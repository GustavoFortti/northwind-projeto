"""Bronze -> Silver: produtos.

Objetivo:
    Limpar o cadastro de produtos, ajustar os tipos e verificar IDs, nomes,
    preços e duplicidades.

Entrada de dados:
    Produtos brutos com categoria, fornecedor, embalagem, preço e estoque.

Saída de dados:
    Catálogo padronizado e validado, com uma linha por produto.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "bronze_to_silver_products"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
BRONZE = DATA / "bronze" / "products.csv"
SILVER = DATA / "silver" / "products" / "products.parquet"


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


def transform(bronze):
    """Converte os campos do produto para os tipos usados na camada Silver."""
    return (
        bronze
        .withColumn("product_id", F.col("product_id").cast("int"))
        .withColumn("product_name", F.col("product_name").cast("string"))
        .withColumn("supplier_id", F.col("supplier_id").cast("int"))
        .withColumn("category_id", F.col("category_id").cast("int"))
        .withColumn("quantity_per_unit", F.col("quantity_per_unit").cast("string"))
        .withColumn("unit_price", F.col("unit_price").cast("decimal(10,2)"))
        .withColumn("units_in_stock", F.col("units_in_stock").cast("int"))
        .withColumn("units_on_order", F.col("units_on_order").cast("int"))
        .withColumn("reorder_level", F.col("reorder_level").cast("int"))
        .withColumn("discontinued", F.col("discontinued").cast("int"))
    )


def validate(df):
    """Verifica IDs, nomes, preços, duplicidades e indicador de descontinuação."""
    total = df.count()
    problemas = {
        "product_id nulo": df.filter(F.col("product_id").isNull()).count(),
        "product_id duplicado": total - df.select("product_id").distinct().count(),
        "product_name nulo": df.filter(F.col("product_name").isNull()).count(),
        "unit_price negativo": df.filter(F.col("unit_price") < 0).count(),
        "discontinued fora de [0, 1]": df.filter(
            (F.col("discontinued") < 0) | (F.col("discontinued") > 1)
        ).count(),
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, transformação, validação e gravação dos produtos."""
    # 1. Abre a sessão usada para ler e transformar os dados.
    log.info("inicio | bronze=%s", BRONZE.name)
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê o catálogo bruto de produtos.
    bronze = spark.read.csv(str(BRONZE), header=True, sep=";")
    log.info("bronze lido: %d produtos", bronze.count())

    # 3. Ajusta os tipos e valida o catálogo transformado.
    silver = transform(bronze)
    total = validate(silver)

    # 4. Substitui a tabela Silver pelo catálogo validado.
    SILVER.parent.mkdir(parents=True, exist_ok=True)
    silver.write.mode("overwrite").parquet(str(SILVER))
    log.info("silver gravado: %d produtos em %s", total, SILVER)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
