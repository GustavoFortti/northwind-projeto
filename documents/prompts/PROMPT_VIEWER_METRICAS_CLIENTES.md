# Prompt - Tela “Métricas de clientes” no Viewer

Implemente no Viewer uma nova tela chamada **Métricas de clientes**, consumindo exclusivamente a tabela SQLite:

```text
viewer/data.sqlite
tabela: historico_cliente_metricas
```

A tela deve permitir selecionar um mês histórico em uma linha temporal e mostrar, para cada cliente, se cada métrica **aumentou**, permaneceu **normal** ou **diminuiu**, comparando diretamente as janelas acumuladas de 3, 6 e 9 meses com tolerância de 10%.

## 1. Escopo

Alterar somente o frontend do Viewer:

```text
viewer/index.html
viewer/styles.css
viewer/bi.js
```

Criar um arquivo JavaScript específico para a nova tela:

```text
viewer/metricas-clientes.js
```

Se durante a implementação for realmente necessário ajustar outro arquivo do Viewer, justificar a alteração no relatório final.

Não alterar:

- jobs da pipeline;
- arquivos Parquet;
- schema ou conteúdo de `viewer/data.sqlite`;
- cálculos da camada Gold;
- telas existentes, além da adaptação mínima da navegação e da inicialização compartilhada do banco;
- dependências do projeto.

Não adicionar bibliotecas ou frameworks externos. Usar apenas HTML, CSS e JavaScript já compatíveis com o Viewer atual e com `sql.js`.

## 2. Entender a implementação existente antes de alterar

Antes de implementar:

1. Ler `viewer/index.html`, `viewer/styles.css` e `viewer/bi.js`.
2. Entender como `bi.js` carrega `viewer/data.sqlite` uma única vez.
3. Seguir o padrão usado para inicializar `grafo.js` e `vendas.js`, compartilhando a mesma instância do banco.
4. Preservar o tema escuro, a barra lateral, a responsividade e os componentes visuais existentes.
5. Não duplicar o download ou a abertura de `data.sqlite` dentro de `metricas-clientes.js`.

## 3. Nova opção de navegação

Adicionar na seção **Principal** da barra lateral, logo após **Recomendação de produtos**, a opção:

```text
Métricas de clientes
```

Usar:

```html
data-page="metricas-clientes"
```

Criar a página correspondente:

```html
id="page-metricas-clientes"
```

Atualizar a navegação existente para garantir que somente uma destas páginas fique visível por vez:

```text
page-vendas
page-metricas-clientes
page-bi
page-tabelas
```

A página de recomendação de produtos deve continuar sendo a página inicial.

## 4. Fonte dos meses da linha temporal

Não fixar meses no HTML ou no JavaScript.

Carregar os meses disponíveis diretamente do SQLite:

```sql
SELECT ano_mes
FROM historico_cliente_metricas
GROUP BY ano_mes
ORDER BY ano_mes;
```

`ano_mes` está armazenado no formato:

```text
YYYY-MM
```

Apresentar ao usuário no formato:

```text
MM/AA
```

Exemplos:

```text
1997-04 -> 04/97
1998-01 -> 01/98
```

Ao abrir a tela pela primeira vez, selecionar automaticamente o último mês disponível no banco. Não assumir no código qual é esse mês.

## 5. Linha temporal

No topo da página, abaixo do título, criar uma linha temporal horizontal inspirada no desenho de referência fornecido.

Ela deve ter:

- uma linha horizontal contínua;
- um marcador para cada `ano_mes` existente no SQLite;
- marcadores em ordem cronológica;
- destaque visual claro para o mês selecionado, usando um círculo maior;
- rótulo `MM/AA` do mês selecionado;
- indicação dos meses vizinhos quando houver espaço;
- rolagem horizontal em telas estreitas, sem comprimir os marcadores até ficarem ilegíveis;
- clique/toque em qualquer marcador para selecionar o mês;
- foco visível e navegação por teclado.

Cada marcador deve ser um elemento interativo acessível, preferencialmente um `<button>`, com texto acessível como:

```text
Selecionar janeiro de 1998
```

Suportar:

- `ArrowLeft`: selecionar o mês anterior;
- `ArrowRight`: selecionar o próximo mês;
- `Home`: selecionar o primeiro mês;
- `End`: selecionar o último mês.

