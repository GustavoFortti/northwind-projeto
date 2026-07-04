# Prompt - Descontos no histórico mensal de volume por cliente

Atualize somente o job `historico_cliente_volume.py` para incluir informações mensais de desconto.

Não alterar frontend, churn, scores ou outros jobs.

## Novos campos

Adicionar à tabela `historico_cliente_volume`:

```text
receita_sem_desconto
desconto_medio
```

O schema final deve ser:

```text
ano_mes
cliente_id
nome_empresa
receita_sem_desconto
receita_total
desconto_medio
quantidade_pedidos
quantidade_produtos_distintos
quantidade_itens
```

## Receita sem desconto

Calcular o valor dos itens antes dos descontos:

```text
receita_sem_desconto =
SUM(unit_price × quantity)
```

Esse campo representa o valor bruto dos produtos. Não descrever como receita que a empresa “ganharia”, pois não sabemos se o cliente compraria sem o desconto.

Manter:

```text
receita_total =
SUM(receita_item)
```

`receita_total` representa o valor após os descontos.

## Desconto médio

Não usar `AVG(discount)`, pois isso daria o mesmo peso para itens de valores diferentes.

Calcular o desconto médio ponderado pelo valor bruto:

```text
desconto_medio =
1 - (receita_total ÷ receita_sem_desconto)
```

Forma equivalente:

```text
desconto_medio =
SUM(unit_price × quantity × discount)
÷
SUM(unit_price × quantity)
```

Armazenar como decimal entre `0` e `1`:

```text
0,15 = 15%
```

Se `receita_sem_desconto` for zero, retornar zero para evitar divisão inválida.

## Exemplo

```text
Produto A:
valor bruto = 100
desconto = 10%
receita = 90

Produto B:
valor bruto = 900
desconto = 20%
receita = 720
```

Resultado mensal:

```text
receita_sem_desconto = 1.000
receita_total = 810
desconto_medio = 1 - (810 ÷ 1.000) = 19%
```

A média simples seria 15%, mas estaria errada porque ignoraria o valor de cada item.

## Validações

Adicionar:

- `receita_sem_desconto >= 0`;
- `receita_total >= 0`;
- `receita_sem_desconto >= receita_total`;
- `desconto_medio` entre `0` e `1`;
- soma de `receita_sem_desconto` igual à soma de `unit_price × quantity` na Silver;
- soma de `receita_total` igual à soma de `receita_item` na Silver.

Manter as validações atuais de pedidos, produtos distintos e quantidade de itens.

## Documentação

Atualizar o texto inicial do arquivo:

- objetivo;
- entrada de dados;
- saída de dados.

Explicar na função de agregação a diferença entre:

- valor bruto antes do desconto;
- receita final após desconto;
- desconto médio ponderado.

Atualizar os comentários numerados da `main()` e os logs finais para mostrar:

```text
receita sem desconto
receita após desconto
desconto médio global
```

Não alterar a granularidade: continua uma linha por `ano_mes + cliente`.

Ao finalizar, executar o job e informar schema, totais reconciliados e um exemplo real de cliente/mês.
