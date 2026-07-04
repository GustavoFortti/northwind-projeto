"""Gold -> banco de consumo: orquestrador da exportação.

Objetivo:
    Receber o nome de uma tabela Gold e decidir qual exportador usar:

        export_data_consolidado.py -> tabela em arquivo único
            (data/gold/<tabela>/<tabela>.parquet)
        export_data_historico.py -> tabela histórica em vários arquivos
            mensais (data/gold/<tabela>/<tabela>-YYYY-MM.parquet), juntados
            em uma única tabela no destino

    Delega a exportação ao script correspondente (como os demais
    orquestradores da pipeline, via subprocess) e propaga o erro se ele
    falhar. Mantém a mesma interface de linha de comando de antes, então
    nenhum chamador (os `job.py` de silver_to_gold_*) precisa mudar.

Entrada de dados:
    Nome da tabela a exportar, tipo de destino e caminho de destino.

Saída de dados:
    A mesma tabela publicada no destino escolhido (por padrão, o SQLite do
    viewer), como arquivo único ou consolidação histórica, decidido
    automaticamente a partir do que existir na gold.

Rodar:
    .venv/bin/python pipeline/jobs/gold_to_db_export_data/job.py ticket_medio
    .venv/bin/python pipeline/jobs/gold_to_db_export_data/job.py historico_cliente_metricas
"""

import argparse
import logging
import subprocess
import sys
from datetime import date
from pathlib import Path

JOB = "gold_to_db_export_data"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GOLD = ROOT / "data" / "gold"
LOGS = ROOT / "pipeline" / "logs"
DEFAULT_DEST = ROOT / "viewer" / "data.sqlite"

CONSOLIDADO = HERE / "export_data_consolidado.py"
HISTORICO = HERE / "export_data_historico.py"

TARGETS_SUPORTADOS = ("sqlite",)


def setup_logger():
    """Configura os logs do job no terminal e em um arquivo diário."""
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


def escolher_exportador(table: str) -> Path:
    """Decide qual script exportador usar para a tabela pedida.

    Primeiro procura o arquivo único (data/gold/<tabela>/<tabela>.parquet):
    se existir, a tabela é "consolidada" e usa export_data_consolidado.py.
    Senão, procura ao menos um Parquet mensal
    (data/gold/<tabela>/<tabela>-YYYY-MM.parquet): se existir, a tabela é
    "histórica" e usa export_data_historico.py. Se nenhum dos dois existir,
    interrompe com erro listando as tabelas disponíveis nos dois formatos.
    """
    unico = GOLD / table / f"{table}.parquet"
    if unico.exists():
        return CONSOLIDADO

    mensais = sorted(GOLD.glob(f"{table}/{table}-*.parquet"))
    if mensais:
        return HISTORICO

    disponiveis_unicos = sorted(
        p.parent.name for p in GOLD.glob("*/*.parquet") if p.stem == p.parent.name
    )
    disponiveis_historicos = sorted({p.parent.name for p in GOLD.glob("*/*-*.parquet")})
    raise FileNotFoundError(
        f"tabela '{table}' nao existe na gold; "
        f"disponiveis (arquivo unico): {disponiveis_unicos}; "
        f"disponiveis (historico mensal): {disponiveis_historicos}"
    )


def main():
    """Lê os argumentos, escolhe o exportador certo para a tabela e delega a execução."""
    # 1. Lê o nome da tabela, o tipo de destino e o caminho de saída.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "table", help="tabela da gold a exportar (ex.: ticket_medio, historico_cliente_metricas)"
    )
    parser.add_argument("--target", default="sqlite", choices=TARGETS_SUPORTADOS)
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    args = parser.parse_args()

    # 2. Decide entre o exportador de arquivo único e o de histórico mensal.
    script = escolher_exportador(args.table)
    log.info("tabela '%s' -> %s", args.table, script.name)

    # 3. Delega a exportação ao script escolhido, com os mesmos argumentos.
    subprocess.run(
        [sys.executable, str(script), args.table, "--target", args.target, "--dest", args.dest],
        check=True,
    )
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