O marcador selecionado deve usar `aria-current="date"`.

Quando o mês mudar, atualizar a tabela imediatamente, sem recarregar a página nem buscar novamente o arquivo SQLite.

## 6. Consulta dos clientes do mês selecionado

Para o mês selecionado, ler uma linha por cliente da tabela:

```sql
SELECT
    cliente_id,
    nome_empresa,
    frequencia_compra_3m,
    frequencia_compra_6m,
    frequencia_compra_9m,
    receita_media_3m,
    receita_media_6m,
    receita_media_9m,
    desconto_medio_3m,
    desconto_medio_6m,
    desconto_medio_9m,
    quantidade_produtos_distintos_media_3m,
    quantidade_produtos_distintos_media_6m,
    quantidade_produtos_distintos_media_9m,
    quantidade_itens_media_3m,
    quantidade_itens_media_6m,
    quantidade_itens_media_9m
FROM historico_cliente_metricas
WHERE ano_mes = :ano_mes
ORDER BY nome_empresa, cliente_id;
```

Usar statement preparado com parâmetro. Finalizar/liberar o statement depois da leitura.

Não concatenar valores externos em SQL.

## 7. Significado correto das janelas

As três janelas terminam no mês selecionado e são acumuladas:

```text
3m = meses 1 a 3
6m = meses 1 a 6
9m = meses 1 a 9
```

Exemplo para o mês selecionado `1998-01`:

```text
3m = 1997-11 a 1998-01
6m = 1997-08 a 1998-01
9m = 1997-05 a 1998-01
```

Comparar diretamente os valores armazenados nas colunas `3m`, `6m` e `9m`.

Não decompor ou converter as janelas em blocos independentes:

```text
Não calcular meses 4 a 6.
Não calcular meses 7 a 9.
Não usar 2 × média_6m − média_3m.
Não usar 3 × média_9m − 2 × média_6m.
```

## 8. Regra de classificação com tolerância de 10%

Criar uma única função pura e reutilizável para classificar todas as métricas, por exemplo:

```javascript
classificarTendencia(valor3m, valor6m, valor9m)
```

A tolerância deve ser uma constante centralizada:

```javascript
const TOLERANCIA_TENDENCIA = 0.10;
```

Calcular duas variações relativas:

```text
variacao_3_6 = (valor3m - valor6m) / |valor6m|
variacao_6_9 = (valor6m - valor9m) / |valor9m|
```

Classificar como:

```text
Aumentou
    quando variacao_3_6 > 10%
    E variacao_6_9 > 10%

Diminuiu
    quando variacao_3_6 < -10%
    E variacao_6_9 < -10%

Normal
    em todos os demais casos
```

Portanto, conceitualmente:

```text
Aumentou:  3m é significativamente maior que 6m,
           e 6m é significativamente maior que 9m.

Diminuiu:  3m é significativamente menor que 6m,
           e 6m é significativamente menor que 9m.

Normal:    as diferenças estão dentro da tolerância
           ou as duas comparações apontam sentidos diferentes.
```

Diferença exatamente igual a `+10%` ou `-10%` ainda está dentro da tolerância e deve resultar em `Normal`. Somente valores que ultrapassarem 10% são significativos.

Usar uma pequena margem numérica, como `Number.EPSILON` ou constante equivalente, para uma diferença exatamente no limite não mudar de classe por ruído de ponto flutuante.

### Tratamento obrigatório de zero

Os valores das métricas são não negativos. A função de variação deve tratar o denominador zero explicitamente:

```text
base = 0 e atual = 0 -> variação = 0
base = 0 e atual > 0 -> variação = +Infinity
base > 0             -> cálculo percentual normal
```

Nunca produzir `NaN`, erro de divisão ou texto inválido na interface.

Se os três valores forem zero, o resultado é:

```text
Normal
```

Se uma comparação indicar aumento e a outra indicar diminuição ou estabilidade, o resultado também é:

```text
Normal
```

### Exemplos obrigatórios

```text
3m = 125, 6m = 110, 9m = 95
3m supera 6m em mais de 10%
6m supera 9m em mais de 10%
resultado: Aumentou
```

