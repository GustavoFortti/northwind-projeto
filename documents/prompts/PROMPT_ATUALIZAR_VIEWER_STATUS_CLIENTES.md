# Prompt - Consolidar métricas no Status do cliente e criar painel explicativo

Atualize a tela existente **Métricas de clientes** no Viewer.

A tela já foi implementada e atualmente possui:

- linha do tempo mensal;
- filtros por cliente, empresa e por cada uma das cinco métricas;
- tabela com `Cliente`, `Empresa` e cinco colunas de tendência;
- tags `Aumentou`, `Normal` e `Diminuiu` por métrica;
- cards explicativos exibidos ao passar o mouse ou focar cada tag.

O objetivo desta alteração é substituir as cinco colunas por um único **Status do cliente**, reorganizar a área abaixo da linha do tempo em um layout mestre–detalhe e exibir uma justificativa permanente e mais útil para o cliente selecionado.

## 1. Ler o estado atual antes de alterar

Antes de implementar, ler integralmente:

```text
viewer/index.html
viewer/metricas-clientes.js
viewer/styles.css
viewer/bi.js
```

Entender e preservar:

- a abertura única de `viewer/data.sqlite` feita por `bi.js`;
- o compartilhamento da instância `db` com `window.iniciarMetricasClientes(db)`;
- a linha do tempo e sua navegação por teclado;
- o cache mensal já existente;
- a estrutura da função individual `classificarTendencia`, que deverá ser atualizada conforme a nova regra deste prompt;
- a diferença direta usada para frequência e desconto;
- a variação relativa usada para receita, variedade e quantidade;
- o tratamento de zero e de ponto flutuante;
- os filtros de texto por cliente e empresa;
- o tema escuro e a responsividade do Viewer.

Não reimplementar a tela do zero sem necessidade. Refatorar a implementação atual, removendo o que deixou de ser usado.

## 2. Escopo de arquivos

Alterar somente o frontend do Viewer:

```text
viewer/index.html
viewer/metricas-clientes.js
viewer/styles.css
```

Alterar `viewer/bi.js` apenas se for estritamente necessário para manter a inicialização ou o redimensionamento dos novos gráficos.

Não alterar:

- pipeline;
- arquivos Parquet;
- schema ou conteúdo de `viewer/data.sqlite`;
- cálculos Gold;
- outras páginas do Viewer;
- tooltips de Vendas, BI ou Grafo;
- dependências do projeto.

Não adicionar bibliotecas externas. Construir os gráficos com SVG e JavaScript nativos, seguindo o padrão já existente em `viewer/bi.js`.

## 3. Fontes de dados

Usar duas tabelas já existentes no mesmo SQLite:

```text
historico_cliente_metricas
historico_cliente_volume
```

### `historico_cliente_metricas`

Continuar usando essa tabela para:

- obter os meses disponíveis da linha do tempo;
- obter os clientes existentes no retrato mensal selecionado;
- ler os valores acumulados de 3, 6 e 9 meses;
- calcular a tendência individual das cinco métricas;
- calcular o novo Status geral do cliente;
- construir a justificativa detalhada.

### `historico_cliente_volume`

Usar essa tabela para os dois gráficos mensais do cliente selecionado:

```text
ano_mes
cliente_id
nome_empresa
receita_total
quantidade_pedidos
quantidade_produtos_distintos
quantidade_itens
```

Para o gráfico de **frequência mensal**, usar:

```text
quantidade_pedidos
```

Na interface, deixar claro que frequência mensal significa a quantidade de pedidos realizados no mês. Não afirmar que cada pedido corresponde necessariamente a uma visita física.

Para o gráfico de **receita mensal**, usar:

```text
receita_total
```

Não buscar ou abrir o SQLite novamente. Reutilizar `metricasDb`.

## 4. Atualizar a classificação individual das cinco métricas

Continuar classificando individualmente cada métrica como:

```text
aumentou
normal
diminuiu
```

Continuar calculando os estados individuais para:

```text
frequencia_compra
receita_media
desconto_medio
quantidade_produtos_distintos_media
quantidade_itens_media
```

Continuar comparando diretamente as janelas acumuladas:

```text
3m = meses 1 a 3
6m = meses 1 a 6
9m = meses 1 a 9
```

Não decompor essas janelas em blocos independentes.

### 4.1 Problema da regra atual

A regra atual compara:

```text
3m com 6m
6m com 9m
```

