"""Silver -> Gold: orquestração de clientes.

Objetivo:
    Executar a criação da tabela de clientes e exportar o resultado para o
    banco consumido pela aplicação.

Entrada de dados:
    Cadastro Silver já limpo, com uma linha por cliente.

Saída de dados:
    Dimensão Gold de clientes e sua cópia no banco da aplicação.
"""

import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

JOB = "silver_to_gold_clientes"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LOGS = ROOT / "pipeline" / "logs"

SCRIPTS = [
    "clientes.py",
]
TABLES = [
    "clientes",
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
    """Executa o processamento de clientes e exporta a tabela gerada."""
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
