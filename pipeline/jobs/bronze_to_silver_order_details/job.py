"""Bronze -> Silver: itens dos pedidos.

Objetivo:
    Preparar cada item vendido para uso nas análises. O script converte os
    campos para os tipos corretos e calcula receita_item como preço vezes
    quantidade, descontando o percentual aplicado. Também verifica valores
    inválidos, pares pedido-produto repetidos e itens sem pedido correspondente.

Entrada de dados:
    Linhas brutas com pedido, produto, preço, quantidade e desconto aplicado.

Saída de dados:
    Uma linha validada por produto dentro de cada pedido, com preço,
    quantidade, desconto e receita líquida calculada.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "bronze_to_silver_order_details"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
BRONZE = DATA / "bronze" / "order_details.csv"
SILVER = DATA / "silver" / "order_details" / "order_details.parquet"
SILVER_ORDERS = DATA / "silver" / "orders" / "orders.parquet"


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
    """Ajusta os tipos dos itens e calcula a receita líquida de cada linha."""
    return (
        bronze
        .withColumn("order_id", F.col("order_id").cast("int"))
        .withColumn("product_id", F.col("product_id").cast("int"))
        .withColumn("unit_price", F.col("unit_price").cast("decimal(10,2)"))
        .withColumn("quantity", F.col("quantity").cast("int"))
        .withColumn("discount", F.col("discount").cast("decimal(4,2)"))
        .withColumn(
            "receita_item",
            F.round(
                F.col("unit_price") * F.col("quantity") * (1 - F.col("discount")),
                2,
            ).cast("decimal(12,2)"),
        )
    )


def validate(df, spark):
    """Valida a consistência dos itens antes da gravação.

    Confere se cada par pedido-produto é único, se quantidade, preço e
    desconto estão dentro dos limites aceitos e, quando a tabela de pedidos
    existe, verifica se todo item aponta para um pedido conhecido. Interrompe
    o job ao encontrar problemas e devolve a quantidade de linhas válidas.
    """
    total = df.count()
    pk_distinta = df.select("order_id", "product_id").distinct().count()
    problemas = {
        "PK (order_id, product_id) duplicada": total - pk_distinta,
        "quantity <= 0": df.filter(F.col("quantity") <= 0).count(),
        "unit_price < 0": df.filter(F.col("unit_price") < 0).count(),
        "discount fora de [0, 1]": df.filter(
            (F.col("discount") < 0) | (F.col("discount") > 1)
        ).count(),
    }

    # integridade referencial: todo item aponta para um pedido existente
    if SILVER_ORDERS.exists():
        orders = spark.read.parquet(str(SILVER_ORDERS)).select("order_id")
        orfaos = df.join(orders, on="order_id", how="left_anti").count()
        problemas["order_id sem pedido na silver.orders"] = orfaos
    else:
        log.warning("silver/orders/orders.parquet ausente, FK nao checada")

    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, transformação, validação e gravação dos itens."""
    # 1. Abre a sessão usada para ler e transformar os dados.
    log.info("inicio | bronze=%s", BRONZE)
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê as linhas brutas dos itens dos pedidos.
    bronze = spark.read.csv(str(BRONZE), header=True, sep=";")
    log.info("bronze lido: %d linhas", bronze.count())

    # 3. Converte os campos, calcula receita_item e valida o resultado.
    silver = transform(bronze)
    total = validate(silver, spark)

    # 4. Substitui a tabela Silver pelos itens validados.
    SILVER.parent.mkdir(parents=True, exist_ok=True)
    silver.write.mode("overwrite").parquet(str(SILVER))
    log.info("silver gravado: %d linhas em %s", total, SILVER)

    # 5. Registra a receita total apenas como conferência da execução.
    receita = silver.agg(F.sum("receita_item").alias("r")).collect()[0]["r"]
    log.info("receita total (conferencia): %s", f"{receita:,.2f}")
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