e exige que as duas comparações ultrapassem o limite no mesmo sentido. Isso mascara uma mudança recente quando `6m` e `9m` são iguais.

Exemplo:

```text
frequência_3m = 66,7%
frequência_6m = 100,0%
frequência_9m = 100,0%
```

Na regra antiga:

```text
3m × 6m = -33,3 p.p.
6m × 9m =   0,0 p.p.
```

Como a segunda comparação é zero, o resultado antigo fica `Normal`, apesar da queda recente. Esse comportamento deve ser corrigido.

### 4.2 Novas comparações

Comparar sempre a janela mais recente de três meses contra as duas referências mais longas:

```text
comparação A = 3m com 6m
comparação B = 3m com 9m
```

Não comparar mais `6m` com `9m` para classificar a tendência.

Calcular um único índice pela média das duas comparações:

```text
indice_tendencia = (comparacao_3_6 + comparacao_3_9) / 2
```

Os parênteses são obrigatórios. Não implementar como `a + b / 2`.

### 4.3 Nova tolerância

Alterar a constante centralizada para:

```javascript
const TOLERANCIA_TENDENCIA = 0.20;
```

O novo limite é 20%.

Classificar:

```text
indice_tendencia > +0,20  -> aumentou
indice_tendencia < -0,20  -> diminuiu
entre -0,20 e +0,20       -> normal
```

Os limites exatos `+0,20` e `-0,20` pertencem a `Normal`. Usar comparação estrita e preservar a margem de ponto flutuante já existente.

### 4.4 Frequência e desconto: diferença direta

Para métricas que já são proporções entre zero e um:

```text
frequencia_compra
desconto_medio
```

usar diferença direta:

```text
comparacao_3_6 = valor3m - valor6m
comparacao_3_9 = valor3m - valor9m
indice_tendencia = (comparacao_3_6 + comparacao_3_9) / 2
```

O índice fica em pontos percentuais representados como decimal.

Exemplo obrigatório:

```text
3m = 0,667
6m = 1,000
9m = 1,000

comparacao_3_6 = 0,667 - 1,000 = -0,333
comparacao_3_9 = 0,667 - 1,000 = -0,333

indice_tendencia = (-0,333 + -0,333) / 2
indice_tendencia = -0,333

-0,333 < -0,20
resultado = diminuiu
```

Para frequência, interpretar corretamente os valores:

```text
66,7% em 3m  = compra em 2 dos últimos 3 meses
100% em 6m   = compra nos 6 dos últimos 6 meses
100% em 9m   = compra nos 9 dos últimos 9 meses
```

Os percentuais são normalizados para permitir a comparação direta, mas a quantidade de meses ativos depende do tamanho de cada janela.

### 4.5 Receita, itens variados e quantidade: variação relativa

Para métricas de valor absoluto:

```text
receita_media
quantidade_produtos_distintos_media
quantidade_itens_media
```

manter a variação relativa contra cada referência:

```text
comparacao_3_6 = (valor3m - valor6m) / |valor6m|
comparacao_3_9 = (valor3m - valor9m) / |valor9m|
indice_tendencia = (comparacao_3_6 + comparacao_3_9) / 2
```

Exemplo:

```text
3m = 80
6m = 100
9m = 120

comparacao_3_6 = (80 - 100) / 100 = -0,20
comparacao_3_9 = (80 - 120) / 120 = -0,3333
indice_tendencia = (-0,20 + -0,3333) / 2 = -0,2667

-0,2667 < -0,20
resultado = diminuiu
```

### 4.6 Tratamento de zero

Preservar o tratamento seguro usado pela variação relativa:

```text
base = 0 e atual = 0 -> variação = 0
base = 0 e atual > 0 -> variação = +Infinity
base > 0             -> cálculo relativo normal
```

Nunca produzir `NaN`.

Ao calcular a média:

- duas comparações finitas: média aritmética normal;
- pelo menos uma comparação `+Infinity`: índice `+Infinity`;
- os três valores iguais a zero: índice zero e resultado `normal`.

### 4.7 Retorno da função

Atualizar `classificarTendencia` para devolver dados suficientes para a justificativa permanente, por exemplo:

```javascript
{
  estado,
  comparacao36,
  comparacao39,
  indiceTendencia,
  modo
}
```

Remover do retorno e do restante do código a antiga `variacao69`, quando ela não tiver mais uso.

