# Prompt - Histórico de clientes com janelas de 3, 6 e 9 meses

Crie um novo job Silver → Gold que gere um retrato mensal do comportamento de compra de cada cliente usando janelas móveis de 3, 6 e 9 meses.

O job deve ler diretamente da Silver. Não usar tabelas Gold como entrada.

Não implementar churn, classificação de risco, previsão, alertas ou frontend nesta tarefa. O resultado será apenas uma base histórica factual para análises futuras.

## Local do novo job

Criar dentro do agrupamento de histórico de clientes:

```text
pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_metricas.py
```

Nome do job:

```python
JOB = "gold_historico_cliente_metricas"
```

O script deve ser executável diretamente e aceitar uma data de processamento opcional:

```text
.venv/bin/python pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_metricas.py
```

ou:

```text
.venv/bin/python pipeline/jobs/silver_to_gold_historico_cliente/historico_cliente_metricas.py --data-processamento 1997-05-01
```

Quando o argumento não for informado, usar a data atual.

O parâmetro é necessário para testes e reprocessamentos históricos. Validar o formato `YYYY-MM-DD` e apresentar erro claro quando for inválido.

## Regra do mês processado

O job nunca pode usar dados do mês vigente na data de processamento.

O campo `ano_mes` deve representar sempre o mês fechado imediatamente anterior.

Exemplos:

```text
data de processamento: 2026-07-05
ano_mes processado: 2026-06
```

```text
data de processamento: 2026-07-25
ano_mes processado: 2026-06
```

As duas execuções devem produzir o mesmo mês histórico.

Calcular:

```text
inicio_mes_atual = primeiro dia do mês da data de processamento
fim_mes_processado = inicio_mes_atual - 1 dia
ano_mes = mês de fim_mes_processado
```

Todos os filtros devem usar no máximo `fim_mes_processado`. Nenhum pedido do mês vigente pode entrar nos cálculos.

## Janelas móveis

As janelas incluem o mês processado.

Para uma execução em julho/2026, processando junho/2026:

```text
janela de 3 meses: abril, maio e junho
janela de 6 meses: janeiro até junho
janela de 9 meses: outubro do ano anterior até junho
```

Calcular os inícios das janelas por mês de calendário, sem usar aproximações de 30, 90, 180 ou 270 dias.

```text
inicio_3m = primeiro dia do mês processado menos 2 meses
inicio_6m = primeiro dia do mês processado menos 5 meses
inicio_9m = primeiro dia do mês processado menos 8 meses
```

O fim de todas as janelas é o último dia do mês processado.

## Validação de cobertura histórica

O job só pode executar quando existirem nove meses completos de dados.

Descobrir a menor e a maior `order_date` disponíveis na Silver.

### Primeiro mês completo

Se a menor data for o primeiro dia do mês, esse mês pode ser considerado completo.

Se a menor data começar depois do primeiro dia, considerar como primeiro mês completo apenas o mês seguinte.

Exemplo da base atual:

```text
menor order_date = 1996-07-04
```

Julho/1996 é parcial. Portanto:

```text
primeiro mês completo = 1996-08
```

A primeira execução válida será:

```text
data de processamento = 1997-05-01
mês processado = 1997-04
janela de 9 meses = 1996-08 até 1997-04
```

Uma execução em `1997-04-01` deve falhar, porque processaria março e precisaria incluir julho/1996, que é parcial.

Validar:

```text
inicio_9m >= primeiro_mes_completo
```

Se não houver cobertura, interromper com mensagem contendo:

- menor data encontrada;
- primeiro mês considerado completo;
- mês solicitado;
- início necessário para a janela de nove meses;
- primeira data de processamento permitida.

### Cobertura até o final do mês processado

Também validar:

```text
maior order_date >= fim_mes_processado
```

Se a Silver não tiver dados até o final do mês que deveria ser processado, interromper para evitar gerar um retrato parcial.

Não continuar silenciosamente com meses incompletos.

## Fontes Silver

Usar diretamente as tabelas Silver na estrutura atual de armazenamento:

```text
data/silver/orders/orders.parquet
data/silver/order_details/order_details.parquet
data/silver/customers/customers.parquet
```

Antes de implementar, confirmar os caminhos atuais no repositório e seguir a convenção vigente caso a migração de armazenamento ainda não tenha sido aplicada.

