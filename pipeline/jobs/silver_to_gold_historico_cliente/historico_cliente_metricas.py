"""Silver -> Gold: retrato mensal de clientes em três faixas de 3 meses.

Objetivo:
    Para uma data de processamento (padrão: hoje), montar um retrato do
    comportamento de compra de cada cliente nos nove meses fechados
    imediatamente anteriores, divididos em três faixas INDEPENDENTES de
    exatamente 3 meses cada, sem sobreposição entre elas:

        3m -> os 3 meses mais recentes (meses 1 a 3 antes da execução);
        6m -> os 3 meses seguintes, mais antigos (meses 4 a 6);
        9m -> os 3 meses mais antigos das três faixas (meses 7 a 9).

    O sufixo (3m/6m/9m) indica a que distância aquele bloco de 3 meses está
    da execução - não é mais um acúmulo de 3, 6 ou 9 meses. Cada faixa
    sempre tem exatamente 3 meses, e cada média é sempre dividida por 3.
    É uma base factual - sem churn, sem score, sem classificação de risco
    - pensada para alimentar análises futuras sobre esses temas.

Entrada de dados:
    Pedidos, itens e clientes tratados na camada Silver
    (data/silver/orders, data/silver/order_details, data/silver/customers).
    Não lê nenhuma tabela Gold.

Saída de dados:
    Um Parquet por mês processado, em
    data/gold/historico_cliente_metricas/historico_cliente_metricas-<ano_mes>.parquet,
    com uma linha por cliente elegível (todo cliente com pelo menos um
    pedido até o fim do mês processado) e as métricas médias/frequência
    das três faixas.

Rodar:
    .venv/bin/python pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_metricas.py
    .venv/bin/python pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_metricas.py --data-processamento 1997-05-01
"""

import argparse
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlframe.duckdb import DuckDBSession as SparkSession
from sqlframe.duckdb import functions as F

JOB = "gold_historico_cliente_metricas"
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
LOGS = ROOT / "pipeline" / "logs"
SILVER_ORDERS = DATA / "silver" / "orders" / "orders.parquet"
SILVER_DETAILS = DATA / "silver" / "order_details" / "order_details.parquet"
SILVER_CUSTOMERS = DATA / "silver" / "customers" / "customers.parquet"
GOLD_DIR = DATA / "gold" / "historico_cliente_metricas"

JANELAS = (3, 6, 9)
MESES_POR_FAIXA = 3  # toda faixa tem exatamente 3 meses; nunca 6 ou 9


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


# ── datas: só aritmética de mês de calendário, nunca aproximação por dias ──


def primeiro_dia_mes(d: date) -> date:
    """Primeiro dia do mês de `d`."""
    return d.replace(day=1)


def somar_meses(d: date, n: int) -> date:
    """Some `n` meses de calendário ao primeiro dia do mês de `d` (n pode ser negativo)."""
    total = d.year * 12 + (d.month - 1) + n
    ano, mes0 = divmod(total, 12)
    return date(ano, mes0 + 1, 1)


def formatar_ano_mes(d: date) -> str:
    """Formata o mês de `d` como 'YYYY-MM'."""
    return f"{d.year:04d}-{d.month:02d}"


def meses_no_intervalo(inicio: date, fim_inclusive: date) -> list:
    """Lista 'YYYY-MM' de cada mês entre `inicio` e `fim_inclusive`, ambos os
    primeiros dias de um mês. Usada para filtrar a base mensal pela janela."""
    labels = []
    atual = primeiro_dia_mes(inicio)
    limite = primeiro_dia_mes(fim_inclusive)
    while atual <= limite:
        labels.append(formatar_ano_mes(atual))
        atual = somar_meses(atual, 1)
    return labels


# ── argumentos e períodos ──────────────────────────────────────


