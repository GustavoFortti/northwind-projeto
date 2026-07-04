"""Silver -> Gold: produtos comprados no mesmo pedido.

Objetivo:
    Transformar os itens dos pedidos em pares direcionais de co-compra. Um
    pedido com A, B e C produz A->B, A->C, B->A, B->C, C->A e C->B. Essa
    direção permite consultar o que acompanhou qualquer produto escolhido.
    Pedidos com um único produto também são mantidos, sem acompanhante.

Entrada de dados:
    Pedidos com cliente e data; itens com produto e quantidade; cadastro com
    os nomes dos produtos.

Saída de dados:
    Uma linha por pedido, produto comprado e acompanhante, incluindo as
    quantidades e o número de outros produtos presentes no pedido.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_produtos_associados"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_ORDERS = DATA / "silver" / "orders" / "orders.parquet"
SILVER_DETAILS = DATA / "silver" / "order_details" / "order_details.parquet"
SILVER_PRODUCTS = DATA / "silver" / "products" / "products.parquet"
GOLD = DATA / "gold" / "produtos_associados" / "produtos_associados.parquet"


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


def carregar_dados(spark):
    """Lê pedidos, itens e produtos tratados na camada Silver."""
    orders = spark.read.parquet(str(SILVER_ORDERS))
    details = spark.read.parquet(str(SILVER_DETAILS))
    products = spark.read.parquet(str(SILVER_PRODUCTS))
    return orders, details, products


def montar_associacoes(orders, details, products):
    """Transforma os itens dos pedidos em pares direcionais de produtos.

    Primeiro monta uma base com pedido, cliente, data, produto e quantidade.
    Em seguida conta quantos produtos distintos existem em cada pedido e faz
    um auto-relacionamento dos itens: para um pedido com A, B e C, são criados
    A->B, A->C, B->A, B->C, C->A e C->B. A direção permite perguntar diretamente
    quais produtos acompanharam um produto escolhido.

    Pedidos com somente um produto recebem uma linha com acompanhante nulo,
    evitando que desapareçam da base. O retorno tem uma linha por pedido,
    produto comprado e acompanhante.
    """
    # Junta os itens aos dados do pedido e ao nome de cada produto.
    itens = (
        details.select("order_id", "product_id", "quantity")
        .join(
            orders.select(
                "order_id",
                "customer_id",
                F.col("order_date").alias("data_compra"),
                F.date_format(F.col("order_date"), "yyyy-MM").alias("ano_mes"),
            ),
            on="order_id",
            how="inner",
        )
        .join(products.select("product_id", "product_name"), on="product_id", how="inner")
    )

    # Conta quantos produtos diferentes formam cada pedido.
    resumo_pedido = itens.groupBy("order_id").agg(
        F.countDistinct("product_id").alias("total_produtos_distintos")
    )

    # Cria duas visões da mesma lista para formar os pares X -> Y.
    comprado = itens.select(
        F.col("order_id"),
        F.col("ano_mes"),
        F.col("data_compra"),
        F.col("customer_id").alias("id_cliente"),
        F.col("product_id").alias("produto_comprado_id"),
        F.col("product_name").alias("produto_comprado_nome"),
        F.col("quantity").alias("quantidade_comprada"),
    )
    acompanhante = itens.select(
        F.col("order_id"),
        F.col("product_id").alias("produto_acompanhante_id"),
        F.col("product_name").alias("produto_acompanhante_nome"),
        F.col("quantity").alias("quantidade_acompanhante"),
    )

    # Relaciona cada produto a todos os outros produtos do mesmo pedido.
    pares = (
        comprado.join(acompanhante, on="order_id", how="inner")
        .filter(F.col("produto_comprado_id") != F.col("produto_acompanhante_id"))
        .join(resumo_pedido, on="order_id", how="inner")
        .withColumn(
            "quantidade_outros_produtos_distintos",
            F.col("total_produtos_distintos") - 2,
        )
    )

    # Preserva pedidos de um único produto usando acompanhante nulo.
    sozinhos = (
        comprado.join(resumo_pedido, on="order_id", how="inner")
        .filter(F.col("total_produtos_distintos") == 1)
        .withColumn("produto_acompanhante_id", F.lit(None).cast("int"))
        .withColumn("produto_acompanhante_nome", F.lit(None).cast("string"))
        .withColumn("quantidade_acompanhante", F.lit(None).cast("int"))
        .withColumn("quantidade_outros_produtos_distintos", F.lit(0))
    )

    # Alinha o schema dos pares e dos pedidos sem acompanhante antes da união.
    colunas = [
        "ano_mes",
        "data_compra",
        "order_id",
        "id_cliente",
        "produto_comprado_id",
        "produto_comprado_nome",
        "quantidade_comprada",
        "produto_acompanhante_id",
        "produto_acompanhante_nome",
        "quantidade_acompanhante",
        "total_produtos_distintos",
        "quantidade_outros_produtos_distintos",
    ]
    gold = pares.select(*colunas).unionByName(sozinhos.select(*colunas))
    return gold.withColumnRenamed("order_id", "id_compra")


def validar_resultado(gold, total_pedidos_silver):
    """Valida se os pares representam corretamente os pedidos de origem.

    Confere se X nunca é igual a Y, se não há pares repetidos e se todos os
    pedidos Silver aparecem na saída. Também valida as regras dos pedidos de
    um item, a contagem de outros produtos, nomes e quantidades. Interrompe o
    job caso qualquer uma dessas regras seja violada.
    """
    problemas = {
        "produto comprado igual ao acompanhante": gold.filter(
            F.col("produto_comprado_id") == F.col("produto_acompanhante_id")
        ).count(),
        "par duplicado (id_compra, comprado, acompanhante)": gold.count()
        - gold.select(
            "id_compra", "produto_comprado_id", "produto_acompanhante_id"
        ).distinct().count(),
        "pedidos faltando na tabela": total_pedidos_silver
        - gold.select("id_compra").distinct().count(),
        "pedido de 1 produto com acompanhante nao nulo": gold.filter(
            (F.col("total_produtos_distintos") == 1)
            & F.col("produto_acompanhante_id").isNotNull()
        ).count(),
        "par com acompanhante e total_produtos_distintos < 2": gold.filter(
            F.col("produto_acompanhante_id").isNotNull()
            & (F.col("total_produtos_distintos") < 2)
        ).count(),
        "quantidade_outros_produtos_distintos negativa": gold.filter(
            F.col("quantidade_outros_produtos_distintos") < 0
        ).count(),
        "produto_comprado_nome nulo": gold.filter(
            F.col("produto_comprado_nome").isNull()
        ).count(),
        "quantidade_comprada nao positiva": gold.filter(
            F.col("quantidade_comprada") <= 0
        ).count(),
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")


def main():
    """Executa a leitura, criação, validação e gravação dos produtos associados."""
    # 1. Abre a sessão de processamento.
    log.info("inicio")
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê pedidos, itens e produtos da Silver.
    orders, details, products = carregar_dados(spark)
    total_pedidos = orders.select("order_id").distinct().count()
    log.info("silver lido: %d pedidos, %d itens", total_pedidos, details.count())

    # 3. Cria os pares direcionais e valida se todos os pedidos foram preservados.
    gold = montar_associacoes(orders, details, products)
    validar_resultado(gold, total_pedidos)

    # 4. Calcula números de controle sobre pedidos e pares produzidos.
    com_acompanhante = gold.filter(F.col("produto_acompanhante_id").isNotNull()).count()
    sem_acompanhante = gold.filter(F.col("produto_acompanhante_id").isNull()).count()
    pedidos_um_produto = (
        gold.filter(F.col("total_produtos_distintos") == 1).select("id_compra").distinct().count()
    )
    pedidos_com_acompanhante = total_pedidos - pedidos_um_produto
    periodo = gold.agg(
        F.min("data_compra").alias("min"), F.max("data_compra").alias("max")
    ).collect()[0]

    log.info("pedidos totais: %d", total_pedidos)
    log.info("pedidos com 1 produto: %d", pedidos_um_produto)
    log.info("pedidos com acompanhantes: %d", pedidos_com_acompanhante)
    log.info("pares direcionais: %d", com_acompanhante)
    log.info("linhas sem acompanhante: %d", sem_acompanhante)
    log.info("periodo: %s a %s", periodo["min"], periodo["max"])

    # 5. Substitui o Parquet Gold pelo resultado validado.
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    gold.write.mode("overwrite").parquet(str(GOLD))
    log.info("gold gravado: %d linhas em %s", gold.count(), GOLD)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