Usar:

- `orders`: pedido, cliente e data;
- `order_details`: produto, quantidade, preço, desconto e receita líquida;
- `customers`: nome da empresa.

Não ler:

- `historico_cliente_volume`;
- `historico_cliente_produtos`;
- qualquer outra tabela Gold.

## População de clientes

Incluir todo cliente que tenha realizado pelo menos um pedido até o final do mês processado.

Um cliente deve continuar aparecendo mesmo que não tenha comprado nada dentro da janela de nove meses. Nesse caso, suas métricas das janelas devem ser zero.

Não incluir clientes cuja primeira compra ocorreu depois do mês processado.

Essa regra evita olhar informações futuras e preserva clientes inativos no retrato histórico.

## Granularidade da saída

Uma linha por:

```text
ano_mes + cliente_id
```

O mesmo cliente deve ter no máximo uma linha em cada arquivo mensal.

## Definição de frequência de compra

Para evitar duplicidade com `quantidade_pedidos_media`, definir frequência como a proporção de meses da janela em que o cliente realizou pelo menos um pedido.

Exemplo:

```text
janela de 3 meses
cliente comprou em abril e junho, mas não em maio

frequencia_compra_3m = 2 ÷ 3 = 0,6667
```

Armazenar entre `0` e `1`:

```text
0 = não comprou em nenhum mês
1 = comprou em todos os meses
```

Fórmulas:

```text
frequencia_compra_3m = meses com compra na janela ÷ 3
frequencia_compra_6m = meses com compra na janela ÷ 6
frequencia_compra_9m = meses com compra na janela ÷ 9
```

## Médias mensais

Todas as médias devem considerar meses sem compra como zero.

Não dividir apenas pelos meses ativos.

Exemplo:

```text
receita nos últimos 3 meses:
abril = 300
maio = 0
junho = 600

receita_media_3m = (300 + 0 + 600) ÷ 3 = 300
```

Aplicar a mesma regra a:

- receita;
- receita sem desconto;
- quantidade de pedidos;
- quantidade de produtos distintos;
- quantidade de itens.

## Desconto médio das janelas

Não calcular uma média simples dos percentuais mensais.

Usar o desconto efetivo ponderado pelo valor bruto de todos os itens da janela:

```text
desconto_medio_janela =
1 - (soma da receita líquida ÷ soma da receita sem desconto)
```

Se a receita sem desconto da janela for zero, retornar desconto zero.

Armazenar o resultado entre `0` e `1`.

## Agregação mensal intermediária

Antes de calcular as janelas, montar uma base intermediária com uma linha por:

```text
ano_mes + cliente
```

Calcular nela:

```text
receita = SUM(receita_item)
receita_sem_desconto = SUM(unit_price × quantity)
quantidade_pedidos = COUNT(DISTINCT order_id)
quantidade_produtos_distintos = COUNT(DISTINCT product_id)
quantidade_itens = SUM(quantity)
```

As médias de 3, 6 e 9 meses devem ser calculadas a partir desses valores mensais.

Para meses ausentes, considerar todas as métricas como zero.

## Schema final

Produzir as colunas nesta ordem:

```text
ano_mes
cliente_id
nome_empresa

frequencia_compra_3m
receita_media_3m
receita_sem_desconto_media_3m
desconto_medio_3m
quantidade_pedidos_media_3m
quantidade_produtos_distintos_media_3m
quantidade_itens_media_3m

frequencia_compra_6m
receita_media_6m
receita_sem_desconto_media_6m
desconto_medio_6m
quantidade_pedidos_media_6m
quantidade_produtos_distintos_media_6m
quantidade_itens_media_6m

frequencia_compra_9m
receita_media_9m
receita_sem_desconto_media_9m
desconto_medio_9m
quantidade_pedidos_media_9m
quantidade_produtos_distintos_media_9m
quantidade_itens_media_9m
```

## Tipos e arredondamento

- `ano_mes`: string `YYYY-MM`;
- IDs e nomes: manter os tipos da Silver;
- frequências: decimal entre `0` e `1`, com quatro casas;
- descontos: decimal entre `0` e `1`, com quatro casas;
- receitas médias: decimal com duas casas;
- demais médias: decimal com duas casas.

