"""Silver -> Gold: cadastro de clientes.

Objetivo:
    Montar a tabela de clientes usada pela aplicação, selecionando os dados
    cadastrais e renomeando as colunas para português.

Entrada de dados:
    Cadastro Silver com identificação, empresa, contato, endereço e telefone.

Saída de dados:
    Dimensão Gold em português, com uma linha cadastral por cliente.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_clientes"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_CUSTOMERS = DATA / "silver" / "customers" / "customers.parquet"
GOLD = DATA / "gold" / "clientes" / "clientes.parquet"


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
    """Lê da camada Silver o cadastro de clientes já limpo."""
    return spark.read.parquet(str(SILVER_CUSTOMERS))


def montar_clientes(customers):
    """Seleciona os campos cadastrais e renomeia as colunas para português."""
    return customers.select(
        F.col("customer_id").alias("cliente_id"),
        F.col("company_name").alias("nome_empresa"),
        F.col("contact_name").alias("nome_contato"),
        F.col("contact_title").alias("cargo_contato"),
        F.col("address").alias("endereco"),
        F.col("city").alias("cidade"),
        F.col("region").alias("regiao"),
        F.col("postal_code").alias("cep"),
        F.col("country").alias("pais"),
        F.col("phone").alias("telefone"),
        F.col("fax"),
    )


def validar_resultado(gold, total_clientes_silver):
    """Confere campos obrigatórios, unicidade e preservação dos clientes."""
    total = gold.count()
    problemas = {
        "cliente_id nulo": gold.filter(F.col("cliente_id").isNull()).count(),
        "cliente_id duplicado": total - gold.select("cliente_id").distinct().count(),
        "nome_empresa nulo": gold.filter(F.col("nome_empresa").isNull()).count(),
        "clientes perdidos na selecao": total_clientes_silver - total,
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, montagem, validação e gravação da tabela de clientes."""
    # 1. Abre a sessão de processamento.
    log.info("inicio")
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê os clientes da Silver e registra a quantidade recebida.
    customers = carregar_dados(spark)
    total_clientes_silver = customers.count()
    log.info("silver lido: %d clientes", total_clientes_silver)

    # 3. Monta a dimensão em português e valida se nenhum cliente foi perdido.
    gold = montar_clientes(customers)
    total = validar_resultado(gold, total_clientes_silver)

    # 4. Substitui o Parquet Gold pelo resultado validado.
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    gold.write.mode("overwrite").parquet(str(GOLD))
    log.info("gold gravado: %d clientes em %s", total, GOLD)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
