"""Bronze -> Silver: clientes.

Objetivo:
    Limpar o cadastro bruto de clientes, ajustar os tipos, trocar campos
    vazios por nulo e verificar IDs, nomes e duplicidades.

Entrada de dados:
    Registros brutos com identificação, empresa, contato, endereço e telefone.

Saída de dados:
    Cadastro padronizado e validado, com uma linha por cliente.
"""

import logging
from datetime import date
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "bronze_to_silver_customers"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
BRONZE = DATA / "bronze" / "customers.csv"
SILVER = DATA / "silver" / "customers" / "customers.parquet"

STRING_COLS = [
    "customer_id", "company_name", "contact_name", "contact_title",
    "address", "city", "region", "postal_code", "country", "phone", "fax",
]


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
    """Converte os campos do cadastro para texto e normaliza vazios como nulo."""
    df = bronze
    for c in STRING_COLS:
        df = df.withColumn(
            c,
            F.when(F.col(c).cast("string") == "", F.lit(None))
             .otherwise(F.col(c).cast("string")),
        )
    return df


def validate(df):
    """Verifica campos obrigatórios e garante que cada cliente seja único."""
    total = df.count()
    problemas = {
        "customer_id nulo": df.filter(F.col("customer_id").isNull()).count(),
        "customer_id duplicado": total - df.select("customer_id").distinct().count(),
        "company_name nulo": df.filter(F.col("company_name").isNull()).count(),
    }
    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %d ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v > 0}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, limpeza, validação e gravação dos clientes."""
    # 1. Abre a sessão usada para ler e transformar os dados.
    log.info("inicio | bronze=%s", BRONZE.name)
    spark = SparkSession.builder.getOrCreate()

    # 2. Lê o cadastro bruto de clientes.
    bronze = spark.read.csv(str(BRONZE), header=True, sep=";")
    log.info("bronze lido: %d clientes", bronze.count())

    # 3. Limpa os campos e valida o resultado antes de gravar.
    silver = transform(bronze)
    total = validate(silver)

    # 4. Substitui a tabela Silver pelo cadastro validado.
    SILVER.parent.mkdir(parents=True, exist_ok=True)
    silver.write.mode("overwrite").parquet(str(SILVER))
    log.info("silver gravado: %d clientes em %s", total, SILVER)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
