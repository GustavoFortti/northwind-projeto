# Prompt — Adicionar aba “O que fazer” ao Status do cliente

Atualize o painel de detalhes da tela existente **Métricas de clientes** no Viewer.

O painel à direita atualmente mostra o Status do cliente, dois gráficos mensais e a seção “Por que este Status?”. Ele deve ser dividido em duas abas:

```text
Por que o Status | O que fazer
```

A aba **Por que o Status** deve preservar o conteúdo explicativo já existente.

A nova aba **O que fazer** deve apresentar os produtos que o cliente comprou, ordenados por um score de recorrência, e a oferta disponível para cada produto no período selecionado.

## 1. Ler o estado atual antes de alterar

Antes da implementação, ler integralmente:

```text
viewer/index.html
viewer/metricas-clientes.js
viewer/styles.css
```

Entender e preservar:

- linha do tempo e `metricasMesSelecionado`;
- seleção da linha do cliente e `metricasClienteSelecionado`;
- objeto enriquecido com as cinco tendências e o Status geral;
- cabeçalho do cliente selecionado;
- gráficos de frequência e receita;
- cards das cinco métricas;
- filtros da tabela de clientes;
- rolagem independente dos cards;
- cache das consultas atuais;
- abertura única de `viewer/data.sqlite` feita por `bi.js`.

Não reimplementar a tela do zero.

## 2. Escopo

Alterar somente o frontend do Viewer:

```text
viewer/index.html
viewer/metricas-clientes.js
viewer/styles.css
```

Alterar apenas os arquivos realmente necessários.

Não alterar:

- pipeline;
- Parquets;
- schema ou conteúdo de `viewer/data.sqlite`;
- cálculos das cinco métricas;
- regra de tendência de 20%;
- regra do Status geral;
- outras páginas do Viewer;
- dependências do projeto.

Não adicionar biblioteca ou framework externo.

## 3. Tabelas SQLite disponíveis

Usar as tabelas que já existem em `viewer/data.sqlite`.

### Histórico mensal de produtos do cliente

```text
historico_cliente_produtos
```

Schema relevante:

```text
ano_mes
cliente_id
produto_id
produto_nome
quantidade_consumida
receita_total
```

A granularidade é uma linha por:

```text
ano_mes + cliente_id + produto_id
```

### Maior desconto por produto e mês

```text
descontos
```

Schema relevante:

```text
ano_mes
produto_id
produto_nome
preco_unitario
maior_desconto
```

A chave usada nesta tela é:

```text
ano_mes + produto_id
```

`maior_desconto` é decimal entre zero e um:

```text
0,10 = 10%
```

Não carregar novamente o arquivo SQLite. Reutilizar `metricasDb`.

## 4. Estrutura visual das abas

O cabeçalho principal do cliente deve permanecer visível acima das abas:

```text
STATUS DO CLIENTE
Maria Anders — Alfreds Futterkiste    [Normal]
Cliente ALFKI · Retrato de 04/98
```

Logo abaixo, criar a navegação:

```text
[ Por que o Status ] [ O que fazer ]
```

### Aba “Por que o Status”

Mover para essa aba todo o conteúdo atual:

- frase que resume o Status;
- gráfico de frequência mensal;
- gráfico de receita mensal;
- título “Por que este Status?”;
- cinco cards de métricas e suas justificativas.

Não alterar os cálculos, textos ou dados dessa aba, exceto pelos ajustes estruturais necessários para colocá-la dentro do painel de abas.

### Aba “O que fazer”

Criar o conteúdo novo:

```text
Produtos com maior recorrência
Produtos já comprados pelo cliente nos 30 meses encerrados em MM/AA.

Nome do produto | Score | Oferta
```

A lista deve ocupar a largura disponível do painel e usar a rolagem vertical já existente no card de detalhes.

## 5. Acessibilidade das abas

Implementar abas acessíveis:

```text
role="tablist"
role="tab"
role="tabpanel"
aria-selected
aria-controls
```

Requisitos:

- clique/toque troca a aba;
- `ArrowLeft` e `ArrowRight` navegam entre as abas;
- `Home` seleciona a primeira aba;
- `End` seleciona a última aba;
- foco visível;
- apenas o painel ativo fica visível;
- o conteúdo continua acessível sem depender de hover.

Ao abrir a tela pela primeira vez, selecionar:

```text
Por que o Status
```

