"""Silver -> Gold: histórico mensal de produtos por cliente.

Objetivo:
    Construir o histórico mensal de consumo por cliente e produto. O script
    liga os itens aos pedidos, clientes e produtos e depois agrupa as compras
    do mesmo mês. Para cada grupo, soma unidades e receita.

Entrada de dados:
    Pedidos com cliente e data; itens com produto, quantidade e receita;
    cadastros com os nomes dos clientes e produtos.

Saída de dados:
    Uma linha por mês, cliente e produto (com a categoria/grupo do produto,
    categoria_id). A série mensal é preservada, em vez de gerar somente um
    total acumulado por cliente.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_historico_cliente_produtos"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_ORDERS = DATA / "silver" / "orders" / "orders.parquet"
SILVER_DETAILS = DATA / "silver" / "order_details" / "order_details.parquet"
SILVER_CUSTOMERS = DATA / "silver" / "customers" / "customers.parquet"
SILVER_PRODUCTS = DATA / "silver" / "products" / "products.parquet"
GOLD = DATA / "gold" / "historico_cliente_produtos" / "historico_cliente_produtos.parquet"


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
    """Lê pedidos, itens, clientes e produtos tratados na camada Silver."""
    orders = spark.read.parquet(str(SILVER_ORDERS))
    details = spark.read.parquet(str(SILVER_DETAILS))
    customers = spark.read.parquet(str(SILVER_CUSTOMERS))
    products = spark.read.parquet(str(SILVER_PRODUCTS))
    return orders, details, customers, products


def montar_historico(orders, details, customers, products):
    """Monta o histórico mensal de consumo de cada cliente.

    Primeiro liga cada item ao pedido para obter cliente, data e mês. Depois
    acrescenta os nomes do cliente e do produto. Por fim, agrupa por mês,
    cliente e produto, somando unidades e receita.

    Retorna uma linha para cada combinação de mês, cliente e produto.
    """
    # Enriquece cada item com o cliente, o mês e os nomes usados na saída.
    itens = (
        details.select("order_id", "product_id", "quantity", "receita_item")
        .join(
            orders.select(
                "order_id",
                "customer_id",
                "order_date",
                F.date_format(F.col("order_date"), "yyyy-MM").alias("ano_mes"),
            ),
            on="order_id",
            how="inner",
        )
        .join(
            customers.select("customer_id", F.col("company_name").alias("nome_empresa")),
            on="customer_id",
            how="inner",
        )
        .join(
            products.select(
                "product_id",
                F.col("product_name").alias("produto_nome"),
                "category_id",
            ),
            on="product_id",
            how="inner",
        )
    )

    # Resume todas as compras do mesmo cliente e produto dentro de cada mês.
    historico = (
        itens.groupBy(
            "ano_mes", "customer_id", "nome_empresa", "product_id", "produto_nome", "category_id"
        )
        .agg(
            F.sum("quantity").alias("quantidade_consumida"),
            F.sum("receita_item").cast("decimal(14,2)").alias("receita_total"),
        )
        .select(
            "ano_mes",
            F.col("customer_id").alias("cliente_id"),
            "nome_empresa",
            F.col("product_id").alias("produto_id"),
            "produto_nome",
            F.col("category_id").alias("categoria_id"),
            "quantidade_consumida",
            "receita_total",
        )
    )
    return historico


def validar_resultado(historico, total_quantidade_silver, total_receita_silver):
    """Confere a estrutura e os totais do histórico produzido.

    Verifica a unicidade de mês-cliente-produto, campos obrigatórios e
    métricas positivas. Também soma quantidade e receita na Gold e compara
    com a Silver, garantindo que os joins e agrupamentos não perderam nem
    duplicaram valores. Interrompe o job se alguma conferência falhar.
    """
    total = historico.count()
    problemas = {
        "chave (ano_mes, cliente_id, produto_id) duplicada": total
        - historico.select("ano_mes", "cliente_id", "produto_id").distinct().count(),
        "cliente_id nulo": historico.filter(F.col("cliente_id").isNull()).count(),
        "produto_id nulo": historico.filter(F.col("produto_id").isNull()).count(),
        "nome_empresa nulo": historico.filter(F.col("nome_empresa").isNull()).count(),
        "produto_nome nulo": historico.filter(F.col("produto_nome").isNull()).count(),
        "categoria_id nulo": historico.filter(F.col("categoria_id").isNull()).count(),
        "quantidade_consumida nao positiva": historico.filter(
            F.col("quantidade_consumida") <= 0
        ).count(),
        "receita_total negativa": historico.filter(F.col("receita_total") < 0).count(),
        "soma quantidade_consumida != silver": abs(
            historico.agg(F.sum("quantidade_consumida").alias("q")).collect()[0]["q"]
            - total_quantidade_silver
        ),
        "soma receita_total != silver": abs(
            float(historico.agg(F.sum("receita_total").alias("r")).collect()[0]["r"])
            - float(total_receita_silver)
        )
        > 0.01,
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %s ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, agregação, validação e gravação do histórico mensal."""
    # 1. Abre a sessão de processamento.
    log.info("inicio")
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê as quatro fontes Silver e calcula os totais usados na conferência.
    orders, details, customers, products = carregar_dados(spark)
    total_quantidade_silver = details.agg(F.sum("quantity").alias("q")).collect()[0]["q"]
    total_receita_silver = details.agg(F.sum("receita_item").alias("r")).collect()[0]["r"]
    log.info(
        "silver lido: %d pedidos, %d itens, %d clientes, %d produtos",
        orders.count(), details.count(), customers.count(), products.count(),
    )

    # 3. Agrupa as compras e valida a chave e os totais calculados.
    gold = montar_historico(orders, details, customers, products)
    total = validar_resultado(gold, total_quantidade_silver, total_receita_silver)

    # 4. Calcula números de controle que serão registrados no log.
    pares_distintos = gold.select("cliente_id", "produto_id").distinct().count()
    clientes_com_compras = gold.select("cliente_id").distinct().count()
    produtos_comprados = gold.select("produto_id").distinct().count()
    unidades = gold.agg(F.sum("quantidade_consumida").alias("q")).collect()[0]["q"]
    receita = gold.agg(F.sum("receita_total").alias("r")).collect()[0]["r"]

    log.info("linhas mensais: %d", total)
    log.info("pares distintos cliente-produto: %d", pares_distintos)
    log.info("clientes com compras: %d", clientes_com_compras)
    log.info("produtos comprados: %d", produtos_comprados)
    log.info("unidades: %s", f"{unidades:,.0f}")
    log.info("receita: %s", f"{receita:,.2f}")

    # 5. Substitui o Parquet Gold pelo histórico validado.
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