Os cinco estados individuais deixam de ser colunas da tabela, mas continuam existindo no objeto enriquecido de cada cliente, pois alimentam o Status geral e o painel explicativo.

O novo Status geral descrito na próxima seção deve obrigatoriamente usar essas flags individuais recalculadas. Portanto, no exemplo `66,7% / 100% / 100%`, a frequência passa a ser `Diminuiu` e pode ativar `Atenção` ou `Ruim`, conforme os estados de receita e quantidade.

## 5. Novo Status geral do cliente

Adicionar uma função pura e separada da classificação individual, por exemplo:

```javascript
classificarStatusCliente(estados)
```

Ela deve devolver pelo menos:

```javascript
{
  status: "bom" | "normal" | "atencao" | "ruim",
  motivos: [...]
}
```

Usar estas abreviações conceituais:

```text
F = estado de frequencia_compra
R = estado de receita_media
Q = estado de quantidade_itens_media
```

`desconto_medio` e `quantidade_produtos_distintos_media` não definem o Status geral nesta versão. Elas são métricas de contexto e devem continuar aparecendo na explicação.

### 5.1 Ruim - vermelho

O Status é `ruim` quando qualquer uma destas regras for verdadeira:

```text
R diminuiu E (F diminuiu OU Q diminuiu)
```

ou:

```text
F diminuiu E (R diminuiu OU Q diminuiu)
```

Forma equivalente, útil apenas para validar a implementação:

```text
pelo menos duas entre F, R e Q estão como diminuiu
```

Exemplos que devem resultar em `ruim`:

```text
F diminuiu + R diminuiu
F diminuiu + Q diminuiu
R diminuiu + Q diminuiu
F diminuiu + R diminuiu + Q diminuiu
```

### 5.2 Atenção - amarelo

Se não for `ruim`, o Status é `atencao` quando:

```text
F diminuiu OU R diminuiu
```

Exemplos:

```text
F diminuiu + R normal + Q normal       -> Atenção
F aumentou + R diminuiu + Q normal     -> Atenção
F normal + R diminuiu + Q aumentou     -> Atenção
```

### 5.3 Bom - verde

Se não for `ruim` nem `atencao`, o Status é `bom` quando:

```text
F aumentou E R aumentou
```

A quantidade, o desconto e a variedade não impedem o Status `bom` nesta versão, desde que as regras prioritárias de `ruim` e `atencao` não tenham sido atendidas.

### 5.4 Normal - cinza

Se não for `ruim`, `atencao` ou `bom`, o Status é `normal`.

Nos casos esperados, isso significa que:

```text
F é normal OU R é normal
```

sem nenhuma queda de frequência ou receita que já tivesse levado a `atencao`.

Exemplos:

```text
F normal + R normal       -> Normal
F normal + R aumentou     -> Normal
F aumentou + R normal     -> Normal
```

### 5.5 Precedência obrigatória

Aplicar as regras nesta ordem:

```text
1. Ruim
2. Atenção
3. Bom
4. Normal
```

Essa precedência é obrigatória. Por exemplo, frequência diminuída e quantidade diminuída devem resultar em `Ruim`, mesmo que a receita esteja normal.

Centralizar rótulos e apresentação:

```text
bom      -> Bom
normal   -> Normal
atencao  -> Atenção
ruim     -> Ruim
```

Não usar acento na chave interna `atencao`; usar acento apenas no texto apresentado.

## 6. Aparência do Status

Exibir Status como tag com texto e indicador visual, nunca somente por cor:

```text
Bom      - verde
Normal   - cinza
Atenção  - amarelo
Ruim     - vermelho
```

Criar classes próprias, por exemplo:

```text
metricas-status-cliente--bom
metricas-status-cliente--normal
metricas-status-cliente--atencao
metricas-status-cliente--ruim
```

As cores devem ter contraste adequado no tema escuro. A linha selecionada também deve ter um destaque independente da cor do Status.

## 7. Nova tabela de clientes

Substituir as cinco colunas atuais de métricas por uma única coluna `Status`.

A tabela deve ficar com exatamente estas três colunas:

```text
Cliente
Empresa
Status
```

Cada linha deve ser selecionável por clique e teclado. Usar semântica acessível e indicar a seleção com `aria-selected="true"` ou abordagem equivalente.

Ao selecionar uma linha:

- guardar o `cliente_id` selecionado;
- destacar visualmente a linha;
- atualizar os dois gráficos;
- atualizar a justificativa das cinco métricas;
- atualizar título, empresa e Status do painel explicativo;
- não abrir tooltip ou popover.

