"""Bronze -> Silver: pedidos.

Objetivo:
    Limpar os pedidos, ajustar datas e valores, trocar campos vazios por
    nulo e verificar IDs e duplicidades.

Entrada de dados:
    Pedidos brutos com cliente, funcionário, datas, frete e entrega.

Saída de dados:
    Pedidos padronizados e validados, com uma linha por pedido.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "bronze_to_silver_orders"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
BRONZE = DATA / "bronze" / "orders.csv"
SILVER = DATA / "silver" / "orders" / "orders.parquet"


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

DATE_COLS = ["order_date", "required_date", "shipped_date"]
INT_COLS = ["order_id", "employee_id", "ship_via"]
STRING_COLS = [
    "customer_id", "ship_name", "ship_address", "ship_city",
    "ship_region", "ship_postal_code", "ship_country",
]


def transform(bronze):
    """Converte datas, números e textos dos pedidos para os tipos corretos."""
    df = bronze
    for c in INT_COLS:
        df = df.withColumn(c, F.col(c).cast("int"))
    for c in DATE_COLS:
        df = df.withColumn(c, F.col(c).cast("date"))
    for c in STRING_COLS:
        df = df.withColumn(
            c,
            F.when(F.col(c).cast("string") == "", F.lit(None))
             .otherwise(F.col(c).cast("string")),
        )
    df = df.withColumn("freight", F.col("freight").cast("decimal(10,2)"))
    return df


def validate(df):
    """Verifica identificadores, datas obrigatórias, duplicidades e frete."""
    total = df.count()
    problemas = {
        "order_id nulo": df.filter(F.col("order_id").isNull()).count(),
        "order_id duplicado": total - df.select("order_id").distinct().count(),
        "order_date nula": df.filter(F.col("order_date").isNull()).count(),
        "freight negativo": df.filter(F.col("freight") < 0).count(),
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, limpeza, validação e gravação dos pedidos."""
    # 1. Abre a sessão usada para ler e transformar os dados.
    log.info("inicio | bronze=%s", BRONZE)
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê os pedidos brutos.
    bronze = spark.read.csv(str(BRONZE), header=True, sep=";")
    log.info("bronze lido: %d linhas", bronze.count())

    # 3. Ajusta os tipos e valida os pedidos transformados.
    silver = transform(bronze)
    total = validate(silver)

    # 4. Substitui a tabela Silver pelos pedidos validados.
    SILVER.parent.mkdir(parents=True, exist_ok=True)
    silver.write.mode("overwrite").parquet(str(SILVER))
    log.info("silver gravado: %d linhas em %s", total, SILVER)

    # 5. Informa quantos pedidos ainda não possuem data de envio.
    nao_entregues = silver.filter(F.col("shipped_date").isNull()).count()
    log.info("pedidos sem shipped_date (nao entregues): %d", nao_entregues)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