def ler_argumentos():
    """Lê --data-processamento (YYYY-MM-DD); usa hoje quando omitido."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-processamento",
        default=None,
        help="data de processamento no formato YYYY-MM-DD (padrão: hoje)",
    )
    args = parser.parse_args()
    if args.data_processamento is None:
        return date.today()
    try:
        return datetime.strptime(args.data_processamento, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            f"--data-processamento invalido: '{args.data_processamento}' "
            "(formato esperado: YYYY-MM-DD)"
        ) from exc


def calcular_periodos(data_processamento: date) -> dict:
    """Calcula o mês fechado processado e os limites das três faixas de 3 meses.

    O mês vigente na data de processamento nunca é usado: fim_mes_processado
    é sempre o último dia do mês anterior, e ano_mes é o mês desse fim.

    As três faixas (3m/6m/9m) particionam os nove meses fechados anteriores
    em blocos de exatamente 3 meses, sem sobreposição - 3m é o bloco mais
    recente (termina no mês processado), 6m é o bloco anterior a esse, e 9m
    é o bloco mais antigo, anterior ao 6m. Para cada faixa N:

        inicio_Nm = inicio_mes_processado - (N - 1) meses
        fim_Nm    = inicio_mes_processado - (N - 3) meses

    Só aritmética de mês de calendário, nunca aproximação por dias.
    """
    inicio_mes_atual = primeiro_dia_mes(data_processamento)
    fim_mes_processado = inicio_mes_atual - timedelta(days=1)
    inicio_mes_processado = primeiro_dia_mes(fim_mes_processado)
    ano_mes = formatar_ano_mes(inicio_mes_processado)

    periodos = {
        "data_processamento": data_processamento,
        "fim_mes_processado": fim_mes_processado,
        "inicio_mes_processado": inicio_mes_processado,
        "ano_mes": ano_mes,
    }
    for n in JANELAS:
        periodos[f"inicio_{n}m"] = somar_meses(inicio_mes_processado, -(n - 1))
        periodos[f"fim_{n}m"] = somar_meses(inicio_mes_processado, -(n - 3))
    return periodos


# ── dados ────────────────────────────────────────────────────


def carregar_dados(spark):
    """Lê pedidos, itens e clientes tratados na camada Silver."""
    orders = spark.read.parquet(str(SILVER_ORDERS))
    details = spark.read.parquet(str(SILVER_DETAILS))
    customers = spark.read.parquet(str(SILVER_CUSTOMERS))
    return orders, details, customers


def validar_cobertura(menor_data: date, maior_data: date, periodos: dict) -> date:
    """Confere se a Silver cobre os nove meses exigidos pelo mês solicitado.

    As três faixas juntas cobrem sempre nove meses fechados, e a faixa 9m é
    a mais antiga delas - por isso o início da faixa 9m (`inicio_9m`) é o
    primeiro mês que precisa existir na Silver. Duas checagens: (1) esse
    início não pode ser anterior ao primeiro mês completo disponível na
    Silver (o mês da menor order_date só é completo se ela cair no dia 1;
    senão o primeiro mês completo é o seguinte); (2) a Silver precisa ter
    dados até o fim do mês processado, senão o retrato ficaria parcial.
    Interrompe com uma mensagem detalhada se qualquer uma falhar. Devolve o
    primeiro mês completo encontrado (usado só para log).
    """
    if menor_data.day == 1:
        primeiro_mes_completo = primeiro_dia_mes(menor_data)
    else:
        primeiro_mes_completo = somar_meses(primeiro_dia_mes(menor_data), 1)

    inicio_9m = periodos["inicio_9m"]
    fim_mes_processado = periodos["fim_mes_processado"]
    primeira_data_permitida = somar_meses(primeiro_mes_completo, 9)

    problemas = []
    if inicio_9m < primeiro_mes_completo:
        problemas.append(
            "cobertura historica insuficiente para a faixa 9m (a mais antiga das tres faixas) "
            f"(menor order_date={menor_data.isoformat()}, "
            f"primeiro mes completo={formatar_ano_mes(primeiro_mes_completo)}, "
            f"mes solicitado={periodos['ano_mes']}, "
            f"inicio necessario da faixa 9m={formatar_ano_mes(inicio_9m)}, "
            f"primeira data de processamento permitida={primeira_data_permitida.isoformat()})"
        )
    if maior_data < fim_mes_processado:
        problemas.append(
            "silver nao tem dados ate o fim do mes processado "
            f"(maior order_date={maior_data.isoformat()}, "
            f"fim do mes processado esperado={fim_mes_processado.isoformat()}, "
            f"mes solicitado={periodos['ano_mes']})"
        )
    if problemas:
        raise ValueError("; ".join(problemas))
    return primeiro_mes_completo


def montar_base_mensal(orders, details, customers, fim_mes_processado: date):
    """Monta a agregação mensal intermediária: uma linha por ano_mes + cliente.

    Primeiro restringe os pedidos a order_date <= fim_mes_processado (nunca
    olhando o mês vigente nem qualquer mês futuro), liga os itens a esses
    pedidos e ao nome do cliente, e agrupa por mês e cliente somando
    receita, receita bruta (sem desconto), pedidos distintos, produtos
    distintos e itens. Meses sem nenhum pedido do cliente simplesmente não
    geram linha aqui - são tratados como zero mais adiante, na janela.
    """
    limite = F.lit(fim_mes_processado.isoformat()).cast("date")
    pedidos_no_periodo = orders.filter(F.col("order_date") <= limite)

    itens = (
        details.select("order_id", "product_id", "quantity", "unit_price", "receita_item")
        .join(
            pedidos_no_periodo.select(
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

    base = (
        itens.groupBy("ano_mes", "customer_id", "nome_empresa")
        .agg(
            F.sum("receita_item").alias("receita"),
            F.sum(F.col("unit_price") * F.col("quantity")).alias("receita_sem_desconto"),
            F.countDistinct("order_id").alias("quantidade_pedidos"),
            F.countDistinct("product_id").alias("quantidade_produtos_distintos"),
            F.sum("quantity").alias("quantidade_itens"),
        )
        .select(
            "ano_mes",
            F.col("customer_id").alias("cliente_id"),
            "nome_empresa",
            "receita",
            "receita_sem_desconto",
            "quantidade_pedidos",
            "quantidade_produtos_distintos",
            "quantidade_itens",
        )
    )
    return base


def montar_populacao_clientes(orders, customers, fim_mes_processado: date):
    """Monta a população de clientes elegíveis para o mês processado.

    Um cliente é elegível se tem ao menos um pedido com order_date <=
    fim_mes_processado - mesmo que nenhum desses pedidos caia dentro da
    janela de 9 meses (nesse caso suas métricas de janela ficam zeradas,
    mas ele continua aparecendo no retrato). Clientes cuja primeira compra
    é posterior ao mês processado não entram, evitando usar informação
    futura.
    """
    limite = F.lit(fim_mes_processado.isoformat()).cast("date")
    clientes_ativos = orders.filter(F.col("order_date") <= limite).select("customer_id").distinct()
    populacao = (
        clientes_ativos.join(
            customers.select("customer_id", F.col("company_name").alias("nome_empresa")),
            on="customer_id",
            how="inner",
        )
        .select(F.col("customer_id").alias("cliente_id"), "nome_empresa")
    )
    return populacao


def calcular_janela(base_mensal, populacao, meses_labels: list, sufixo: str):
    """Calcula as métricas de uma faixa (bloco de 3 meses, sem sobreposição
    com as outras faixas) para todo cliente da população.

    Filtra a base mensal aos 3 meses da faixa (`meses_labels`), soma as
    métricas por cliente e junta de volta com a população inteira - clientes
    sem nenhuma linha na faixa recebem soma zero. As médias sempre dividem
    por `MESES_POR_FAIXA` (3), nunca pela quantidade de meses ativos, para
    que meses sem compra contem como zero. O desconto médio é o ponderado
    pelo valor bruto da faixa inteira, não a média simples dos percentuais
    mensais. Devolve uma linha por cliente com as sete colunas da faixa
    (frequência + 6 médias), já arredondadas.
    """
    dados_janela = base_mensal.filter(F.col("ano_mes").isin(meses_labels))

    agregado = dados_janela.groupBy("cliente_id").agg(
        F.count(F.lit(1)).alias("meses_com_compra"),
        F.sum("receita").alias("receita_soma"),
        F.sum("receita_sem_desconto").alias("receita_sem_desconto_soma"),
        F.sum("quantidade_pedidos").alias("quantidade_pedidos_soma"),
        F.sum("quantidade_produtos_distintos").alias("quantidade_produtos_distintos_soma"),
        F.sum("quantidade_itens").alias("quantidade_itens_soma"),
    )

    janela = (
        populacao.select("cliente_id")
        .join(agregado, on="cliente_id", how="left")
        .select(
            "cliente_id",
            F.coalesce(F.col("meses_com_compra"), F.lit(0)).alias("meses_com_compra"),
            F.coalesce(F.col("receita_soma"), F.lit(0.0)).alias("receita_soma"),
            F.coalesce(F.col("receita_sem_desconto_soma"), F.lit(0.0)).alias("receita_sem_desconto_soma"),
            F.coalesce(F.col("quantidade_pedidos_soma"), F.lit(0)).alias("quantidade_pedidos_soma"),
            F.coalesce(F.col("quantidade_produtos_distintos_soma"), F.lit(0)).alias("quantidade_produtos_distintos_soma"),
            F.coalesce(F.col("quantidade_itens_soma"), F.lit(0)).alias("quantidade_itens_soma"),
        )
        .withColumn(f"frequencia_compra_{sufixo}", F.round(F.col("meses_com_compra") / F.lit(MESES_POR_FAIXA), 4))
        .withColumn(f"receita_media_{sufixo}", F.round(F.col("receita_soma") / F.lit(MESES_POR_FAIXA), 2))
        .withColumn(
            f"receita_sem_desconto_media_{sufixo}",
            F.round(F.col("receita_sem_desconto_soma") / F.lit(MESES_POR_FAIXA), 2),
        )
        .withColumn(
            f"desconto_medio_{sufixo}",
            F.when(F.col("receita_sem_desconto_soma") == 0, F.lit(0.0))
            .otherwise(F.round(1 - (F.col("receita_soma") / F.col("receita_sem_desconto_soma")), 4)),
        )
        .withColumn(
            f"quantidade_pedidos_media_{sufixo}",
            F.round(F.col("quantidade_pedidos_soma") / F.lit(MESES_POR_FAIXA), 2),
        )
        .withColumn(
            f"quantidade_produtos_distintos_media_{sufixo}",
            F.round(F.col("quantidade_produtos_distintos_soma") / F.lit(MESES_POR_FAIXA), 2),
        )
        .withColumn(
            f"quantidade_itens_media_{sufixo}",
            F.round(F.col("quantidade_itens_soma") / F.lit(MESES_POR_FAIXA), 2),
        )
        .select(
            "cliente_id",
            f"frequencia_compra_{sufixo}",
            f"receita_media_{sufixo}",
            f"receita_sem_desconto_media_{sufixo}",
            f"desconto_medio_{sufixo}",
            f"quantidade_pedidos_media_{sufixo}",
            f"quantidade_produtos_distintos_media_{sufixo}",
            f"quantidade_itens_media_{sufixo}",
        )
    )
    return janela


def montar_historico(populacao, janela_3m, janela_6m, janela_9m, ano_mes: str):
    """Junta a população com as três faixas em uma única linha por cliente."""
    historico = (
        populacao.withColumn("ano_mes", F.lit(ano_mes))
        .join(janela_3m, on="cliente_id", how="left")
        .join(janela_6m, on="cliente_id", how="left")
        .join(janela_9m, on="cliente_id", how="left")
        .select(
            "ano_mes",
            "cliente_id",
            "nome_empresa",
            "frequencia_compra_3m",
            "receita_media_3m",
            "receita_sem_desconto_media_3m",
            "desconto_medio_3m",
            "quantidade_pedidos_media_3m",
            "quantidade_produtos_distintos_media_3m",
            "quantidade_itens_media_3m",
            "frequencia_compra_6m",
            "receita_media_6m",
            "receita_sem_desconto_media_6m",
            "desconto_medio_6m",
            "quantidade_pedidos_media_6m",
            "quantidade_produtos_distintos_media_6m",
            "quantidade_itens_media_6m",
            "frequencia_compra_9m",
            "receita_media_9m",
            "receita_sem_desconto_media_9m",
            "desconto_medio_9m",
            "quantidade_pedidos_media_9m",
            "quantidade_produtos_distintos_media_9m",
            "quantidade_itens_media_9m",
        )
    )
    return historico


def validar_resultado(historico, base_mensal, total_populacao: int, periodos: dict) -> int:
    """Confere a chave, os campos obrigatórios e as regras de negócio do retrato.

    Verifica unicidade de (ano_mes, cliente_id), que todas as linhas
    pertencem ao mês processado, campos obrigatórios não nulos, frequências
    e descontos em [0, 1], médias não negativas, ausência de valores
    inválidos (NaN), consistência entre "sem compra na faixa" e métricas
    zeradas, que a base mensal não contém nenhum mês posterior ao
    processado (prova de que nenhum pedido futuro foi usado) e que a
    contagem final bate com a população elegível. Interrompe o job se
    qualquer conferência falhar.
    """
    total = historico.count()
    ano_mes = periodos["ano_mes"]

    sufixos = [f"{n}m" for n in JANELAS]
    colunas_frequencia = [f"frequencia_compra_{s}" for s in sufixos]
    colunas_desconto = [f"desconto_medio_{s}" for s in sufixos]
    colunas_receita = [f"receita_media_{s}" for s in sufixos] + [
        f"receita_sem_desconto_media_{s}" for s in sufixos
    ]
    colunas_quantidade = (
        [f"quantidade_pedidos_media_{s}" for s in sufixos]
        + [f"quantidade_produtos_distintos_media_{s}" for s in sufixos]
        + [f"quantidade_itens_media_{s}" for s in sufixos]
    )
    colunas_numericas = colunas_frequencia + colunas_desconto + colunas_receita + colunas_quantidade

    problemas = {
        "chave (ano_mes, cliente_id) duplicada": total
        - historico.select("ano_mes", "cliente_id").distinct().count(),
        "linhas fora do mes processado": historico.filter(F.col("ano_mes") != F.lit(ano_mes)).count(),
        "cliente_id nulo": historico.filter(F.col("cliente_id").isNull()).count(),
        "nome_empresa nulo": historico.filter(F.col("nome_empresa").isNull()).count(),
        "base mensal com mes posterior ao processado": base_mensal.filter(
            F.col("ano_mes") > F.lit(ano_mes)
        ).count(),
        "quantidade de clientes != populacao elegivel": abs(total - total_populacao),
    }

    for col in colunas_frequencia + colunas_desconto:
        problemas[f"{col} fora de [0, 1]"] = historico.filter(
            (F.col(col) < 0) | (F.col(col) > 1)
        ).count()
    for col in colunas_receita + colunas_quantidade:
        problemas[f"{col} negativa"] = historico.filter(F.col(col) < 0).count()
    for col in colunas_numericas:
        problemas[f"{col} invalida (NaN)"] = historico.filter(F.isnan(F.col(col))).count()

    for s in sufixos:
        problemas[f"cliente sem compra na faixa {s} com metrica != 0"] = historico.filter(
            (F.col(f"frequencia_compra_{s}") == 0)
            & (
                (F.col(f"receita_media_{s}") != 0)
                | (F.col(f"receita_sem_desconto_media_{s}") != 0)
                | (F.col(f"quantidade_pedidos_media_{s}") != 0)
                | (F.col(f"quantidade_produtos_distintos_media_{s}") != 0)
                | (F.col(f"quantidade_itens_media_{s}") != 0)
            )
        ).count()

    for regra, qtd in problemas.items():
        log.info("validacao [%s]: %s ocorrencias", regra, qtd)
    erros = {k: v for k, v in problemas.items() if v}
    if erros:
        raise ValueError(f"validacao falhou: {erros}")
    return total


def main():
    """Executa a leitura, os cálculos das faixas, a validação e a gravação do mês processado."""
    log.info("inicio")

    # 1. Lê os argumentos e calcula o mês processado e os limites das três faixas.
    data_processamento = ler_argumentos()
    periodos = calcular_periodos(data_processamento)
    log.info("data de processamento: %s", periodos["data_processamento"].isoformat())
    log.info("mes processado (ano_mes): %s", periodos["ano_mes"])
    for n in JANELAS:
        inicio, fim = periodos[f"inicio_{n}m"], periodos[f"fim_{n}m"]
        log.info("faixa %dm (3 meses, sem sobreposicao): %s a %s", n, formatar_ano_mes(inicio), formatar_ano_mes(fim))

    # 2. Abre a sessão e lê as três fontes Silver.
    spark = SparkSession.builder.getOrCreate()
    orders, details, customers = carregar_dados(spark)

    # 3. Descobre a cobertura histórica disponível e valida o período solicitado.
    cobertura = orders.agg(
        F.min("order_date").alias("mn"), F.max("order_date").alias("mx")
    ).collect()[0]
    menor_data, maior_data = cobertura["mn"], cobertura["mx"]
    log.info("menor order_date na silver: %s", menor_data.isoformat())
    log.info("maior order_date na silver: %s", maior_data.isoformat())
    primeiro_mes_completo = validar_cobertura(menor_data, maior_data, periodos)
    log.info("primeiro mes completo disponivel: %s", formatar_ano_mes(primeiro_mes_completo))

    # 4. Monta a base mensal intermediária (uma linha por ano_mes + cliente).
    base_mensal = montar_base_mensal(orders, details, customers, periodos["fim_mes_processado"])

    # 5. Monta a população de clientes elegíveis para o mês processado.
    populacao = montar_populacao_clientes(orders, customers, periodos["fim_mes_processado"])
    total_populacao = populacao.count()
    log.info("clientes elegiveis: %d", total_populacao)

    # 6. Calcula as três faixas de 3 meses (sem sobreposição entre elas).
    janelas_calculadas = {}
    for n in JANELAS:
        labels = meses_no_intervalo(periodos[f"inicio_{n}m"], periodos[f"fim_{n}m"])
        janelas_calculadas[n] = calcular_janela(base_mensal, populacao, labels, f"{n}m")

    # 7. Monta o retrato final: uma linha por cliente elegível, com as três faixas.
    historico = montar_historico(
        populacao, janelas_calculadas[3], janelas_calculadas[6], janelas_calculadas[9], periodos["ano_mes"]
    )

    # 8. Valida a chave, os campos obrigatórios e as regras de negócio da saída.
    total = validar_resultado(historico, base_mensal, total_populacao, periodos)

    # 9. Registra os números de controle exigidos.
    com_compra_9m = historico.filter(F.col("frequencia_compra_9m") > 0).count()
    sem_compra_9m = total - com_compra_9m
    log.info("clientes com compra na faixa 9m (mais antiga): %d", com_compra_9m)
    log.info("clientes sem compra na faixa 9m (mais antiga): %d", sem_compra_9m)
    log.info("linhas gravadas: %d", total)

    # 10. Grava só o arquivo do mês processado, sem tocar nos demais meses.
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    destino = GOLD_DIR / f"historico_cliente_metricas-{periodos['ano_mes']}.parquet"
    historico.write.mode("overwrite").parquet(str(destino))
    log.info("arquivo gravado: %s", destino)
    log.info("fim | sucesso")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("job falhou")
        raise