Comportamento de seleção:

1. Ao abrir a tela ou trocar de mês, selecionar o primeiro cliente visível.
2. Se o mesmo cliente existir no novo mês, pode preservar a seleção.
3. Ao mudar filtros, preservar o cliente selecionado se ele continuar visível.
4. Se o cliente selecionado deixar de estar visível, selecionar a primeira linha filtrada.
5. Se nenhum cliente estiver visível, mostrar estado vazio no painel explicativo.

## 8. Filtros

Manter:

```text
Cliente - busca textual por cliente_id
Empresa - busca textual por nome_empresa
```

Remover completamente os cinco filtros individuais:

```text
Frequência de compra
Média de receita
Média de desconto
Média de itens variados
Média de quantidade
```

Adicionar somente um filtro de Status:

```text
Status
    Todos
    Bom
    Normal
    Atenção
    Ruim
```

Os três filtros restantes combinam com `E`:

```text
cliente E empresa E status
```

Atualizar o botão `Limpar filtros` para limpar:

- busca por cliente;
- busca por empresa;
- filtro de Status;
- e restaurar a seleção coerentemente.

Remover do JavaScript:

- `metricasFiltroClasse` por métrica;
- loops de filtros construídos a partir de `METRICAS_FILTRAVEIS`;
- referências aos cinco `<select>` removidos;
- qualquer código morto decorrente dessa alteração.

## 9. Remover os cards exibidos sobre as tags

O card atual que aparece ao passar o mouse ou focar uma tag individual não deve mais existir.

Remover de `viewer/metricas-clientes.js` todo o código exclusivo desse comportamento, incluindo:

- estado de hover/foco do tooltip;
- temporizadores de fechamento;
- montagem de conteúdo;
- posicionamento do card;
- listeners de `pointerenter`, `pointerleave`, `focus`, `blur` e `Escape` ligados a esse tooltip;
- inicialização global do tooltip de métricas;
- ligação do tooltip às antigas células de tendência.

Remover de `viewer/index.html`:

```html
<div id="metricas-tooltip" ...></div>
```

Remover de `viewer/styles.css`:

- `.metricas-tooltip` e suas variações;
- estilos exclusivos das antigas cinco tags, quando não forem mais utilizados.

Não remover:

- `#bi-tooltip`;
- `#vendas-tooltip`;
- tooltips do Grafo;
- classes `.vt-*` que ainda forem usadas pela página de Vendas;
- qualquer código compartilhado com outras páginas.

A nova tag de Status não deve abrir card ao passar o mouse. A explicação ficará permanentemente no painel do cliente selecionado.

## 10. Novo layout em duas colunas

Manter o cabeçalho e a linha do tempo ocupando toda a largura.

Abaixo da linha do tempo, substituir o card único atual por uma área em duas colunas:

```text
┌──────────────────────────────┬───────────────────────────┐
│ Tabela de clientes           │ Explicação do cliente     │
│ Cliente | Empresa | Status   │ selecionado               │
│                              │                           │
│                              │ [gráfico frequência]      │
│                              │ [gráfico receita]         │
│                              │                           │
│                              │ Por que este status       │
│                              │ 5 métricas explicadas     │
└──────────────────────────────┴───────────────────────────┘
```

No desktop:

- tabela de clientes à esquerda;
- painel explicativo à direita;
- usar proporção aproximada de `45% / 55%`, dando um pouco mais de largura aos detalhes e gráficos;
- os dois lados devem começar alinhados no topo;
- a tabela pode ter rolagem vertical interna;
- o painel explicativo pode crescer verticalmente sem cortar conteúdo.

Esta posição é obrigatória e segue o desenho fornecido: lista para seleção à esquerda e detalhes do cliente à direita.

Em telas estreitas:

- empilhar as áreas em uma coluna;
- mostrar primeiro a tabela, para o usuário escolher o cliente;
- mostrar depois o painel explicativo;
- ao selecionar um cliente, manter navegação utilizável sem criar rolagem horizontal na página;
- gráficos e blocos de métricas devem ocupar 100% da largura disponível.

## 11. Cabeçalho do painel explicativo

Quando houver cliente selecionado, mostrar no topo do painel:

```text
Status do cliente
ALFKI - Alfreds Futterkiste
[tag Status]
Retrato de 04/98
```

Logo abaixo, exibir uma frase curta e gerada a partir das regras reais.

