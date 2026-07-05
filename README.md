# Northwind - sistema de dados

Este repositório contém um pipeline que transforma os dados brutos da base Northwind em tabelas analíticas usadas por um viewer web. O processamento organiza os dados nas camadas Bronze, Silver e Gold e, ao final, exporta os resultados para SQLite.

## Arquitetura

```text
CSV (Bronze)
    ↓ limpeza, tipagem e validação
Parquet (Silver)
    ↓ agregações e regras de negócio
Parquet (Gold)
    ↓ exportação
SQLite (viewer/data.sqlite)
    ↓
Viewer web
```

As transformações são executadas em Python com o backend DuckDB do SQLFrame, usando uma API semelhante à do Spark. O Parquet é utilizado nas camadas processadas, e o SQLite funciona como a camada de consumo do viewer.

## Camadas de dados

### Bronze

Contém os arquivos CSV originais da Northwind em `data/bronze/`. Esses arquivos já são a entrada do pipeline; o repositório não possui um processo anterior de extração.

### Silver

Converte os principais dados para Parquet, corrige tipos e valida a integridade das informações.

| Tabela            | Conteúdo                                   |
| ----------------- | ------------------------------------------- |
| `customers`     | Cadastro tratado de clientes.               |
| `orders`        | Pedidos com datas, cliente e frete.         |
| `products`      | Cadastro tratado de produtos.               |
| `order_details` | Itens dos pedidos e receita após desconto. |

Os jobs validam identificadores obrigatórios, duplicidades, valores negativos e referências entre pedidos e seus itens.

### Gold

Produz as tabelas analíticas usadas pelo sistema.

| Tabela                         | Conteúdo                                                     |
| ------------------------------ | ------------------------------------------------------------- |
| `clientes`                   | Dimensão de clientes.                                        |
| `produtos`                   | Catálogo com categoria e fornecedor.                         |
| `descontos`                  | Maior desconto por produto e mês.                            |
| `produtos_associados`        | Produtos encontrados juntos em pedidos.                       |
| `ticket_medio`               | Resumo mensal das vendas.                                     |
| `historico_cliente_produtos` | Consumo mensal por cliente e produto.                         |
| `historico_cliente_volume`   | Frequência, pedidos e receita mensal por cliente.            |
| `historico_cliente_metricas` | Métricas mensais de clientes em três faixas de três meses. |

As tabelas são gravadas em `data/gold/`. O exportador copia os dados para `viewer/data.sqlite`; no caso das tabelas históricas, ele reúne todos os arquivos mensais disponíveis.

## Estrutura do repositório

```text
.
├── data/
│   ├── bronze/       # CSVs de origem
│   ├── silver/       # Parquets tratados
│   └── gold/         # Parquets analíticos
├── pipeline/
│   ├── jobs/         # transformações e exportação
│   └── logs/         # logs locais
├── viewer/
│   ├── data.sqlite   # banco gerado pelo pipeline
│   └── docs/         # documentação funcional
└── documents/
    └── prompts/      # prompts usados no desenvolvimento
```

## Execução

Execute os comandos a partir da raiz do repositório usando o ambiente virtual `.venv`.

### Gerar a Silver

```bash
.venv/bin/python pipeline/jobs/bronze_to_silver_customers/job.py
.venv/bin/python pipeline/jobs/bronze_to_silver_orders/job.py
.venv/bin/python pipeline/jobs/bronze_to_silver_products/job.py
.venv/bin/python pipeline/jobs/bronze_to_silver_order_details/job.py
```

O job de `order_details` deve ser executado depois de `orders`, pois valida as referências dos pedidos.

### Gerar a Gold e atualizar o SQLite

```bash
.venv/bin/python pipeline/jobs/silver_to_gold_clientes/job.py
.venv/bin/python pipeline/jobs/silver_to_gold_produtos/job.py
.venv/bin/python pipeline/jobs/silver_to_gold_produtos_associados/job.py
.venv/bin/python pipeline/jobs/silver_to_gold_ticket_medio/job.py
.venv/bin/python pipeline/jobs/silver_to_gold_historico_cliente/job.py
```

Cada orquestrador gera suas tabelas Gold e já exporta o resultado para o banco do viewer.

### Gerar métricas mensais de clientes

O retrato de métricas é processado separadamente. A data informada gera os dados do mês fechado imediatamente anterior.

```bash
.venv/bin/python pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_metricas.py --data-processamento 1998-05-01
.venv/bin/python pipeline/jobs/gold_to_db_export_data/job.py historico_cliente_metricas
```

Nesse exemplo, é criado o retrato de `1998-04`, e todo o histórico disponível é exportado para o SQLite.

Para exportar novamente uma tabela Gold específica:

```bash
.venv/bin/python pipeline/jobs/gold_to_db_export_data/job.py produtos
```

## Logs e validações

Os jobs mostram o andamento no terminal e gravam logs em `pipeline/logs/`. Quando uma validação falha, o processamento é interrompido para evitar a publicação de dados inconsistentes.

## Documentação do sistema

- [Funcionamento das telas](viewer/docs/sistema.md)
- [Diagrama do sistema](viewer/docs/sistema.svg)
