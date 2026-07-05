# Visão geral do sistema

## Diagrama do sistema

[Abrir o diagrama em tamanho original](./sistema.svg)

![Diagrama geral do sistema](./sistema.svg)

## Como usar o sistema?

Temos duas telas:

1. **Recomendação de produtos** → Apresenta uma solução para o problema do ticket médio.
2. **Métricas de clientes** → Apresenta uma solução para o problema de churn.

As soluções apresentadas não foram validadas com base em dados, ou seja, não conseguimos comprovar a eficiência dessas soluções. Porém, são estratégias que podem contribuir para resolver os problemas relacionados ao ticket médio e ao churn.

## Tela: Recomendação de produtos

![Tela de recomendação de produtos](./Recomenda%C3%A7%C3%A3o%20de%20produtos.png)

- É uma tela de escolha de produtos para o momento de uma venda. (A forma como as vendas parecem ocorrer no problema proposto é por meio de atendimento ou encomenda via telefone; por isso, a solução foi pensada dessa maneira.)

- Ao escolher um produto, ela mostra uma lista de produtos associados, ou seja, produtos que já apareceram juntos em outras compras. Por exemplo, quem compra feijão também pode comprar arroz; portanto, esses seriam produtos associados.

- A ideia é oferecer ao cliente o arroz no momento em que ele estiver comprando o feijão e, assim, ter a chance de aumentar o ticket médio.

### Observações

- O score é calculado com base nas associações de todas as compras.

- A busca de clientes tem como objetivo preencher o campo “Consumo do cliente”, que representa a quantidade daquele item que o cliente já comprou, considerando todas as suas compras.

- O campo de linha do tempo é utilizado para escolher em qual período estamos, pois isso altera a oferta apresentada ao cliente.

- A oferta é calculada com base no maior desconto aplicado a esse produto em qualquer compra realizada no mês vigente. Por exemplo, se alguém, no mês 5 de 1997, comprou vinho com 20% de desconto, você também poderia receber esse mesmo desconto. Nesse cálculo, desconsideramos regras de volume de compra ou quaisquer outras condições.

## Tela: Métricas de clientes

![Tela de métricas de clientes](./M%C3%A9tricas%20de%20clientes.png)

- É uma tela criada para ajudar a reduzir o churn, identificando mudanças negativas no comportamento do cliente antes que ele deixe de comprar completamente.

- Ao escolher um período na linha do tempo, a tela apresenta o retrato dos clientes naquele momento. Cada cliente recebe um status: “Bom”, “Normal”, “Atenção” ou “Ruim”.

- A classificação permite priorizar clientes que apresentam queda de frequência, receita ou quantidade comprada, facilitando uma abordagem comercial antecipada.

- Além de indicar o problema, a tela sugere produtos e ofertas relevantes, aumentando as chances de recuperar o interesse do cliente e manter o relacionamento.

### Observações

- O status compara o comportamento dos últimos 3 meses com os períodos de 6 e 9 meses.

- Na aba “O que fazer”, são exibidos os produtos comprados pelo cliente nos 9 meses anteriores ao período selecionado. O score considera a frequência de compra do produto e a frequência de outros produtos da mesma categoria.

- A oferta é baseada no maior desconto aplicado ao produto durante o período selecionado. Esse valor é apenas uma referência histórica e desconsidera volume de compra ou outras condições comerciais. (O mesmo da tela de recomendação de produtos.)

- A aba “Por que o Status” é apenas explicativa, mostrando o motivo da classificação.
