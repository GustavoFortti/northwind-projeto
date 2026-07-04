"""Silver -> Gold: catálogo de produtos.

Objetivo:
    Montar o catálogo final usado pela aplicação. Cada produto tratado é
    ligado aos cadastros de categoria e fornecedor pelos respectivos IDs.
    Os joins preservam o produto mesmo se uma descrição auxiliar estiver
    ausente, e os campos finais são renomeados para português.

Entrada de dados:
    Produtos tratados com IDs e dados comerciais; categorias e fornecedores
    com os nomes que serão acrescentados ao catálogo.

Saída de dados:
    Uma linha por produto, com categoria, fornecedor, embalagem, preço e
    demais dados do catálogo em português.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_produtos"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_PRODUCTS = DATA / "silver" / "products" / "products.parquet"
BRONZE_CATEGORIES = DATA / "bronze" / "categories.csv"
BRONZE_SUPPLIERS = DATA / "bronze" / "suppliers.csv"
GOLD = DATA / "gold" / "produtos" / "produtos.parquet"


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
    """Lê produtos, categorias e fornecedores usados para montar o catálogo."""
    products = spark.read.parquet(str(SILVER_PRODUCTS))
    categories = (
        spark.read.csv(str(BRONZE_CATEGORIES), header=True, sep=";")
        .select(
            F.col("category_id").cast("int").alias("category_id"),
            F.col("category_name").cast("string").alias("categoria_nome"),
        )
    )
    suppliers = (
        spark.read.csv(str(BRONZE_SUPPLIERS), header=True, sep=";")
        .select(
            F.col("supplier_id").cast("int").alias("supplier_id"),
            F.col("company_name").cast("string").alias("fornecedor_nome"),
        )
    )
    return products, categories, suppliers


def montar_produtos(products, categories, suppliers):
    """Monta o catálogo final a partir de três cadastros.

    Liga cada produto à sua categoria e ao seu fornecedor por meio dos IDs.
    Os joins são à esquerda para preservar o produto mesmo quando faltar uma
    descrição auxiliar. Ao final, seleciona e renomeia os campos para o
    vocabulário em português usado na Gold.
    """
    return (
        products
        .join(categories, on="category_id", how="left")
        .join(suppliers, on="supplier_id", how="left")
        .select(
            F.col("product_id").alias("produto_id"),
            F.col("product_name").alias("produto_nome"),
            F.col("category_id").alias("categoria_id"),
            F.col("categoria_nome"),
            F.col("supplier_id").alias("fornecedor_id"),
            F.col("fornecedor_nome"),
            F.col("quantity_per_unit").alias("quantidade_por_unidade"),
            F.col("unit_price").alias("preco_unitario"),
            F.col("units_in_stock").alias("unidades_em_estoque"),
            F.col("units_on_order").alias("unidades_em_pedido"),
            F.col("reorder_level").alias("nivel_reposicao"),
            F.col("discontinued").alias("descontinuado"),
        )
    )


def validar_resultado(gold, total_produtos_silver):
    """Valida se o catálogo enriquecido permaneceu completo e consistente.

    Confere IDs obrigatórios e únicos, nomes, preços não negativos e a
    quantidade de produtos antes e depois dos joins. Também identifica IDs
    de categoria ou fornecedor sem descrição correspondente. Interrompe o
    job em caso de problema e devolve o total de produtos válidos.
    """
    total = gold.count()
    problemas = {
        "produto_id nulo": gold.filter(F.col("produto_id").isNull()).count(),
        "produto_id duplicado": total - gold.select("produto_id").distinct().count(),
        "produto_nome nulo": gold.filter(F.col("produto_nome").isNull()).count(),
        "preco_unitario negativo": gold.filter(F.col("preco_unitario") < 0).count(),
        "produtos perdidos no join": total_produtos_silver - total,
        "categoria_nome nula (categoria_id nao nulo)": gold.filter(
            F.col("categoria_id").isNotNull() & F.col("categoria_nome").isNull()
        ).count(),
        "fornecedor_nome nulo (fornecedor_id nao nulo)": gold.filter(
            F.col("fornecedor_id").isNotNull() & F.col("fornecedor_nome").isNull()
        ).count(),
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, montagem, validação e gravação do catálogo Gold."""
    # 1. Abre a sessão de processamento.
    log.info("inicio")
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê produtos, categorias e fornecedores e registra seus totais.
    products, categories, suppliers = carregar_dados(spark)
    total_produtos_silver = products.count()
    log.info(
        "lido: %d produtos, %d categorias, %d fornecedores",
        total_produtos_silver, categories.count(), suppliers.count(),
    )

    # 3. Junta as fontes, renomeia os campos e valida o catálogo final.
    gold = montar_produtos(products, categories, suppliers)
    total = validar_resultado(gold, total_produtos_silver)

    # 4. Substitui o Parquet Gold pelo catálogo validado.
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    gold.write.mode("overwrite").parquet(str(GOLD))
    log.info("gold gravado: %d produtos em %s", total, GOLD)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
