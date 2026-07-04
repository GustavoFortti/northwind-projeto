"""Silver -> Gold: orquestração de produtos associados.

Objetivo:
    Executar a criação dos pares de produtos comprados juntos e exportar o
    resultado para o banco consumido pela aplicação.

Entrada de dados:
    Pedidos, seus itens e o cadastro de produtos tratados.

Saída de dados:
    Tabela Gold com pares de produtos por pedido, também disponível no banco.
"""

import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

JOB = "silver_to_gold_produtos_associados"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOGS = ROOT / "pipeline" / "logs"

SCRIPTS = [
    "produtos_associados.py",
]
TABLES = [
    "produtos_associados",
]
EXPORT_JOB = ROOT / "pipeline" / "jobs" / "gold_to_db_export_data" / "job.py"


def setup_logger():
    """Configura os logs do orquestrador no terminal e em arquivo diário."""
    LOGS.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(JOB)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for handler in (
        logging.StreamHandler(),
        logging.FileHandler(LOGS / f"{JOB}_{date.today():%Y%m%d}.log", encoding="utf-8"),
    ):
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger


log = setup_logger()


def main():
    """Executa a criação dos produtos associados e exporta a tabela gerada."""
    # 1. Executa os scripts que criam as tabelas Gold deste job.
    log.info("inicio | %d script(s): %s", len(SCRIPTS), ", ".join(SCRIPTS))
    for script in SCRIPTS:
        log.info("executando %s ...", script)
        subprocess.run([sys.executable, str(HERE / script)], check=True)
        log.info("%s concluido", script)
    # 2. Exporta cada tabela criada para o banco consumido pelo viewer.
    for table in TABLES:
        log.info("exportando gold.%s para o viewer ...", table)
        subprocess.run(
            [sys.executable, str(EXPORT_JOB), table],
            check=True,
        )
        log.info("gold.%s exportada", table)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