Exemplos:

```text
Bom:
“Frequência de compra e receita média aumentaram.”

Normal:
“Frequência e receita permanecem dentro do comportamento normal.”

Atenção:
“A receita média diminuiu; acompanhe a evolução deste cliente.”

Ruim:
“Receita média e quantidade comprada diminuíram, atendendo ao critério de risco.”
```

Não usar uma mensagem genérica se for possível citar exatamente quais regras foram acionadas. A propriedade `motivos` devolvida por `classificarStatusCliente` deve alimentar esse resumo.

Evitar afirmar que o cliente “vai abandonar”, “é churn” ou que uma métrica causou outra. A tela mostra sinais históricos, não previsão ou causalidade.

## 12. Gráficos mensais

Criar dois gráficos de linha lado a lado dentro do painel explicativo:

```text
Frequência mensal
Receita mensal
```

### 12.1 Período

Exibir exatamente os nove meses que terminam no `ano_mes` selecionado.

Exemplo para `1998-01`:

```text
1997-05, 1997-06, 1997-07, 1997-08, 1997-09,
1997-10, 1997-11, 1997-12, 1998-01
```

Gerar a sequência completa de meses em JavaScript. Se o cliente não tiver linha em `historico_cliente_volume` para algum mês, preencher:

```text
quantidade_pedidos = 0
receita_total = 0
```

Não omitir meses sem compra, pois isso distorceria a evolução.

### 12.2 Consulta

Usar statement preparado, com parâmetros, equivalente a:

```sql
SELECT
    ano_mes,
    quantidade_pedidos,
    receita_total
FROM historico_cliente_volume
WHERE cliente_id = :cliente_id
  AND ano_mes BETWEEN :mes_inicial AND :mes_final
ORDER BY ano_mes;
```

Liberar o statement em `finally`.

Criar cache com chave composta, por exemplo:

```text
cliente_id + ano_mes selecionado
```

Não recarregar o SQLite e não consultar novamente a mesma combinação sem necessidade.

### 12.3 Gráfico de frequência

Usar:

```text
eixo X = mês
eixo Y = quantidade_pedidos
```

Título visível:

```text
Frequência mensal
```

Subtítulo:

```text
Pedidos realizados em cada mês
```

O eixo Y deve partir de zero e usar valores inteiros.

### 12.4 Gráfico de receita

Usar:

```text
eixo X = mês
eixo Y = receita_total
```

Título visível:

```text
Receita mensal
```

Subtítulo:

```text
Receita após descontos em cada mês
```

Formatar valores em `pt-BR`, com duas casas nos detalhes e escala compacta nos eixos quando necessário.

### 12.5 Apresentação e acessibilidade

- usar SVG nativo;
- não adicionar biblioteca de gráficos;
- manter o padrão visual do Viewer;
- mostrar linha, pontos e grade discreta;
- destacar o mês selecionado;
- incluir título acessível ou descrição textual do gráfico;
- criar um estado apropriado quando todos os nove valores forem zero;
- redimensionar os gráficos quando o painel mudar de largura;
- não criar o antigo card flutuante de explicação das tags.

## 13. Seção “Por que este Status?”

Abaixo dos gráficos, criar uma seção permanente:

```text
Por que este Status?
```

Ela deve explicar as cinco métricas usando os dados de `historico_cliente_metricas` já carregados para a linha selecionada.

Não mostrar somente um parágrafo solto. Criar cinco linhas ou pequenos cards consistentes, um por métrica.

Cada item deve conter:

1. nome da métrica;
2. tag individual `Aumentou`, `Normal` ou `Diminuiu`;
3. valores de `3m`, `6m` e `9m`;
4. resumo compacto das comparações `3m × 6m` e `3m × 9m`;
5. média das duas comparações;
6. uma frase curta de interpretação;
7. indicação do papel da métrica no Status geral.

Apresentar cada métrica como uma linha ou card horizontal compacto com esta hierarquia:

```text
┌────────────────────────────────────────────────────────────┐
│ Frequência de compra     [↑ Aumentou]     Indicador principal│
│ 3 meses       6 meses       9 meses                         │
│ 100% (3/3)    66,7% (4/6)   55,6% (5/9)                    │
│ 3×6: +33,3 p.p. · 3×9: +44,4 p.p. · média: +38,9 p.p.     │
│ A variação média contra 6m e 9m superou +20%.               │
└────────────────────────────────────────────────────────────┘
```

