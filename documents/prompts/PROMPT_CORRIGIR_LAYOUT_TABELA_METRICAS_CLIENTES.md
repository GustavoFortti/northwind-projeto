# Prompt - Corrigir tabela, alturas e rolagem da tela Métricas de clientes

Faça uma correção visual e de dados pontual na tela existente **Métricas de clientes** do Viewer.

A tela mestre–detalhe, o Status geral, os gráficos e os cálculos das cinco métricas já estão implementados. Não refazer a funcionalidade e não alterar nenhuma regra de negócio nesta tarefa.

## 1. Problemas atuais

Corrigir os seguintes problemas observados na tabela de clientes:

1. A coluna `Status` fica muito distante, exigindo rolagem horizontal para aparecer.
2. A coluna `Empresa` ocupa mais largura do que precisa.
3. A coluna `Cliente` mostra o código `cliente_id`, mas deve mostrar o nome da pessoa de contato.
4. Os textos das três colunas precisam aparecer por completo.
5. Todas as linhas devem ter a mesma altura, mesmo quando algum texto quebrar em duas linhas.
6. O card de clientes e o card de detalhes devem ter exatamente a mesma altura no desktop.
7. Os dois cards devem possuir rolagem vertical própria e independente.
8. Existe um pequeno quadrado branco no canto inferior direito da área rolável da tabela, no encontro das barras de rolagem. Ele não deve aparecer.

## 2. Ler o código atual antes de alterar

Ler integralmente antes da implementação:

```text
viewer/index.html
viewer/metricas-clientes.js
viewer/styles.css
```

Inspecionar especialmente:

```text
carregarClientesDoMes
metricasFiltrarLinhas
metricasRenderizarTabela
metricasRenderizarPainel
.metricas-grid
.metricas-card-tabela
.metricas-card-painel
.metricas-tabela-scroll
.metricas-table
.metricas-td-cliente
.metricas-td-empresa
.metricas-td-status
.metricas-painel
```

Preservar:

- linha do tempo;
- regra individual de tendência com comparações `3m × 6m` e `3m × 9m`;
- tolerância de 20%;
- regra do Status geral;
- seleção de cliente;
- filtros por cliente, empresa e Status;
- gráficos de frequência e receita;
- painel “Por que este Status?”;
- acessibilidade por teclado;
- carregamento único de `viewer/data.sqlite`.

## 3. Escopo

Alterar somente:

```text
viewer/index.html
viewer/metricas-clientes.js
viewer/styles.css
```

Alterar apenas os arquivos realmente necessários.

Não alterar:

- pipeline;
- Parquets;
- `viewer/data.sqlite`;
- schema das tabelas;
- regras de cálculo;
- filtros ou telas não relacionadas;
- dependências do projeto.

## 4. A coluna Cliente deve mostrar o nome do cliente

A tabela `historico_cliente_metricas` contém `cliente_id` e `nome_empresa`, mas não contém o nome da pessoa de contato.

Buscar o nome na tabela:

```text
clientes.nome_contato
```

Relacionamento:

```text
historico_cliente_metricas.cliente_id = clientes.cliente_id
```

Atualizar a consulta de `carregarClientesDoMes` para fazer `LEFT JOIN` com `clientes`, mantendo todos os clientes históricos mesmo se algum cadastro não for encontrado.

Usar consulta equivalente a:

```sql
SELECT
    h.cliente_id,
    COALESCE(NULLIF(TRIM(c.nome_contato), ''), h.cliente_id) AS nome_cliente,
    h.nome_empresa,
    h.frequencia_compra_3m,
    h.frequencia_compra_6m,
    h.frequencia_compra_9m,
    h.receita_media_3m,
    h.receita_media_6m,
    h.receita_media_9m,
    h.desconto_medio_3m,
    h.desconto_medio_6m,
    h.desconto_medio_9m,
    h.quantidade_produtos_distintos_media_3m,
    h.quantidade_produtos_distintos_media_6m,
    h.quantidade_produtos_distintos_media_9m,
    h.quantidade_itens_media_3m,
    h.quantidade_itens_media_6m,
    h.quantidade_itens_media_9m
FROM historico_cliente_metricas AS h
LEFT JOIN clientes AS c
       ON c.cliente_id = h.cliente_id
WHERE h.ano_mes = :ano_mes
ORDER BY nome_cliente, h.nome_empresa, h.cliente_id;
```

