"""Silver -> Gold: volume mensal de compra por cliente.

Objetivo:
    Mostrar o volume mensal de compra de cada cliente, sem separar por
    produto: quanto ele gastou (antes e depois de descontos), em quantos
    pedidos, com quantos produtos distintos e quantos itens no total, em
    cada mês.

Entrada de dados:
    Pedidos com cliente e data; itens com produto, quantidade, preço
    unitário e receita já com desconto aplicado; cadastro com o nome dos
    clientes.

Saída de dados:
    Uma linha por mês e cliente, com o valor bruto, a receita após desconto,
    o desconto médio ponderado e as demais métricas agregadas do mês.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_historico_cliente_volume"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_ORDERS = DATA / "silver" / "orders" / "orders.parquet"
SILVER_DETAILS = DATA / "silver" / "order_details" / "order_details.parquet"
SILVER_CUSTOMERS = DATA / "silver" / "customers" / "customers.parquet"
GOLD = DATA / "gold" / "historico_cliente_volume" / "historico_cliente_volume.parquet"


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
    """Lê pedidos, itens e clientes tratados na camada Silver."""
    orders = spark.read.parquet(str(SILVER_ORDERS))
    details = spark.read.parquet(str(SILVER_DETAILS))
    customers = spark.read.parquet(str(SILVER_CUSTOMERS))
    return orders, details, customers


def montar_volume(orders, details, customers):
    """Monta o volume mensal de compra de cada cliente.

    Liga cada item ao pedido para obter cliente, data e mês, e acrescenta o
    nome da empresa. Depois agrupa por mês e cliente (sem entrar no detalhe
    de produto) e calcula, para cada grupo:

    - receita_sem_desconto: valor bruto dos itens, unit_price × quantity,
      antes de qualquer desconto - não é "receita perdida", é só a
      referência para medir o desconto aplicado;
    - receita_total: receita_item somado, ou seja, o valor já com o
      desconto de cada item aplicado (o que de fato entrou);
    - desconto_medio: o desconto médio ponderado pelo valor bruto de cada
      item (1 - receita_total / receita_sem_desconto), e não a média
      simples dos percentuais de desconto - a média simples trataria um
      item de R$ 10 com 50% de desconto igual a um item de R$ 1.000 com
      50%, mascarando o efeito real no faturamento;
    - pedidos distintos, produtos distintos e total de itens comprados.

    Retorna uma linha para cada combinação de mês e cliente.
    """
    # Enriquece cada item com o cliente, o mês e o nome usado na saída.
    itens = (
        details.select("order_id", "product_id", "quantity", "unit_price", "receita_item")
        .join(
            orders.select(
                "order_id",
                "customer_id",
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
    )

    # Resume todas as compras do cliente dentro de cada mês, sem separar por produto.
    volume = (
        itens.groupBy("ano_mes", "customer_id", "nome_empresa")
        .agg(
            F.sum(F.col("unit_price") * F.col("quantity"))
                .cast("decimal(14,2)").alias("receita_sem_desconto"),
            F.sum("receita_item").cast("decimal(14,2)").alias("receita_total"),
            F.countDistinct("order_id").alias("quantidade_pedidos"),
            F.countDistinct("product_id").alias("quantidade_produtos_distintos"),
            F.sum("quantity").alias("quantidade_itens"),
        )
        # desconto médio ponderado pelo valor bruto do mês; sem pedido no mês
        # o bruto seria 0, então retorna 0 em vez de dividir por zero.
        .withColumn(
            "desconto_medio",
            F.when(F.col("receita_sem_desconto") == 0, F.lit(0.0))
                .otherwise(F.round(1 - (F.col("receita_total") / F.col("receita_sem_desconto")), 4)),
        )
        .select(
            "ano_mes",
            F.col("customer_id").alias("cliente_id"),
            "nome_empresa",
            "receita_sem_desconto",
            "receita_total",
            "desconto_medio",
            "quantidade_pedidos",
            "quantidade_produtos_distintos",
            "quantidade_itens",
        )
        .orderBy("ano_mes", "cliente_id")
    )
    return volume


def validar_resultado(
    volume,
    total_pedidos_silver,
    total_itens_silver,
    total_receita_silver,
    total_bruto_silver,
):
    """Confere a estrutura e os totais do volume mensal produzido.

    Verifica a unicidade de mês-cliente, campos obrigatórios, métricas
    positivas e a consistência entre valor bruto, receita após desconto e
    desconto médio. Também soma pedidos, itens, receita e valor bruto na
    Gold e compara com a Silver, garantindo que os joins e agrupamentos não
    perderam nem duplicaram valores. Interrompe o job se alguma conferência
    falhar.
    """
    total = volume.count()
    problemas = {
        "chave (ano_mes, cliente_id) duplicada": total
        - volume.select("ano_mes", "cliente_id").distinct().count(),
        "ano_mes nulo": volume.filter(F.col("ano_mes").isNull()).count(),
        "cliente_id nulo": volume.filter(F.col("cliente_id").isNull()).count(),
        "nome_empresa nulo": volume.filter(F.col("nome_empresa").isNull()).count(),
        "quantidade_pedidos nao positiva": volume.filter(
            F.col("quantidade_pedidos") <= 0
        ).count(),
        "quantidade_produtos_distintos nao positiva": volume.filter(
            F.col("quantidade_produtos_distintos") <= 0
        ).count(),
        "quantidade_itens nao positiva": volume.filter(
            F.col("quantidade_itens") <= 0
        ).count(),
        "receita_sem_desconto negativa": volume.filter(
            F.col("receita_sem_desconto") < 0
        ).count(),
        "receita_total negativa": volume.filter(F.col("receita_total") < 0).count(),
        "receita_sem_desconto menor que receita_total": volume.filter(
            F.col("receita_sem_desconto") < F.col("receita_total")
        ).count(),
        "desconto_medio fora de [0, 1]": volume.filter(
            (F.col("desconto_medio") < 0) | (F.col("desconto_medio") > 1)
        ).count(),
        "soma quantidade_itens != silver": abs(
            volume.agg(F.sum("quantidade_itens").alias("q")).collect()[0]["q"]
            - total_itens_silver
        ),
        "soma receita_sem_desconto != silver": abs(
            float(volume.agg(F.sum("receita_sem_desconto").alias("b")).collect()[0]["b"])
            - float(total_bruto_silver)
        )
        > 0.01,
        "soma receita_total != silver": abs(
            float(volume.agg(F.sum("receita_total").alias("r")).collect()[0]["r"])
            - float(total_receita_silver)
        )
        > 0.01,
        "soma quantidade_pedidos != total de pedidos distintos da silver": abs(
            volume.agg(F.sum("quantidade_pedidos").alias("p")).collect()[0]["p"]
            - total_pedidos_silver
        ),
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %s ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, agregação, validação e gravação do volume mensal."""
    # 1. Abre a sessão de processamento.
    log.info("inicio")
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê as três fontes Silver e calcula os totais usados na conferência.
    orders, details, customers = carregar_dados(spark)
    total_pedidos_silver = orders.select("order_id").distinct().count()
    total_itens_silver = details.agg(F.sum("quantity").alias("q")).collect()[0]["q"]
    total_receita_silver = details.agg(F.sum("receita_item").alias("r")).collect()[0]["r"]
    total_bruto_silver = details.agg(
        F.sum(F.col("unit_price") * F.col("quantity")).alias("b")
    ).collect()[0]["b"]
    log.info(
        "silver lido: %d pedidos, %d itens, %d clientes",
        total_pedidos_silver, details.count(), customers.count(),
    )

    # 3. Agrupa as compras por mês e cliente.
    gold = montar_volume(orders, details, customers)

    # 4. Valida a chave, os campos obrigatórios e os totais calculados.
    total = validar_resultado(
        gold,
        total_pedidos_silver,
        total_itens_silver,
        total_receita_silver,
        total_bruto_silver,
    )

    # 5. Registra os números finais de controle.
    clientes_com_compras = gold.select("cliente_id").distinct().count()
    bruto = gold.agg(F.sum("receita_sem_desconto").alias("b")).collect()[0]["b"]
    receita = gold.agg(F.sum("receita_total").alias("r")).collect()[0]["r"]
    itens = gold.agg(F.sum("quantidade_itens").alias("q")).collect()[0]["q"]
    pedidos = gold.agg(F.sum("quantidade_pedidos").alias("p")).collect()[0]["p"]
    desconto_medio_global = 1 - (float(receita) / float(bruto)) if bruto else 0.0

    log.info("linhas mensais: %d", total)
    log.info("clientes com compras: %d", clientes_com_compras)
    log.info("pedidos (soma mensal): %d", pedidos)
    log.info("itens: %s", f"{itens:,.0f}")
    log.info("receita sem desconto: %s", f"{bruto:,.2f}")
    log.info("receita apos desconto: %s", f"{receita:,.2f}")
    log.info("desconto medio global: %s", f"{desconto_medio_global:.2%}")

    # 6. Grava o Parquet Gold.
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