Ao trocar o cliente ou o período, preservar a aba ativa. Isso permite comparar rapidamente a aba “O que fazer” entre clientes diferentes.

Se o painel ficar sem cliente selecionado, manter as abas desabilitadas ou mostrar o estado vazio já existente.

## 6. Janela fixa de 30 meses fechados

O score deve considerar uma janela retrospectiva fixa de 30 meses, terminando no `Período selecionado` da linha do tempo.

Exemplo para período selecionado `1998-04`:

```text
mês final   = 1998-04
mês inicial = 1995-11
```

Usar a função de manipulação de `YYYY-MM` já existente, como `metricasSomarMeses`, para calcular:

```javascript
const mesInicial = metricasSomarMeses(metricasMesSelecionado, -29);
const mesFinal = metricasMesSelecionado;
```

A janela contém exatamente:

```text
mês selecionado + 29 meses anteriores = 30 meses
```

Não usar meses posteriores ao período selecionado.

O denominador permanece 30 mesmo quando o SQLite ainda não possui 30 meses anteriores de histórico. Meses ausentes contam como meses sem compra. Essa é uma regra deliberada do score.

## 7. Quais produtos entram na lista

Listar somente produtos para os quais o cliente tenha pelo menos uma linha em `historico_cliente_produtos` dentro da janela de 30 meses.

Para cada produto, contar em quantos meses distintos ele foi comprado:

```text
meses_com_compra = COUNT(DISTINCT ano_mes)
```

Uma ou várias compras do mesmo produto no mesmo mês contam apenas uma vez.

Exemplos:

```text
Julho:  10 unidades de vinho
Agosto: 10 unidades de vinho

meses_com_compra = 2
```

```text
Julho: três pedidos diferentes com vinho
Agosto: nenhum pedido com vinho

meses_com_compra = 1
```

Não somar `quantidade_consumida` para formar frequência ou score. Quantidade e receita não entram no score desta versão.

## 8. Cálculo da frequência e do Score

Calcular a frequência do produto:

```text
frequencia_compra_produto = meses_com_compra ÷ 30
```

Calcular o Score em pontos:

```text
score = TRUNCAR(frequencia_compra_produto × 100)
```

Forma equivalente:

```text
score = FLOOR((meses_com_compra × 100) ÷ 30)
```

O Score fica entre zero e 100 pontos.

Usar truncamento para baixo, não arredondamento convencional, para reproduzir a regra definida.

Exemplo obrigatório:

```text
meses_com_compra = 2

frequencia = 2 ÷ 30
frequencia = 0,0666...
frequencia aproximada = 6,66%
score = FLOOR(6,66)
score = 6 pontos
```

Outros exemplos:

```text
1 mês  de 30 -> 3 pontos
3 meses de 30 -> 10 pontos
15 meses de 30 -> 50 pontos
30 meses de 30 -> 100 pontos
```

O Score é um indicador de recorrência histórica, não uma probabilidade estatística calibrada. Na interface, pode ser descrito como “quanto maior o Score, mais recorrente foi a compra do produto”. Não afirmar que existe garantia de nova compra.

## 9. Ordenação

Ordenar a lista obrigatoriamente por:

```text
1. meses_com_compra DESC
2. produto_nome ASC
```

Como o Score deriva diretamente de `meses_com_compra`, isso equivale a ordenar do maior Score para o menor, mas evita qualquer ambiguidade causada pelo truncamento.

Não permitir que a ordenação padrão seja substituída pela oferta.

## 10. Cálculo da Oferta

A Oferta depende do produto e do mês apontado em `Período selecionado`.

Para cada produto da lista, procurar em `descontos`:

```text
descontos.produto_id = produto comprado
descontos.ano_mes = metricasMesSelecionado
```

Usar:

```text
oferta = descontos.maior_desconto
```

Exemplo:

```text
Vinho no mês 1996-07 -> maior_desconto = 0,05 -> Oferta 5%
Vinho no mês 1996-08 -> maior_desconto = 0,10 -> Oferta 10%
```

Se o período selecionado for `1996-08`, mostrar:

```text
10%
```

Não calcular média entre meses. Não buscar o último desconto conhecido. Não usar desconto futuro. Não usar o desconto específico pago pelo cliente.

O campo representa o maior desconto observado para aquele produto no mês selecionado, conforme a tabela `descontos`.

### Ausência de desconto

Tratar separadamente:

```text
registro existente e maior_desconto = 0
    mostrar “0%” ou “Sem desconto”

nenhum registro do produto no mês selecionado
    mostrar “Sem oferta no período”
```