O exemplo visual acima deve respeitar a própria classificação: se a média exibida não ultrapassar `+20%`, a tag e a frase precisam ser `Normal`. Nunca mostrar números incompatíveis com o estado calculado.

As cinco métricas devem aparecer sempre na mesma ordem:

```text
1. Frequência de compra
2. Média de receita
3. Média de desconto
4. Média de itens variados
5. Média de quantidade
```

Exemplo da seção completa, em formato conceitual:

```text
Por que este Status?

Frequência de compra     [↓ Diminuiu]  Principal · participou do Status
3m: 33,3% (1/3) | 6m: 50,0% (3/6) | 9m: 66,7% (6/9)
3×6: -16,7 p.p. | 3×9: -33,4 p.p. | média: -25,1 p.p.
A variação média da frequência contra 6m e 9m ficou abaixo de -20%.

Média de receita         [↓ Diminuiu]  Principal · participou do Status
3m: 280,00 | 6m: 410,00 | 9m: 520,00
3×6: -31,7% | 3×9: -46,2% | média: -39,0%
A variação relativa média da receita contra 6m e 9m ficou abaixo de -20%.

Média de desconto        [• Normal]    Contexto · não define o Status
3m: 8,0% | 6m: 7,5% | 9m: 8,1%
3×6: +0,5 p.p. | 3×9: -0,1 p.p. | média: +0,2 p.p.
O desconto permaneceu dentro da faixa de tolerância ou oscilou.

Média de itens variados  [• Normal]    Contexto · não define o Status
3m: 2,30 | 6m: 2,20 | 9m: 2,40
3×6: +4,5% | 3×9: -4,2% | média: +0,2%
A variedade média permaneceu normal.

Média de quantidade      [↓ Diminuiu]  Agravante · reforçou o Status Ruim
3m: 12,00 | 6m: 18,00 | 9m: 25,00
3×6: -33,3% | 3×9: -52,0% | média: -42,7%
A quantidade média diminuiu e reforçou a classificação de risco.
```

Os números acima são somente exemplo visual. A implementação deve usar os valores reais do cliente e mês selecionados.

Não repetir fórmulas matemáticas longas nessa área. Mostrar somente as duas variações e sua média em uma linha compacta. O objetivo é permitir leitura rápida: o que aconteceu, quais valores foram usados, qual índice determinou a flag e se a métrica influenciou o Status.

Papéis possíveis:

```text
Principal
    frequência de compra
    receita média

Agravante
    média de quantidade

Contexto
    média de desconto
    média de itens variados
```

Não chamar quantidade de agravante em todos os casos. Ela só deve ser destacada como agravante quando estiver `Diminuiu` e tiver participado da regra que tornou o Status `Ruim`. Nos demais casos, pode aparecer como `Apoio` ou `Contexto operacional`.

### 13.1 Frequência de compra

Exibir como percentual e explicar em quantidade de meses ativos:

```text
3m: 66,7% - comprou em 2 dos últimos 3 meses
6m: 50,0% - comprou em 3 dos últimos 6 meses
9m: 44,4% - comprou em 4 dos últimos 9 meses
```

Calcular a quantidade de meses apenas para apresentação:

```text
Math.round(frequencia * tamanhoDaJanela)
```

Deixar claro que frequência representa a proporção de meses com ao menos um pedido.

### 13.2 Receita média

Mostrar:

```text
3m: média mensal de ...
6m: média mensal de ...
9m: média mensal de ...
```

Explicar que meses sem compra entram como zero na média Gold.

### 13.3 Desconto médio

Mostrar os três percentuais e explicar que se trata do desconto efetivo ponderado pelo valor bruto, não da média simples dos descontos dos itens.

Não tratar aumento de desconto como automaticamente bom. O estado indica apenas direção.

### 13.4 Média de itens variados

Usar os campos:

```text
quantidade_produtos_distintos_media_3m
quantidade_produtos_distintos_media_6m
quantidade_produtos_distintos_media_9m
```

Explicar como média mensal de produtos distintos comprados.

### 13.5 Média de quantidade

Usar os campos:

```text
quantidade_itens_media_3m
quantidade_itens_media_6m
quantidade_itens_media_9m
```

Explicar como média mensal de unidades compradas. Se estiver `Diminuiu` e tiver participado da regra de `Ruim`, destacar isso explicitamente.

### 13.6 Relação com o Status

Gerar uma justificativa final determinística, baseada nas flags, por exemplo:

```text
“O Status é Ruim porque receita média e quantidade média diminuíram.
A frequência permaneceu normal. Desconto e variedade são exibidos como
contexto e não alteraram a classificação geral.”
```

Não inventar justificativas com base apenas nos valores absolutos. Usar as flags calculadas e as regras da seção 5.

## 14. Estado vazio e atualização

Se nenhum cliente estiver selecionado ou os filtros não retornarem linhas, o painel deve mostrar:

```text
Selecione um cliente para visualizar o histórico e a justificativa do Status.
```

Ao trocar o mês na linha do tempo:

1. carregar/enriquecer clientes do novo retrato;
2. recalcular o Status geral;
3. atualizar a tabela e sua contagem;
4. escolher uma linha válida;
5. consultar os nove meses de volume do cliente selecionado;
6. redesenhar gráficos e explicações.

Evitar condições de corrida visuais. Como as consultas ao banco em memória são síncronas, manter a atualização em uma sequência previsível.

## 15. Responsividade

Desktop:

- linha do tempo em largura total;
- tabela à esquerda;
- painel explicativo à direita;
- gráficos lado a lado dentro do painel;
- tabela com cabeçalho fixo e rolagem própria.

Tablet:

- permitir reduzir a proporção das colunas;
- empilhar os gráficos se eles ficarem estreitos demais.

Mobile:

- filtros e tabela primeiro;
- painel explicativo depois;
- gráficos empilhados;
- tabela pode rolar horizontalmente dentro do card, sem gerar overflow na página;
- nenhuma informação essencial depende de hover;
- linha selecionada e tags continuam legíveis.

## 16. Segurança e limpeza de código

- Usar `"use strict"`.
- Usar statements preparados para parâmetros.
- Liberar statements em `finally`.
- Inserir dados do SQLite com `textContent`, nunca com `innerHTML`.
- Manter nomes prefixados com `metricas` para evitar colisões globais.
- Não criar um segundo carregamento de `data.sqlite`.
- Remover funções, variáveis, seletores e CSS mortos.
- Preservar código compartilhado por outras telas.
- Não duplicar a lógica de tendência individual.
- Centralizar a nova regra de Status em uma função testável.
- Expor a função de Status em `window` somente se necessário para testes, usando nome prefixado.

## 17. Testes obrigatórios das regras

### 17.1 Nova regra de tendência individual

Testar `classificarTendencia` e conferir não apenas o estado, mas também `comparacao36`, `comparacao39` e `indiceTendencia`.

Casos de diferença direta, usados por frequência e desconto:

```text
(0,667; 1,000; 1,000)
3×6 = -0,333; 3×9 = -0,333; média = -0,333 -> Diminuiu

(1,000; 0,667; 0,556)
3×6 = +0,333; 3×9 = +0,444; média = +0,3885 -> Aumentou

(0,800; 1,000; 1,000)
3×6 = -0,200; 3×9 = -0,200; média = -0,200 -> Normal

(0; 0; 0)
média = 0 -> Normal
```

Casos de variação relativa, usados por receita, variedade e quantidade:

```text
(80; 100; 120)
3×6 = -20%; 3×9 = -33,33%; média = -26,67% -> Diminuiu

(121; 100; 100)
3×6 = +21%; 3×9 = +21%; média = +21% -> Aumentou

(120; 100; 100)
3×6 = +20%; 3×9 = +20%; média = +20% -> Normal

(0; 0; 0)
média = 0 -> Normal
```

Adicionar casos com uma comparação positiva e outra negativa para provar que a classificação depende da média, não da exigência de os dois sinais serem iguais.

Confirmar que:

- nenhuma parte da classificação usa `6m × 9m`;
- o limite é `20%`, não `10%`;
- exatamente `±20%` permanece `Normal`;
- não ocorre `NaN` com zero;
- o exemplo `66,7% / 100% / 100%` resulta em `Diminuiu`.

### 17.2 Regra de Status geral

Testar a função `classificarStatusCliente` com todas estas combinações:

