# Prompt - Reestruturar armazenamento dos Parquets

Reestruture somente os caminhos de armazenamento e consumo dos arquivos Parquet da pipeline.

Não criar histórico, arquivos com data, novos indicadores, novas tabelas ou alterações no frontend. Não alterar regras de negócio, schemas, cálculos ou nomes das tabelas.

## Nova estrutura obrigatória

Hoje os arquivos ficam diretamente na camada:

```text
data/silver/orders.parquet
data/gold/produtos.parquet
```

Eles devem passar a ficar dentro de uma pasta com o nome da tabela:

```text
data/silver/orders/orders.parquet
data/gold/produtos/produtos.parquet
```

A convenção obrigatória para todas as tabelas Parquet será:

```text
data/<camada>/<nome_tabela>/<nome_tabela>.parquet
```

Exemplos:

```text
data/silver/customers/customers.parquet
data/silver/orders/orders.parquet
data/silver/order_details/order_details.parquet
data/silver/products/products.parquet

data/gold/clientes/clientes.parquet
data/gold/produtos/produtos.parquet
data/gold/ticket_medio/ticket_medio.parquet
data/gold/produtos_associados/produtos_associados.parquet
data/gold/historico_cliente_produtos/historico_cliente_produtos.parquet
data/gold/historico_cliente_volume/historico_cliente_volume.parquet
```

Antes de alterar, descubra todas as tabelas existentes no repositório. Não limite a mudança apenas aos exemplos acima.

## Arquivos que devem ser revisados

Pesquisar o projeto inteiro por:

```text
.parquet
data/silver
data/gold
SILVER_
GOLD
read.parquet
write.mode
```

Atualizar:

- todos os jobs Bronze → Silver que gravam Parquet;
- todos os jobs Silver → Gold que leem a Silver;
- todos os jobs Silver → Gold que gravam a Gold;
- validações que leem outras tabelas Parquet;
- scripts orquestradores;
- exportador Gold → SQLite;
- comentários, docstrings e mensagens de erro com caminhos antigos;
- qualquer script auxiliar que consuma diretamente um Parquet.

Não alterar os arquivos CSV da Bronze. A nova estrutura vale para os Parquets das camadas Silver e Gold.

## Padrão dos caminhos

Exemplo para uma tabela Silver:

```python
SILVER_ORDERS = (
    DATA / "silver" / "orders" / "orders.parquet"
)
```

Exemplo para uma saída Gold:

```python
GOLD = (
    DATA / "gold" / "produtos_associados" / "produtos_associados.parquet"
)
```

Manter os nomes atuais das constantes sempre que possível.

Antes de gravar, continuar criando a pasta de destino:

```python
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
```

Não implementar fallback para os caminhos antigos. Todos os produtores e consumidores devem usar exclusivamente a nova estrutura.

## Exportador Gold → SQLite

Atualizar:

```text
pipeline/jobs/gold_to_db_export_data/job.py
```

Atualmente o exportador localiza uma tabela como:

```text
data/gold/<tabela>.parquet
```

Passar a localizar como:

```text
data/gold/<tabela>/<tabela>.parquet
```

Exemplo:

```python
parquet = GOLD / args.table / f"{args.table}.parquet"
```

Atualizar também a listagem de tabelas disponíveis quando uma tabela não for encontrada.

Uma tabela só deve ser considerada disponível quando existir:

```text
data/gold/<nome>/<nome>.parquet
```

Não alterar:

- nome da tabela exportada para SQLite;
- schema;
- valores;
- comportamento de substituição da tabela;
- argumentos do comando.

## Orquestradores

Os `job.py` devem continuar executando os mesmos scripts e exportando as mesmas tabelas.

Atualizar somente:

- textos que exibem caminhos;
- docstrings;
- eventuais verificações de existência de arquivos.

As listas `SCRIPTS` e `TABLES` não devem mudar, exceto se houver alguma referência de caminho embutida nelas.

## Migração dos dados atuais

Não manter duas cópias ativas da mesma tabela.

Procedimento:

1. Atualizar primeiro todos os produtores e consumidores.
2. Executar a pipeline na ordem correta para regenerar os Parquets.
3. Validar os novos arquivos.
4. Confirmar que a exportação para SQLite funciona.
5. Somente depois remover os Parquets antigos que ficaram diretamente em:
   - `data/silver/*.parquet`;
   - `data/gold/*.parquet`.

Não apagar arquivos antes de confirmar que a nova pipeline foi executada com sucesso.

## Fora do escopo

Não implementar:

- arquivos com data no nome;
- particionamento histórico;
- snapshots;
- retenção de versões;
- churn;
- novos jobs;
- novos campos;
- alterações de schema;
- mudanças no frontend;
- mudanças nos cálculos atuais.

Esta tarefa altera apenas a organização física dos Parquets e os caminhos usados para lê-los e gravá-los.

## Validação obrigatória

Depois da alteração:

1. Listar todos os produtores de Parquet.
2. Listar todos os consumidores de Parquet.
3. Confirmar que nenhum código ativo usa:
   ```text
   data/silver/<tabela>.parquet
   data/gold/<tabela>.parquet
   ```
4. Executar os jobs Bronze → Silver.
5. Executar os jobs Silver → Gold.
6. Executar as exportações para SQLite.
7. Confirmar que todos os novos arquivos seguem:
   ```text
   data/<camada>/<tabela>/<tabela>.parquet
   ```
8. Comparar schemas e quantidades de linhas antes e depois.
9. Confirmar que as tabelas do SQLite mantiveram nomes e schemas.
10. Validar a sintaxe de todos os arquivos Python alterados.
11. Confirmar que o viewer continua funcionando.
12. Remover os Parquets antigos somente após todas as validações.

Ao finalizar, informar:

- arquivos modificados;
- caminhos antigos e novos;
- tabelas regeneradas;
- contagens comparadas;
- validações executadas;
- arquivos antigos removidos;
- qualquer referência antiga que tenha permanecido e sua justificativa.