Manter `cliente_id` no objeto e continuar usando-o como chave interna para:

- seleção da linha;
- `dataset`;
- cache;
- consulta de volume;
- identificação estável entre meses.

Não usar `nome_cliente` como chave.

## 5. Cabeçalhos e conteúdo da tabela

A tabela deve manter três colunas, nesta ordem:

```text
Nome do cliente
Empresa
Status
```

Conteúdo:

```text
Nome do cliente -> nome_cliente, vindo de clientes.nome_contato
Empresa         -> nome_empresa
Status          -> tag Bom, Normal, Atenção ou Ruim
```

Exemplo:

```text
Maria Anders | Alfreds Futterkiste | Normal
Ana Trujillo | Ana Trujillo Emparedados y helados | Atenção
```

O código `ALFKI`, `ANATR` etc. não deve mais ser o texto principal da primeira coluna. Ele pode continuar disponível internamente e, se necessário para acessibilidade, no `aria-label` da linha.

Atualizar também o filtro:

```text
label: Nome do cliente
placeholder: Buscar cliente...
```

O filtro de cliente deve pesquisar `nome_cliente` sem acento e sem diferenciar maiúsculas/minúsculas.

Opcionalmente, ele também pode encontrar pelo `cliente_id`, sem mostrar o código na coluna. Isso preserva a possibilidade de localizar rapidamente um cadastro pelo código.

Atualizar o cabeçalho do painel de detalhes para priorizar o nome:

```text
Maria Anders - Alfreds Futterkiste
```

O código pode aparecer em texto secundário discreto, por exemplo:

```text
Cliente ALFKI · Retrato de 04/98
```

Não repetir o código como se fosse o nome da pessoa.

## 6. Distribuição das três colunas

O problema atual é provocado principalmente por:

```css
.metricas-table { min-width: 760px; }
```

Essa largura mínima força rolagem horizontal dentro de um card com aproximadamente 45% da tela e empurra `Status` para a direita.

Na tabela mestre, remover a largura mínima fixa de 760 px e fazer as três colunas caberem na largura real do card.

Usar `table-layout: fixed` e definir larguras explícitas com `<colgroup>` ou seletores `nth-child`.

Distribuição inicial recomendada:

```text
Nome do cliente: 34%
Empresa:         40%
Status:          26%
```

Pode ajustar alguns pontos percentuais após testar, desde que:

- `Status` fique totalmente visível sem rolagem horizontal no desktop;
- o espaço de `Empresa` seja menor que na implementação atual;
- os três cabeçalhos apareçam por completo;
- as tags `Atenção` e `Normal` apareçam por completo;
- nome e empresa não sejam cortados com reticências.

Não usar novamente um `min-width` maior que o próprio card na tabela desktop.

## 7. Textos completos e quebra controlada

Remover da tabela mestre qualquer combinação que esconda conteúdo:

```css
overflow: hidden;
text-overflow: ellipsis;
white-space: nowrap;
```

Permitir quebra controlada em nome e empresa:

```css
white-space: normal;
overflow-wrap: anywhere;
word-break: normal;
```

A coluna Status deve manter a tag inteira em uma linha:

```css
white-space: nowrap;
```

Testar pelo menos os nomes mais longos existentes:

```text
Ana Trujillo Emparedados y helados
FISSA Fabrica Inter. Salchichas S.A.
Trail's Head Gourmet Provisioners
```

Nenhum deles pode ficar truncado.

## 8. Todas as linhas com a mesma altura

Definir uma altura uniforme para as linhas da tabela, suficiente para duas linhas de texto em nome ou empresa.

Usar uma variável ou valor centralizado, por exemplo:

```css
--metricas-altura-linha: 58px;
```