```text
F=diminuiu, R=diminuiu, Q=normal     -> Ruim
F=diminuiu, R=normal, Q=diminuiu     -> Ruim
F=normal, R=diminuiu, Q=diminuiu     -> Ruim
F=diminuiu, R=diminuiu, Q=diminuiu   -> Ruim

F=diminuiu, R=normal, Q=normal       -> Atenção
F=aumentou, R=diminuiu, Q=normal     -> Atenção
F=normal, R=diminuiu, Q=aumentou     -> Atenção

F=aumentou, R=aumentou, Q=normal     -> Bom
F=aumentou, R=aumentou, Q=diminuiu   -> Bom

F=normal, R=normal, Q=normal         -> Normal
F=normal, R=aumentou, Q=normal       -> Normal
F=aumentou, R=normal, Q=aumentou     -> Normal
```

Também confirmar que mudanças em desconto ou variedade, isoladamente, não alteram o Status geral.

Criar um teste integrado entre as duas regras:

```text
frequência: 3m=66,7%, 6m=100%, 9m=100% -> Diminuiu
receita: flag Normal
quantidade: flag Normal
Status geral esperado: Atenção
```

E outro:

```text
frequência: 3m=66,7%, 6m=100%, 9m=100% -> Diminuiu
receita: flag Normal
quantidade: flag Diminuiu
Status geral esperado: Ruim
```

## 18. Testes de integração e interface

Servir `viewer/` por HTTP e verificar:

1. A tela abre no último mês disponível.
2. A linha do tempo continua funcional por mouse e teclado.
3. A tabela possui somente `Cliente`, `Empresa` e `Status`.
4. As quatro cores e rótulos de Status aparecem corretamente.
5. Os filtros disponíveis são somente Cliente, Empresa e Status.
6. O botão de limpar filtros funciona.
7. Selecionar uma linha atualiza o painel sem tooltip.
8. Não aparece card ao passar o mouse pelas tags.
9. O elemento `#metricas-tooltip` deixou de existir.
10. Não há listeners ou CSS mortos do tooltip antigo.
11. Os gráficos exibem os nove meses até o mês selecionado.
12. Meses sem linha em `historico_cliente_volume` aparecem como zero.
13. Frequência usa `quantidade_pedidos` e receita usa `receita_total`.
14. A seção explicativa mostra as cinco métricas com valores 3m, 6m e 9m.
15. Cada métrica mostra `3m × 6m`, `3m × 9m` e a média das comparações.
16. O caso `66,7% / 100% / 100%` aparece como frequência `Diminuiu`.
17. Essa nova flag participa corretamente do Status geral do cliente.
18. A justificativa corresponde às flags e ao Status mostrado.
19. Trocar o mês atualiza tabela, seleção, gráficos e justificativa.
20. Filtrar a linha selecionada escolhe outra linha válida ou mostra estado vazio.
21. O layout funciona em desktop, tablet e mobile.
22. Não há erros no console.
23. Vendas, Visualização e Relacionamento de Tabelas continuam funcionando.

## 19. Critérios de aceite

A tarefa estará concluída quando:

- as cinco colunas de tendência forem substituídas por `Status`;
- a tendência individual comparar `3m × 6m` e `3m × 9m`;
- a média das duas comparações usar tolerância estrita de 20%;
- o caso `66,7% / 100% / 100%` resultar em frequência `Diminuiu`;
- as novas flags individuais alimentarem o Status geral;
- cada cliente receber exatamente um dos quatro Status definidos;
- a precedência `Ruim > Atenção > Bom > Normal` estiver implementada;
- somente Cliente, Empresa e Status puderem filtrar a lista;
- o tooltip antigo das métricas tiver sido completamente removido;
- a área abaixo da linha do tempo estiver dividida entre painel explicativo e tabela;
- a tabela selecionar o cliente exibido no painel;
- os gráficos usarem dados mensais reais de `historico_cliente_volume`;
- os gráficos cobrirem nove meses e preencherem meses ausentes com zero;
- as cinco métricas aparecerem na justificativa permanente;
- a justificativa mostrar as duas comparações, a média e a flag de cada métrica;
- a explicação distinguir métricas principais, agravante e contexto;
- nenhuma causalidade ou previsão de churn for inventada;
- a interface permanecer acessível e responsiva;
- banco, pipeline e outras telas não forem alterados.

## 20. Entrega final

Ao finalizar, informar:

- arquivos alterados;
- código exato da regra de Status;
- precedência aplicada;
- filtros removidos e filtro adicionado;
- código de tooltip removido;
- consulta feita em `historico_cliente_volume`;
- como os nove meses e os zeros foram montados;
- como as cinco métricas são explicadas;
- comportamento de seleção e responsividade;
- testes executados e resultados;
- confirmação de que `viewer/data.sqlite` e a pipeline não foram modificados.