```text
3m = 80, 6m = 90, 9m = 105
3m está mais de 10% abaixo de 6m
6m está mais de 10% abaixo de 9m
resultado: Diminuiu
```

```text
3m = 105, 6m = 100, 9m = 96
as diferenças não ultrapassam 10%
resultado: Normal
```

```text
3m = 120, 6m = 100, 9m = 110
as comparações apontam sentidos diferentes
resultado: Normal
```

## 9. Métricas exibidas

Montar uma tabela com estas colunas, nesta ordem:

```text
Cliente
Empresa
Frequência de compra
Média de receita
Média de desconto
Média de itens variados
Média de quantidade
```

Mapeamento:

```text
Cliente
    cliente_id

Empresa
    nome_empresa

Frequência de compra
    frequencia_compra_3m
    frequencia_compra_6m
    frequencia_compra_9m

Média de receita
    receita_media_3m
    receita_media_6m
    receita_media_9m

Média de desconto
    desconto_medio_3m
    desconto_medio_6m
    desconto_medio_9m

Média de itens variados
    quantidade_produtos_distintos_media_3m
    quantidade_produtos_distintos_media_6m
    quantidade_produtos_distintos_media_9m

Média de quantidade
    quantidade_itens_media_3m
    quantidade_itens_media_6m
    quantidade_itens_media_9m
```

Não exibir nesta tela:

- receita sem desconto;
- quantidade média de pedidos;
- campos de outras tabelas;
- scores combinados;
- churn, risco ou previsão.

## 10. Conteúdo das células de tendência

Cada célula de métrica deve mostrar claramente um destes estados:

```text
↑ Aumentou
• Normal
↓ Diminuiu
```

Usar ícone e texto; não comunicar o estado somente por cor.

O estado descreve apenas a direção matemática. Não presumir que aumentar seja sempre bom ou diminuir seja sempre ruim. Isso é especialmente importante para `Média de desconto`.

Adicionar `title`, tooltip acessível ou detalhe equivalente contendo:

- valor de 3 meses;
- valor de 6 meses;
- valor de 9 meses;
- resultado da classificação.

Formatar os valores no padrão `pt-BR`:

- frequência de compra: percentual;
- média de desconto: percentual;
- receita média: duas casas decimais;
- itens variados: duas casas decimais;
- quantidade: duas casas decimais.

Não substituir os valores originais da tabela nem recalcular as métricas Gold. A tela calcula somente o estado visual.

## 11. Estrutura visual

Seguir o desenho de referência e adaptar ao padrão visual já existente no Viewer:

```text
Título: Métricas de clientes

Linha temporal centralizada
    12/97   [01/98 selecionado]   02/98

Tabela de clientes
    Cliente | Empresa | Frequência | Receita | Desconto | Itens variados | Quantidade
```

Requisitos:

- usar o tema escuro e as variáveis CSS já existentes;
- manter largura e espaçamento coerentes com `.bi-wrap`, `.chart-card` e outras páginas;
- colocar a linha temporal em um card próprio;
- colocar a tabela em outro card;
- mostrar o mês selecionado e a quantidade de clientes acima da tabela;
- cabeçalho da tabela fixo durante a rolagem vertical interna, quando aplicável;
- alinhar colunas de status de maneira consistente;
- preservar `cliente_id` sem truncamento indevido;
- permitir quebra ou truncamento controlado do nome da empresa;
- permitir rolagem horizontal da tabela em telas estreitas;
- manter a página utilizável em desktop e mobile;
- não alterar globalmente o comportamento das telas existentes.

Os estados precisam ter contraste suficiente no fundo escuro. Usar classes próprias, por exemplo:

```text
metricas-status--aumentou
metricas-status--normal
metricas-status--diminuiu
```

## 12. Estado vazio e erros

Se a tabela `historico_cliente_metricas` não existir, mostrar uma mensagem clara dentro da página sem quebrar as outras telas.

Se não existirem meses:

```text
Nenhum histórico de métricas de clientes disponível.
```

Se o mês existir, mas não houver clientes:

```text
Nenhum cliente encontrado para MM/AA.
```

Integrar o tratamento de erro ao carregamento atual do Viewer. Criar, se necessário, funções globais no mesmo padrão das páginas existentes:

```javascript
window.iniciarMetricasClientes = function iniciarMetricasClientes(db) { ... }
window.mostrarErroMetricasClientes = function mostrarErroMetricasClientes(msg) { ... }
```

Em `bi.js`, depois de carregar o banco, inicializar a nova página com a mesma instância:

```javascript
if (window.iniciarMetricasClientes) window.iniciarMetricasClientes(db);
```

No fluxo de erro geral, encaminhar a mensagem para a nova tela sem remover o tratamento já existente das outras páginas.

## 13. Segurança e qualidade do JavaScript

- Usar `"use strict"`.
- Não inserir valores vindos do SQLite com `innerHTML`.
- Construir conteúdo com `textContent` e elementos DOM.
- Liberar statements preparados após o uso, inclusive em caso de erro.
- Manter estado da tela encapsulado em `metricas-clientes.js`.
- Evitar variáveis globais genéricas que possam colidir com `bi.js`, `grafo.js` ou `vendas.js`.
- Não executar uma nova consulta completa a cada renderização sem necessidade.
- Não recarregar `data.sqlite` ao trocar de mês.
- Comentar as regras de negócio, principalmente a tolerância e a comparação das três janelas.
- Não alterar as funções de cálculo existentes da pipeline.

## 14. Testes obrigatórios

### Testes da função de classificação

Validar pelo menos:

```text
(125, 110, 95) -> Aumentou
(80, 90, 105) -> Diminuiu
(105, 100, 96) -> Normal
(120, 100, 110) -> Normal
(0, 0, 0) -> Normal
```

Adicionar também casos para:

- exatamente `+10%`;
- exatamente `-10%`;
- denominador zero;
- valores decimais de frequência e desconto;
- uma comparação significativa e a outra dentro da tolerância.

### Testes de dados

Com o `data.sqlite` atual, confirmar:

- os meses são obtidos por `SELECT`, não por lista fixa;
- a linha temporal começa em `04/97` e termina em `04/98`;
- existem 13 meses disponíveis;
- `01/98` retorna 89 clientes;
- trocar o mês altera os clientes e estados exibidos;
- o último mês disponível é selecionado inicialmente;
- o filtro SQL usa somente o `ano_mes` selecionado.

Esses números servem para validar a base atual, mas não devem ser fixados no código da tela.

### Testes de interface

Servir a pasta por HTTP, conforme o projeto já exige, por exemplo:

```bash
cd viewer
python3 -m http.server 8080
```

Verificar:

- navegação entre todas as páginas;
- seleção de mês por mouse;
- seleção de mês por teclado;
- destaque do mês ativo;
- atualização da tabela sem reload;
- tooltip ou detalhe com os valores 3m, 6m e 9m;
- rolagem da tabela;
- layout em largura desktop e mobile;
- ausência de erros no console;
- telas anteriores continuam funcionando.

## 15. Critérios de aceite

A tarefa estará concluída quando:

1. **Métricas de clientes** aparecer na navegação principal.
2. A tela carregar os meses de `historico_cliente_metricas` dinamicamente.
3. O último mês disponível iniciar selecionado.
4. A troca de mês consultar e renderizar apenas o retrato daquele `ano_mes`.
5. Cada uma das cinco métricas receber um estado calculado com as janelas acumuladas `3m`, `6m` e `9m`.
6. A tolerância for exatamente 10%, sendo o limite inclusivo em `Normal`.
7. `Aumentou` exigir as duas comparações acima de 10%.
8. `Diminuiu` exigir as duas comparações abaixo de -10%.
9. Casos mistos, zeros e diferenças dentro do limite forem tratados sem `NaN` e classificados conforme especificado.
10. A interface seguir o tema e a responsividade do Viewer.
11. Nenhum dado do SQLite ou da pipeline for alterado.
12. As telas existentes continuarem funcionais.

## 16. Entrega final

Ao finalizar, informar:

- arquivos criados e alterados;
- consulta usada para carregar os meses;
- consulta usada para carregar os clientes;
- implementação exata da regra de 10%;
- tratamento de zeros;
- comportamento responsivo e acessível da linha temporal;
- testes executados e resultados;
- confirmação de que `viewer/data.sqlite` e a pipeline não foram modificados.