Não transformar ausência de registro em desconto zero sem explicação.

## 11. Consulta SQL recomendada

Criar uma função específica, por exemplo:

```javascript
carregarAcoesCliente(db, clienteId, anoMesSelecionado)
```

Usar statement preparado.

Consulta equivalente:

```sql
WITH compras AS (
    SELECT
        h.produto_id,
        MAX(h.produto_nome) AS produto_nome,
        COUNT(DISTINCT h.ano_mes) AS meses_com_compra
    FROM historico_cliente_produtos AS h
    WHERE h.cliente_id = :cliente_id
      AND h.ano_mes BETWEEN :mes_inicial AND :mes_final
    GROUP BY h.produto_id
)
SELECT
    c.produto_id,
    c.produto_nome,
    c.meses_com_compra,
    CAST((c.meses_com_compra * 100.0) / 30 AS INTEGER) AS score,
    d.maior_desconto AS oferta
FROM compras AS c
LEFT JOIN descontos AS d
       ON d.produto_id = c.produto_id
      AND d.ano_mes = :mes_final
ORDER BY
    c.meses_com_compra DESC,
    c.produto_nome ASC;
```

Como os valores são não negativos, `CAST(... AS INTEGER)` no SQLite produz o truncamento desejado.

Parâmetros:

```text
:cliente_id = cliente selecionado
:mes_inicial = período selecionado menos 29 meses
:mes_final = período selecionado
```

Liberar o statement em `finally`.

Não concatenar `cliente_id` ou meses diretamente no SQL.

## 12. Cache

Criar cache específico para a nova aba, com chave composta:

```text
cliente_id + ano_mes selecionado
```

Exemplo:

```javascript
const metricasAcoesCache = new Map();
const chave = `${clienteId}|${anoMesSelecionado}`;
```

Trocar de aba não deve repetir a consulta para o mesmo cliente e período.

Trocar o período deve usar outra chave, pois tanto o Score quanto a Oferta podem mudar.

## 13. Apresentação da lista

Criar uma tabela compacta com três colunas:

```text
Nome do produto
Score
Oferta
```

### Nome do produto

- mostrar `produto_nome` completo;
- permitir quebra controlada em até duas linhas;
- não ocultar silenciosamente nomes com reticências;
- usar `produto_id` apenas como chave interna.

### Score

Mostrar:

```text
6 pontos
```

Como informação secundária, mostrar:

```text
2 de 30 meses
```

Pode usar uma barra visual discreta de zero a 100, desde que o número continue visível e acessível. Não comunicar Score somente por cor.

Adicionar explicação curta no cabeçalho ou subtítulo:

```text
Score baseado na quantidade de meses em que o produto foi comprado dentro de uma janela fixa de 30 meses.
```

### Oferta

Mostrar como tag:

```text
10%
```

Para zero:

```text
Sem desconto
```

Para ausência de registro:

```text
Sem oferta
```

Adicionar texto acessível deixando claro que se trata do maior desconto observado para o produto no mês selecionado.

## 14. Atualização da aba

Quando o usuário selecionar outro cliente:

1. preservar a aba ativa;
2. carregar a lista do novo cliente;
3. recalcular a janela de 30 meses com o mesmo período selecionado;
4. atualizar Score e Oferta;
5. levar o conteúdo da aba ao topo.

Quando o usuário trocar o período:

1. preservar o cliente quando ele continuar disponível;
2. recalcular o intervalo inicial e final;
3. excluir compras posteriores ao novo período;
4. buscar a Oferta exatamente no novo mês;
5. atualizar a lista mesmo se a aba “O que fazer” já estiver aberta.

Não buscar dados futuros e não manter na tela uma oferta do período anterior.

## 15. Estados vazios e erros

Se o cliente não tiver produtos na janela de 30 meses:

```text
Nenhum produto comprado por este cliente nos 30 meses até MM/AA.
```

Se a consulta falhar:

- mostrar erro somente dentro da aba;
- manter a tabela de clientes e a aba “Por que o Status” utilizáveis;
- não quebrar as outras páginas.

Se não existir oferta para um produto, manter o produto na lista e usar o estado `Sem oferta`.

## 16. Responsividade e rolagem

