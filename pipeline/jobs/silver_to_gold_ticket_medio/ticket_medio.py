"""Silver -> Gold: resumo mensal das vendas.

Objetivo:
    Construir o resumo mensal das vendas em duas etapas. Primeiro agrega os
    itens para formar uma linha por pedido; depois agrupa os pedidos por mês.
    Isso evita repetir pedido ou frete e permite calcular ticket, receita,
    itens, unidades, preço médio, desconto efetivo e frete médio corretamente.

Entrada de dados:
    Pedidos com identificador, data e frete; itens com preço, quantidade,
    desconto e receita líquida.

Saída de dados:
    Uma linha por mês com quantidade de pedidos, receita, ticket médio e os
    componentes usados para explicar sua variação.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_ticket_medio"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_ORDERS = DATA / "silver" / "orders" / "orders.parquet"
SILVER_DETAILS = DATA / "silver" / "order_details" / "order_details.parquet"
GOLD = DATA / "gold" / "ticket_medio" / "ticket_medio.parquet"


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


def base_pedidos(orders, details):
    """Cria a base intermediária no nível de pedido.

    Soma receita bruta e líquida, quantidade de itens e unidades de cada
    pedido. Depois acrescenta data e frete e deriva o mês da compra. Essa base
    evita calcular indicadores mensais diretamente sobre linhas de itens, o
    que poderia contar o mesmo pedido ou frete várias vezes.
    """
    return (
        details
        .groupBy("order_id")
        .agg(
            F.sum("receita_item").alias("ticket"),
            F.sum(F.col("unit_price") * F.col("quantity")).alias("bruto"),
            F.count(F.lit(1)).alias("itens"),
            F.sum("quantity").alias("unidades"),
        )
        .join(
            orders.select("order_id", "order_date", F.col("freight").alias("frete")),
            on="order_id",
            how="inner",
        )
        .withColumn("ano_mes", F.date_format(F.col("order_date"), "yyyy-MM"))
    )


def transform(orders, details):
    """Transforma a base por pedido em um resumo mensal de vendas.

    Para cada mês, conta pedidos, soma receita e calcula médias de ticket,
    unidades, itens e frete. O preço médio considera o valor bruto por unidade;
    o desconto efetivo compara a receita líquida com a receita bruta. Retorna
    uma linha por mês, ordenada cronologicamente.
    """
    pedido = base_pedidos(orders, details)

    # grão de mês: ticket e seus componentes na mesma fonte
    return (
        pedido
        .groupBy("ano_mes")
        .agg(
            F.count("order_id").alias("qtd_pedidos"),
            F.sum("ticket").cast("decimal(14,2)").alias("receita_total"),
            F.round(F.avg("ticket"), 2).cast("decimal(12,2)").alias("ticket_medio"),
            F.round(F.avg("unidades"), 2).alias("unidades_por_pedido"),
            F.round(F.avg("itens"), 3).alias("itens_por_pedido"),
            F.round(F.sum("bruto") / F.sum("unidades"), 2).alias("preco_medio"),
            F.round(1 - F.sum("ticket") / F.sum("bruto"), 4)
                .alias("desconto_efetivo"),
            F.round(F.avg("frete"), 2).alias("frete_por_pedido"),
        )
        .orderBy("ano_mes")
    )


def validate(df, total_pedidos_silver):
    """Confere se o resumo mensal possui métricas válidas e está completo.

    Verifica mês preenchido, ticket positivo, desconto entre zero e um e frete
    não negativo. Depois soma a quantidade mensal de pedidos e compara com a
    Silver para detectar perdas no join ou na agregação. Interrompe o job ao
    encontrar qualquer inconsistência.
    """
    problemas = {
        "ano_mes nulo": df.filter(F.col("ano_mes").isNull()).count(),
        "ticket_medio <= 0": df.filter(F.col("ticket_medio") <= 0).count(),
        "desconto_efetivo fora de [0, 1]": df.filter(
            (F.col("desconto_efetivo") < 0) | (F.col("desconto_efetivo") > 1)
        ).count(),
        "frete_por_pedido negativo": df.filter(F.col("frete_por_pedido") < 0).count(),
        "pedidos perdidos no join": total_pedidos_silver
        - df.agg(F.sum("qtd_pedidos").alias("q")).collect()[0]["q"],
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")


def main():
    """Executa a leitura, agregação, validação e gravação do resumo mensal."""
    # 1. Abre a sessão de processamento.
    log.info("inicio | silver=%s + %s", SILVER_ORDERS.name, SILVER_DETAILS.name)
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê pedidos e itens da Silver e registra as quantidades recebidas.
    orders = spark.read.parquet(str(SILVER_ORDERS))
    details = spark.read.parquet(str(SILVER_DETAILS))
    total_pedidos = orders.count()
    log.info("silver lido: %d pedidos, %d itens", total_pedidos, details.count())

    # 3. Monta o resumo mensal e valida se todos os pedidos foram considerados.
    gold = transform(orders, details)
    validate(gold, total_pedidos)

    # 4. Substitui o Parquet Gold pelo resumo validado.
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    gold.write.mode("overwrite").parquet(str(GOLD))
    log.info("gold gravado: %d meses em %s", gold.count(), GOLD)

    # 5. Calcula o ticket global para conferência do resultado mensal.
    tot = gold.agg(
        F.sum("receita_total").alias("receita"),
        F.sum("qtd_pedidos").alias("pedidos"),
    ).collect()[0]
    log.info(
        "ticket medio global: %s (receita %s / %d pedidos)",
        f"{tot['receita'] / tot['pedidos']:,.2f}",
        f"{tot['receita']:,.2f}",
        tot["pedidos"],
    )
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
