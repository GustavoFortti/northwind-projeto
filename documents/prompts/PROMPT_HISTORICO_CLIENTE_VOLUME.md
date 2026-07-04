# Prompt - Histórico mensal de volume por cliente

Implemente somente a camada Silver → Gold do histórico mensal de clientes. Não criar tela, cálculo de churn, score, classificação de risco ou qualquer funcionalidade adicional.

## 1. Renomear a pasta do job

Renomear:

```text
pipeline/jobs/silver_to_gold_historico_cliente_produtos
```

para:

```text
pipeline/jobs/silver_to_gold_historico_cliente
```

Atualizar referências internas, caminhos de execução, docstrings e o nome do orquestrador:

```python
JOB = "silver_to_gold_historico_cliente"
```

Não renomear a tabela existente `historico_cliente_produtos`.

Logs históricos antigos não precisam ser alterados.

## 2. Simplificar `historico_cliente_produtos.py`

Manter o arquivo:

```text
pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_produtos.py
```

Remover da tabela final:

```text
quantidade_pedidos
primeira_compra_mes
ultima_compra_mes
```

Remover também:

- cálculos dessas colunas;
- validações relacionadas;
- referências em comentários e docstrings;
- logs que dependam delas.

O schema final deve ser:

```text
ano_mes
cliente_id
nome_empresa
produto_id
produto_nome
quantidade_consumida
receita_total
```

A granularidade continua:

```text
uma linha por ano_mes + cliente + produto
```

Manter:

```text
quantidade_consumida = SUM(quantity)
receita_total = SUM(receita_item)
```

Preservar as validações de:

- chave única `(ano_mes, cliente_id, produto_id)`;
- campos obrigatórios;
- quantidade positiva;
- receita não negativa;
- reconciliação da quantidade e receita com a Silver.

## 3. Criar `historico_cliente_volume.py`

Criar:

```text
pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_volume.py
```

Gerar:

```text
data/gold/historico_cliente_volume.parquet
```

Nome do job:

```python
JOB = "gold_historico_cliente_volume"
```

## Objetivo da nova tabela

Mostrar o volume mensal de compra de cada cliente, sem separar por produto.

Granularidade:

```text
uma linha por ano_mes + cliente
```

Schema:

```text
ano_mes
cliente_id
nome_empresa
receita_total
quantidade_pedidos
quantidade_produtos_distintos
quantidade_itens
```

Definições:

```text
receita_total =
SUM(order_details.receita_item)
```

```text
quantidade_pedidos =
COUNT(DISTINCT order_id)
```

```text
quantidade_produtos_distintos =
COUNT(DISTINCT product_id)
```

```text
quantidade_itens =
SUM(order_details.quantity)
```

Exemplo:

```text
O cliente comprou no mês:

10 unidades de vinho
30 unidades de queijo

quantidade_pedidos = quantidade de pedidos distintos realizados no mês
quantidade_produtos_distintos = 2
quantidade_itens = 40
receita_total = soma da receita dos itens
```

## Entradas Silver

Usar diretamente:

```text
data/silver/orders.parquet
data/silver/order_details.parquet
data/silver/customers.parquet
```

O processamento deve:

1. Juntar os itens aos pedidos por `order_id`.
2. Obter cliente, data e `ano_mes` do pedido.
3. Juntar o nome da empresa por `customer_id`.
4. Agrupar por `ano_mes`, `cliente_id` e `nome_empresa`.
5. Calcular as quatro métricas mensais.
6. Ordenar por `ano_mes` e `cliente_id`.

Não usar tabelas Gold como entrada.

## Validações do volume

Validar:

- chave `(ano_mes, cliente_id)` sem duplicidade;
- `ano_mes`, `cliente_id` e `nome_empresa` não nulos;
- `quantidade_pedidos > 0`;
- `quantidade_produtos_distintos > 0`;
- `quantidade_itens > 0`;
- `receita_total >= 0`;
- soma de `quantidade_itens` igual à soma de `quantity` na Silver;
- soma de `receita_total` igual à soma de `receita_item` na Silver;
- soma de `quantidade_pedidos` igual ao total de pedidos distintos da Silver.

## Estrutura e documentação

Organizar o novo arquivo em funções claras:

```text
setup_logger
carregar_dados
montar_volume
validar_resultado
main
```

No início do arquivo, documentar:

```text
Objetivo
Entrada de dados
Saída de dados
```

Cada função deve explicar o que faz. Funções complexas devem explicar joins, granularidade e cálculos.

A `main()` deve possuir etapas numeradas para:

1. iniciar a sessão;
2. carregar os dados;
3. calcular os totais de referência;
4. montar a tabela;
5. validar;
6. gravar o Parquet;
7. registrar os números finais.

## 4. Atualizar o orquestrador

Atualizar:

```text
pipeline/jobs/silver_to_gold_historico_cliente/job.py
```

Para executar, nesta ordem:

```python
SCRIPTS = [
    "historico_cliente_produtos.py",
    "historico_cliente_volume.py",
]
```

E exportar:

```python
TABLES = [
    "historico_cliente_produtos",
    "historico_cliente_volume",
]
```

O job deve gerar e exportar as duas tabelas para `viewer/data.sqlite`, seguindo o padrão atual da pipeline.

## Fora do escopo

Não implementar:

- churn;
- risco de churn;
- comparação entre períodos;
- médias móveis;
- tendência;
- previsão;
- score;
- alertas;
- alterações no frontend.

## Verificação

Depois de implementar:

1. Executar o orquestrador renomeado.
2. Confirmar os dois Parquets.
3. Confirmar os schemas.
4. Confirmar ausência das três colunas removidas.
5. Conferir as reconciliações de pedidos, quantidade e receita.
6. Confirmar as duas tabelas no SQLite.
7. Validar a sintaxe de todos os arquivos alterados.
8. Informar arquivos renomeados, criados e modificados.