Efetuar os cálculos com a maior precisão disponível e arredondar apenas na seleção final.

## Nome e local do arquivo histórico

Gravar um arquivo separado para cada mês processado:

```text
data/gold/historico_cliente_metricas/
    historico_cliente_metricas-<ano_mes>.parquet
```

Exemplo:

```text
data/gold/historico_cliente_metricas/
    historico_cliente_metricas-1997-04.parquet
```

Ao reexecutar o mesmo mês, substituir somente o arquivo daquele mês.

Não apagar nem sobrescrever arquivos de outros meses.

Não gerar também uma cópia sem data nesta tarefa.

## Estrutura das funções

Organizar o script em funções claras, por exemplo:

```text
setup_logger
ler_argumentos
calcular_periodos
carregar_dados
validar_cobertura
montar_base_mensal
montar_populacao_clientes
calcular_janela
montar_historico
validar_resultado
main
```

Não é obrigatório usar exatamente esses nomes, mas as responsabilidades devem permanecer separadas e fáceis de entender.

No início do arquivo, documentar claramente:

```text
Objetivo
Entrada de dados
Saída de dados
```

Funções simples podem ter descrições curtas. Funções de janelas, cobertura e agregação devem explicar:

- quais dados recebem;
- quais períodos consideram;
- como tratam meses sem compra;
- como calculam as métricas;
- o que devolvem.

A `main()` deve ter comentários numerados explicando cada etapa do processo.

## Validações da saída

Validar antes de gravar:

- chave `(ano_mes, cliente_id)` sem duplicidade;
- todas as linhas com o mesmo `ano_mes` processado;
- `cliente_id` e `nome_empresa` não nulos;
- frequências entre `0` e `1`;
- descontos entre `0` e `1`;
- receitas médias não negativas;
- quantidades médias não negativas;
- nenhuma métrica infinita ou inválida;
- clientes sem compra na janela com métricas iguais a zero;
- nenhum pedido posterior ao fim do mês processado utilizado;
- quantidade de clientes igual à população elegível definida para aquele mês.

## Logs obrigatórios

Registrar:

- data de processamento;
- mês processado;
- início e fim das janelas de 3, 6 e 9 meses;
- menor e maior data disponíveis na Silver;
- primeiro mês completo encontrado;
- quantidade de clientes elegíveis;
- quantidade de clientes com e sem compra na janela de nove meses;
- quantidade de linhas gravadas;
- caminho do arquivo criado.

## Idempotência

Executar duas vezes para a mesma data de processamento deve produzir o mesmo conteúdo e substituir somente o arquivo do mesmo `ano_mes`.

Execuções em dias diferentes do mesmo mês devem processar o mesmo mês anterior.

## Fora do escopo

Não implementar:

- churn;
- risco de churn;
- classificação de clientes;
- pesos ou score;
- alertas;
- previsão;
- frontend;
- exportação para SQLite;
- consumo de tabelas Gold;
- alteração dos jobs históricos já existentes;
- inclusão automática no orquestrador atual.

O novo script deve ser executado explicitamente nesta etapa.

## Testes obrigatórios

Executar pelo menos:

### Caso sem cobertura suficiente

```text
--data-processamento 1997-04-01
```

Deve falhar porque a janela precisaria usar julho/1996, que é parcial.

### Primeira execução válida

```text
--data-processamento 1997-05-01
```

Deve:

- processar `1997-04`;
- usar agosto/1996 até abril/1997 na janela de nove meses;
- criar `historico_cliente_metricas-1997-04.parquet`.

### Mesmo mês, outro dia

```text
--data-processamento 1997-05-25
```

Deve produzir o mesmo `ano_mes` e o mesmo conteúdo da execução em 01/05.

### Proteção contra mês parcial no fim

Usar uma data cujo mês anterior não esteja completamente coberto na Silver.

Deve falhar com mensagem clara, sem gravar arquivo parcial.

## Entrega final

Ao finalizar, informar:

- arquivo criado;
- schema final;
- regras exatas das janelas;
- definição usada para frequência;
- tratamento de meses sem compra;
- regra do desconto médio;
- validações de cobertura;
- resultados dos testes;
- quantidade de clientes e linhas geradas no primeiro mês válido;
- exemplo completo de um cliente com os cálculos de 3, 6 e 9 meses.
