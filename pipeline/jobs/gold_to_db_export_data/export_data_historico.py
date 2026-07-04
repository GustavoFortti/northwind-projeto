"""Gold -> banco de consumo: exportação de tabela histórica (multi-arquivo).

Objetivo:
    Publicar uma tabela Gold histórica, guardada em vários Parquets mensais
    (data/gold/<tabela>/<tabela>-YYYY-MM.parquet - um arquivo por mês
    processado), em um único destino de consumo. Por enquanto o
    funcionamento é direto: encontra todos os Parquets mensais da tabela,
    junta o conteúdo de todos eles e grava tudo em uma única tabela no
    destino - nunca uma tabela por mês.

Entrada de dados:
    Nome da tabela e os Parquets Gold mensais correspondentes
    (data/gold/<tabela>/<tabela>-YYYY-MM.parquet).

Saída de dados:
    Uma única tabela no destino escolhido, com as linhas de todos os meses
    encontrados, substituindo a versão anterior da mesma tabela.

Rodar:
    .venv/bin/python pipeline/jobs/gold_to_db_export_data/export_data_historico.py historico_cliente_metricas
    (normalmente chamado via job.py, que decide entre este script e o
    export_data_consolidado.py de acordo com a tabela pedida)
"""

import argparse
import logging
import sqlite3
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession

JOB = "export_data_historico"
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


def localizar_arquivos_mensais(table: str) -> list:
    """Lista, em ordem, todos os Parquets mensais `<tabela>-YYYY-MM.parquet` da tabela."""
    return sorted(GOLD.glob(f"{table}/{table}-*.parquet"))


def export(spark, target, table, arquivos):
    """Lê todos os Parquets mensais encontrados, junta tudo e grava como uma única tabela.

    O padrão com `*` deixa o próprio DuckDB ler e unir os arquivos que
    baterem com `<tabela>-*.parquet` num só DataFrame, na ordem em que
    foram gerados mês a mês.
    """
    padrao = str(GOLD / table / f"{table}-*.parquet")
    df = spark.read.parquet(padrao).toPandas()
    target.write(table, df)
    log.info(
        "exportado: %s (%d arquivos mensais, %d linhas, %d colunas)",
        table, len(arquivos), len(df), len(df.columns),
    )


def main():
    """Interpreta os argumentos, localiza os Parquets mensais e executa a exportação consolidada."""
    # 1. Lê o nome da tabela, o tipo de destino e o caminho de saída.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", help="tabela historica da gold a exportar (ex.: historico_cliente_metricas)")
    parser.add_argument("--target", default="sqlite", choices=TARGETS)
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    args = parser.parse_args()

    # 2. Localiza os Parquets mensais (data/gold/<tabela>/<tabela>-YYYY-MM.parquet)
    #    e interrompe se nenhum existir.
    arquivos = localizar_arquivos_mensais(args.table)
    if not arquivos:
        disponiveis = sorted({p.parent.name for p in GOLD.glob("*/*-*.parquet")})
        raise FileNotFoundError(
            f"tabela historica '{args.table}' nao tem nenhum parquet mensal na gold; "
            f"disponiveis: {disponiveis}"
        )

    # 3. Abre a sessão de leitura e o destino selecionado.
    log.info(
        "inicio | gold.%s (%d arquivos mensais) -> %s (%s)",
        args.table, len(arquivos), args.target, args.dest,
    )
    spark = SparkSession.builder.getOrCreate()
    target = TARGETS[args.target](args.dest)
    # 4. Junta todos os meses, grava como uma única tabela e fecha o destino ao final.
    try:
        export(spark, target, args.table, arquivos)
    finally:
        target.close()
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