- preservar a altura igual entre o card de clientes e o card de detalhes;
- manter a rolagem vertical interna do card de detalhes;
- a barra de abas deve permanecer visível ou facilmente alcançável ao voltar ao topo;
- a tabela de produtos deve caber no painel sem criar rolagem horizontal no desktop;
- em telas estreitas, permitir quebra do nome do produto;
- Score e Oferta devem continuar legíveis;
- não reintroduzir o quadrado branco no canto da scrollbar;
- estilizar trilha, thumb e `scrollbar-corner` com o tema escuro existente.

## 17. Segurança e qualidade

- Usar `"use strict"`.
- Usar statements preparados.
- Liberar statements em `finally`.
- Inserir valores com `textContent`, nunca `innerHTML`.
- Não carregar novamente `data.sqlite`.
- Prefixar novos nomes globais com `metricas`.
- Não duplicar funções existentes de período ou formatação.
- Não misturar a consulta da aba com a regra de Status.
- Remover código morto criado durante a refatoração.

## 18. Testes obrigatórios do Score

Validar a função ou consulta com:

```text
0 meses  -> produto não entra na lista
1 mês    -> 3 pontos
2 meses  -> 6 pontos
3 meses  -> 10 pontos
15 meses -> 50 pontos
30 meses -> 100 pontos
```

Validar também:

- dez unidades em um mês contam como um mês;
- vários pedidos do mesmo produto no mesmo mês contam como um mês;
- compras em dois meses diferentes contam como dois;
- compras posteriores ao período selecionado não entram;
- compras anteriores ao início da janela não entram;
- meses ausentes no histórico continuam fazendo parte do denominador fixo 30;
- lista ordenada por `meses_com_compra DESC`.

## 19. Testes obrigatórios da Oferta

Validar:

```text
maior_desconto = 0,05 -> 5%
maior_desconto = 0,10 -> 10%
maior_desconto = 0    -> Sem desconto
registro inexistente  -> Sem oferta
```

Trocar o período entre dois meses com descontos diferentes deve atualizar imediatamente a Oferta.

Confirmar que:

- Oferta usa `produto_id` e mês selecionado;
- não usa média histórica;
- não usa o maior desconto de todos os meses;
- não usa dados de meses posteriores;
- não remove produtos sem oferta.

## 20. Testes de interface e regressão

Servir `viewer/` por HTTP e verificar:

1. As duas abas aparecem abaixo do cabeçalho do cliente.
2. “Por que o Status” inicia ativa.
3. A aba existente mantém gráficos e cinco métricas.
4. “O que fazer” mostra `Nome do produto`, `Score` e `Oferta`.
5. A lista está ordenada por recorrência.
6. Score mostra pontos e meses de compra em 30.
7. Oferta corresponde ao período da linha do tempo.
8. Trocar cliente atualiza a lista.
9. Trocar período atualiza Score e Oferta.
10. Trocar de aba não repete consultas cacheadas.
11. Navegação por teclado funciona.
12. Estados vazios são claros.
13. As duas rolagens mestre–detalhe continuam independentes.
14. Não há rolagem horizontal ou canto branco no desktop.
15. Não há erros no console.
16. Cálculos de tendência e Status permanecem iguais.
17. Outras páginas do Viewer continuam funcionando.

## 21. Critérios de aceite

A tarefa estará concluída quando:

- o painel possuir as abas `Por que o Status` e `O que fazer`;
- a primeira aba preservar integralmente a explicação atual;
- a segunda aba listar produtos comprados na janela fixa de 30 meses;
- cada produto contar no máximo uma ocorrência por mês;
- o Score for `FLOOR(meses_com_compra / 30 × 100)`;
- dois meses com compra resultarem em 6 pontos;
- a lista estiver ordenada por meses com compra, do maior para o menor;
- a Oferta usar `descontos.maior_desconto` do produto no período selecionado;
- zero e ausência de oferta forem diferenciados;
- nenhuma compra ou oferta futura entrar no cálculo;
- troca de cliente e período atualizar corretamente a aba;
- abas forem acessíveis e responsivas;
- nenhuma regra existente de Status for alterada;
- SQLite, pipeline e demais telas permanecerem intactos.

## 22. Entrega final

Ao finalizar, informar:

- arquivos alterados;
- estrutura HTML e ARIA das abas;
- consulta SQL final da lista;
- cálculo exato do mês inicial e final;
- fórmula e arredondamento do Score;
- ordenação aplicada;
- tratamento de Oferta zero e inexistente;
- estratégia de cache;
- testes executados e resultados;
- confirmação de que cálculos de Status, SQLite e pipeline não foram modificados.
