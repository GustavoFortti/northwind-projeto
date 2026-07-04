"""Gold -> banco de consumo: exportação de tabela de arquivo único.

Objetivo:
    Publicar uma tabela Gold guardada em um único Parquet
    (data/gold/<tabela>/<tabela>.parquet) em um destino de consumo. O
    SQLite do viewer é o destino padrão. A exportação copia o resultado
    final sem transformar valores e substitui a versão anterior da mesma
    tabela.

Entrada de dados:
    Nome da tabela e o arquivo Parquet Gold correspondente
    (data/gold/<tabela>/<tabela>.parquet).

Saída de dados:
    A mesma tabela, com schema e registros preservados, gravada no banco de
    destino escolhido.

Rodar:
    .venv/bin/python pipeline/jobs/gold_to_db_export_data/export_data_consolidado.py ticket_medio
    (normalmente chamado via job.py, que decide entre este script e o
    export_data_historico.py de acordo com a tabela pedida)
"""

import argparse
import logging
import sqlite3
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession

JOB = "export_data_consolidado"
ROOT = Path(__file__).resolve().parents[3]
GOLD = ROOT / "data" / "gold"
LOGS = ROOT / "pipeline" / "logs"
DEFAULT_DEST = ROOT / "viewer" / "data.sqlite"


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


# ── destinos plugáveis ───────────────────────────────────────


class SqliteTarget:
    """Grava cada tabela em um arquivo SQLite (substitui se existir)."""

    def __init__(self, dest: str):
        """Abre o arquivo SQLite de destino, criando sua pasta se necessário."""
        self.path = Path(dest)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)

    def write(self, table: str, df):
        """Substitui a tabela SQLite pelos registros recebidos."""
        df.to_sql(table, self.conn, if_exists="replace", index=False)

    def close(self):
        """Confirma as gravações pendentes e fecha a conexão com o SQLite."""
        self.conn.commit()
        self.conn.close()


TARGETS = {
    "sqlite": SqliteTarget,
    # "bigquery": BigQueryTarget,  # mesmo write(), outro destino
}


# ── job ──────────────────────────────────────────────────────


def export(spark, target, table, parquet):
    """Lê o Parquet Gold único da tabela e envia seus registros ao destino configurado."""
    df = spark.read.parquet(str(parquet)).toPandas()
    target.write(table, df)
    log.info("exportado: %s (%d linhas, %d colunas)", table, len(df), len(df.columns))


def main():
    """Interpreta os argumentos, localiza o Parquet único da tabela e executa a exportação."""
    # 1. Lê o nome da tabela, o tipo de destino e o caminho de saída.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", help="tabela da gold a exportar (ex.: ticket_medio)")
    parser.add_argument("--target", default="sqlite", choices=TARGETS)
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    args = parser.parse_args()

    # 2. Localiza o Parquet único (data/gold/<tabela>/<tabela>.parquet)
    #    e interrompe se ele não existir.
    parquet = GOLD / args.table / f"{args.table}.parquet"
    if not parquet.exists():
        disponiveis = sorted(
            p.parent.name for p in GOLD.glob("*/*.parquet") if p.stem == p.parent.name
        )
        raise FileNotFoundError(
            f"tabela '{args.table}' nao existe na gold como arquivo unico; disponiveis: {disponiveis}"
        )

    # 3. Abre a sessão de leitura e o destino selecionado.
    log.info("inicio | gold.%s -> %s (%s)", args.table, args.target, args.dest)
    spark = SparkSession.builder.getOrCreate()
    target = TARGETS[args.target](args.dest)
    # 4. Copia os dados e garante que o destino seja fechado ao final.
    try:
        export(spark, target, args.table, parquet)
    finally:
        target.close()
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