ou outro valor entre aproximadamente `56px` e `68px`, escolhido após teste visual.

Aplicar a mesma altura a todas as linhas:

```css
.metricas-table--linhas tbody tr {
  height: var(--metricas-altura-linha);
}

.metricas-table--linhas td {
  height: var(--metricas-altura-linha);
  vertical-align: middle;
  line-height: 1.3;
}
```

A altura escolhida deve comportar integralmente o maior nome/empresa atual em no máximo duas linhas. Não resolver igualdade de altura escondendo, cortando ou aplicando reticências ao texto.

Se o teste demonstrar que 58 px não basta, aumentar a altura de todas as linhas igualmente.

O cabeçalho também deve possuir altura consistente e os três títulos completos.

## 9. Cards com a mesma altura

No desktop, os dois blocos devem ter exatamente a mesma altura externa:

```text
card Clientes = card Status do cliente
```

Não deixar o card de detalhes crescer além do card de clientes, como ocorre atualmente.

Usar o grid como controlador da altura. Uma abordagem aceitável:

```css
.metricas-grid {
  align-items: stretch;
  height: clamp(560px, calc(100vh - 300px), 760px);
}

.metricas-card-tabela,
.metricas-card-painel {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
```

Os valores exatos podem ser ajustados ao layout real. O importante é:

- os topos ficarem alinhados;
- as bases ficarem alinhadas;
- nenhuma altura depender da quantidade de clientes ou do tamanho da explicação;
- o conjunto continuar utilizável em resoluções comuns de notebook e desktop.

Não definir uma altura rígida que faça a linha do tempo ou o cabeçalho sair da tela sem possibilidade de rolagem da página.

## 10. Rolagem independente nos dois cards

Os dois blocos devem possuir rolagem vertical própria.

### Card de clientes

Manter cabeçalho e filtros visíveis. Somente a área da tabela deve rolar:

```css
.metricas-card-tabela {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.metricas-tabela-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}
```

O cabeçalho da tabela deve permanecer fixo no topo da própria área rolável.

### Card de detalhes

O painel inteiro deve rolar verticalmente dentro do card:

```css
.metricas-card-painel {
  min-height: 0;
}

.metricas-painel {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
}
```

Ao selecionar outro cliente, levar o painel de detalhes ao topo, para que o cabeçalho e os gráficos do novo cliente fiquem visíveis:

```javascript
painel.scrollTop = 0;
```

Não sincronizar as duas rolagens. Cada card deve rolar de forma independente.

## 11. Remover o quadrado branco no canto da rolagem

O quadrado branco aparece no encontro da barra vertical com a horizontal da `.metricas-tabela-scroll`.

A correção principal deve ser eliminar a necessidade de rolagem horizontal no desktop:

- tabela com `width: 100%`;
- `min-width: 0`;
- `table-layout: fixed`;
- colunas proporcionais;
- `overflow-x: hidden` na área rolável.

Também estilizar explicitamente a trilha e o canto da barra para manter o tema escuro:

```css
.metricas-tabela-scroll,
.metricas-painel {
  scrollbar-color: var(--border) var(--card);
}

.metricas-tabela-scroll::-webkit-scrollbar-track,
.metricas-painel::-webkit-scrollbar-track,
.metricas-tabela-scroll::-webkit-scrollbar-corner,
.metricas-painel::-webkit-scrollbar-corner {
  background: var(--card);
}
```

Se o fundo correto do card for outra variável já usada pelo Viewer, reutilizá-la. Não usar branco, transparente que revele branco, nem uma cor fixa incompatível com o tema.

Verificar o canto inferior direito com:

- scroll no topo;
- scroll no meio;
- scroll no fim;
- zoom do navegador em 100% e 125%;
- Chromium/Chrome.

Não apenas sobrepor um elemento para esconder o quadrado. Corrigir overflow e `scrollbar-corner` corretamente.

## 12. Responsividade

No desktop, a tabela não deve ter rolagem horizontal.

Em telas abaixo do breakpoint mestre–detalhe:

