"""Silver -> Gold: maior desconto mensal por produto.

Objetivo:
    Para cada produto vendido em cada mês, identificar o maior desconto
    concedido entre todas as vendas daquele mês. O preço de catálogo e a
    categoria acompanham o produto para dar contexto ao desconto.

Entrada de dados:
    Itens de pedido com produto, desconto e mês da venda; produtos tratados
    com preço e categoria.

Saída de dados:
    Uma linha por mês e produto, com o maior desconto concedido naquele mês.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_descontos"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_ORDERS = DATA / "silver" / "orders" / "orders.parquet"
SILVER_DETAILS = DATA / "silver" / "order_details" / "order_details.parquet"
SILVER_PRODUCTS = DATA / "silver" / "products" / "products.parquet"
GOLD = DATA / "gold" / "descontos" / "descontos.parquet"


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


def montar_descontos(orders, details, products):
    """Monta o maior desconto mensal de cada produto vendido.

    Liga cada item ao pedido para obter o mês da venda e ao produto para
    obter nome, categoria e preço de catálogo. Depois agrupa por mês e
    produto, mantendo o maior desconto observado entre as vendas do período.

    Retorna uma linha para cada combinação de mês e produto.
    """
    # Enriquece cada item com o mês da venda e os dados do produto.
    itens = (
        details.select("order_id", "product_id", "discount")
        .join(
            orders.select(
                "order_id",
                F.date_format(F.col("order_date"), "yyyy-MM").alias("ano_mes"),
            ),
            on="order_id",
            how="inner",
        )
        .join(
            products.select(
                "product_id",
                F.col("product_name").alias("produto_nome"),
                "category_id",
                F.col("unit_price").alias("preco_unitario"),
            ),
            on="product_id",
            how="inner",
        )
    )

    # Mantém o maior desconto concedido ao produto dentro de cada mês.
    descontos = (
        itens.groupBy(
            "ano_mes", "product_id", "produto_nome", "category_id", "preco_unitario"
        )
        .agg(F.max("discount").alias("maior_desconto"))
        .select(
            "ano_mes",
            F.col("product_id").alias("produto_id"),
            "produto_nome",
            F.col("category_id").alias("categoria_id"),
            "preco_unitario",
            "maior_desconto",
        )
    )
    return descontos


def validar_resultado(descontos, total_produtos_vendidos_silver):
    """Confere a estrutura e os valores do maior desconto mensal produzido.

    Verifica a unicidade de mês-produto, campos obrigatórios, preço não
    negativo e desconto dentro do intervalo [0, 1]. Também confere que a
    quantidade de produtos distintos não mudou em relação à Silver, o que
    garantiria que o join com o catálogo não perdeu nenhum produto vendido.
    Interrompe o job se alguma conferência falhar.
    """
    total = descontos.count()
    problemas = {
        "chave (ano_mes, produto_id) duplicada": total
        - descontos.select("ano_mes", "produto_id").distinct().count(),
        "produto_id nulo": descontos.filter(F.col("produto_id").isNull()).count(),
        "produto_nome nulo": descontos.filter(F.col("produto_nome").isNull()).count(),
        "categoria_id nulo": descontos.filter(F.col("categoria_id").isNull()).count(),
        "preco_unitario negativo": descontos.filter(F.col("preco_unitario") < 0).count(),
        "maior_desconto fora de [0, 1]": descontos.filter(
            (F.col("maior_desconto") < 0) | (F.col("maior_desconto") > 1)
        ).count(),
        "produtos vendidos perdidos no join": total_produtos_vendidos_silver
        - descontos.select("produto_id").distinct().count(),
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %s ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, agregação, validação e gravação do desconto mensal."""
    # 1. Abre a sessão de processamento.
    log.info("inicio")
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê as três fontes Silver e calcula o total usado na conferência.
    orders, details, products = carregar_dados(spark)
    total_produtos_vendidos_silver = details.select("product_id").distinct().count()
    log.info(
        "silver lido: %d pedidos, %d itens, %d produtos",
        orders.count(), details.count(), products.count(),
    )

    # 3. Agrupa os descontos e valida a chave e os valores calculados.
    gold = montar_descontos(orders, details, products)
    total = validar_resultado(gold, total_produtos_vendidos_silver)

    # 4. Calcula números de controle que serão registrados no log.
    produtos_com_desconto = gold.filter(F.col("maior_desconto") > 0).select("produto_id").distinct().count()
    maior_desconto_geral = gold.agg(F.max("maior_desconto").alias("d")).collect()[0]["d"]

    log.info("linhas mensais: %d", total)
    log.info("produtos distintos: %d", gold.select("produto_id").distinct().count())
    log.info("produtos com algum desconto: %d", produtos_com_desconto)
    log.info("maior desconto observado: %s", f"{maior_desconto_geral:.0%}")

    # 5. Substitui o Parquet Gold pelo desconto mensal validado.
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    gold.write.mode("overwrite").parquet(str(GOLD))
    log.info("gold gravado: %d linhas em %s", total, GOLD)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