- manter tabela primeiro e detalhes depois;
- os dois cards podem ser empilhados;
- manter alturas equivalentes quando visualmente adequado;
- cada card continua com sua rolagem vertical;
- reduzir padding antes de reduzir a legibilidade do texto;
- preservar as três colunas enquanto houver largura suficiente.

Em telas muito estreitas, se três colunas lado a lado deixarem o conteúdo ilegível, permitir uma apresentação responsiva própria para a linha, mas sem ocultar nome, empresa ou Status. Não voltar a usar reticências como solução principal.

## 13. Segurança e qualidade

- Continuar usando statements preparados.
- Liberar statements em `finally`.
- Inserir dados com `textContent`.
- Não usar `innerHTML` com valores do SQLite.
- Não duplicar o carregamento do banco.
- Preservar `cliente_id` como chave estável.
- Remover CSS antigo que entre em conflito com a nova distribuição.
- Não deixar seletores mortos.
- Não alterar cálculos ou Status para resolver problema visual.

## 14. Testes obrigatórios

### Dados

Confirmar no SQLite:

```text
ALFKI -> Maria Anders -> Alfreds Futterkiste
ANATR -> Ana Trujillo -> Ana Trujillo Emparedados y helados
ANTON -> Antonio Moreno -> Antonio Moreno Taquería
```

Confirmar que:

- nenhum cliente histórico desaparece por causa do join;
- fallback para `cliente_id` funciona se `nome_contato` for nulo ou vazio;
- filtro por nome funciona sem acento e sem diferenciar maiúsculas/minúsculas;
- seleção e gráficos continuam usando o `cliente_id` correto.

### Layout desktop

Testar pelo menos em:

```text
1440 × 900
1280 × 720
```

Verificar:

1. `Nome do cliente`, `Empresa` e `Status` aparecem por completo.
2. Status está visível sem mover uma barra horizontal.
3. Empresa não empurra Status para fora da área visível.
4. Nenhum nome ou empresa usa reticências.
5. Textos longos quebram em até duas linhas.
6. Todas as linhas possuem a mesma altura.
7. As tags `Normal`, `Atenção`, `Bom` e `Ruim` ficam inteiras.
8. Os dois cards possuem exatamente a mesma altura externa.
9. A área de clientes rola verticalmente.
10. O painel de detalhes rola verticalmente.
11. As rolagens são independentes.
12. Não existe quadrado branco no canto inferior direito.
13. Não existe rolagem horizontal da tabela no desktop.

### Regressão

Confirmar que continuam funcionando:

- troca do mês;
- filtros;
- limpar filtros;
- seleção por clique;
- seleção por teclado;
- atualização do Status;
- gráficos;
- explicações das cinco métricas;
- outras páginas do Viewer;
- ausência de erros no console.

## 15. Critérios de aceite

A tarefa estará concluída quando:

- a primeira coluna mostrar `nome_contato`, com fallback para `cliente_id`;
- o cabeçalho for `Nome do cliente`;
- Empresa continuar sendo `nome_empresa`;
- Status estiver completamente visível e mais próximo das outras colunas;
- os três conteúdos aparecerem sem truncamento;
- todas as linhas tiverem altura uniforme;
- os cards Clientes e Status do cliente tiverem a mesma altura;
- cada card possuir rolagem vertical independente;
- a tabela não exigir rolagem horizontal no desktop;
- o quadrado branco da barra de rolagem tiver desaparecido;
- nenhuma regra de cálculo ou Status tiver sido alterada;
- banco, pipeline e demais telas permanecerem intactos.

## 16. Entrega final

Ao finalizar, informar:

- arquivos alterados;
- consulta final com o `LEFT JOIN`;
- como `nome_cliente` foi obtido e filtrado;
- proporções finais das três colunas;
- altura final das linhas;
- altura aplicada aos dois cards;
- estratégia de rolagem independente;
- correção aplicada ao canto da scrollbar;
- resoluções testadas;
- resultado dos testes de regressão;
- confirmação de que cálculos, SQLite e pipeline não foram modificados.
