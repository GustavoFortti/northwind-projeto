/* Página Métricas de clientes - linha do tempo mensal + mestre-detalhe.
   Reutiliza a mesma instância do sql.js aberta por bi.js (recebe o db pronto
   via window.iniciarMetricasClientes); não busca data.sqlite de novo.
   Consome gold.historico_cliente_metricas (tendência das 5 métricas e
   Status geral do cliente) e gold.historico_cliente_volume (histórico
   mensal de pedidos/receita do cliente selecionado, para os 2 gráficos). */
"use strict";

// nomes das tabelas centralizados aqui: se forem renomeadas na gold, só
// estas linhas precisam mudar.
const TABELA_HISTORICO_METRICAS = "historico_cliente_metricas";
const TABELA_HISTORICO_VOLUME = "historico_cliente_volume";
const TABELA_CLIENTES_CADASTRO = "clientes";
const TABELA_HISTORICO_PRODUTOS_CLIENTE = "historico_cliente_produtos";
const TABELA_DESCONTOS = "descontos";

// janela fixa (em meses) usada pelo score de recorrência de produtos da
// aba "O que fazer" - sempre 9 meses terminando no período selecionado,
// mesmo quando o histórico disponível é menor (meses ausentes contam como
// meses sem compra, reduzindo o score em vez de encolher a janela).
const JANELA_SCORE_RECORRENCIA = 9;

const ROTULOS_ABA = {
  status: "Por que o Status",
  fazer: "O que fazer",
};

// tolerância de 20% para classificar uma métrica como "aumentou"/"diminuiu";
// diferenças na fronteira (exatamente ±20%) continuam "normal" - só o que
// ultrapassa a tolerância é significativo.
const TOLERANCIA_TENDENCIA = 0.20;

// margem para a comparação com a tolerância não virar "normal"/"aumentou"
// por ruído de ponto flutuante. Number.EPSILON (~2,22e-16) é pequeno demais
// para o erro real de arredondamento dessas contas decimais; 1e-9 é uma
// margem segura e ainda 8 ordens de grandeza menor que o próprio limite de 20%.
const MARGEM_PONTO_FLUTUANTE = 1e-9;

const ROTULOS_ESTADO = {
  aumentou: "↑ Aumentou",
  normal: "• Normal",
  diminuiu: "↓ Diminuiu",
};

const ROTULOS_STATUS = {
  bom: "Bom",
  normal: "Normal",
  atencao: "Atenção",
  ruim: "Ruim",
};

const NOMES_MESES = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];

const nfMetricas = (dec = 0) =>
  new Intl.NumberFormat("pt-BR", { minimumFractionDigits: dec, maximumFractionDigits: dec });

function formatarPercentual(v) {
  return `${nfMetricas(1).format(v * 100)}%`;
}

function formatarDecimal2(v) {
  return nfMetricas(2).format(v);
}

// as 5 métricas que alimentam o Status geral e a seção "Por que este
// Status?"; `chave` é o prefixo das colunas <chave>_3m/_6m/_9m na gold.
// `modo` diz como a variação entre duas janelas é calculada (ver
// calcularVariacao): "diferenca" para métricas que já são proporções 0-1
// (frequência e desconto - a diferença direta já é "pontos percentuais"),
// "relativa" para métricas em valor absoluto (receita, itens, quantidade -
// aqui faz sentido comparar o quanto mudou em relação ao valor mais antigo).
// A ordem desta lista é a ordem de exibição na seção explicativa.
const METRICAS_FILTRAVEIS = [
  { chave: "frequencia_compra", titulo: "Frequência de compra", formatar: formatarPercentual, modo: "diferenca" },
  { chave: "receita_media", titulo: "Média de receita", formatar: formatarDecimal2, modo: "relativa" },
  { chave: "desconto_medio", titulo: "Média de desconto", formatar: formatarPercentual, modo: "diferenca" },
  { chave: "quantidade_produtos_distintos_media", titulo: "Média de itens variados", formatar: formatarDecimal2, modo: "relativa" },
  { chave: "quantidade_itens_media", titulo: "Média de quantidade", formatar: formatarDecimal2, modo: "relativa" },
];

// tamanho (em meses) de cada janela acumulada, usado só para explicar a
// frequência em "comprou em N dos últimos M meses" (ver metricasExplicarFrequencia).
const TAMANHO_JANELA = { "3m": 3, "6m": 6, "9m": 9 };

let metricasDb = null;
let metricasMeses = []; // [{ anoMes: "1997-04", label: "04/97" }, ...], em ordem cronológica
let metricasMesSelecionado = null; // "YYYY-MM"
let metricasLinhasDoMes = []; // clientes do mês selecionado, já com _estados/_status calculados
let metricasLinhasFiltradas = []; // último resultado filtrado (para navegação/seleção)
let metricasClienteSelecionado = null; // cliente_id da linha ativa no painel
const metricasClientesCache = new Map(); // ano_mes -> linhas cruas já consultadas (evita reconsultar o mesmo mês)
const metricasVolumeCache = new Map(); // "cliente_id|ano_mes_fim" -> 9 pontos mensais já consultados
const metricasAcoesCache = new Map(); // "cliente_id|ano_mes_selecionado" -> produtos com score/oferta já consultados

// aba ativa do painel de detalhes ("status" ou "fazer"); começa em "status"
// e só muda por ação do usuário - preservada entre trocas de cliente/mês.
let metricasAbaAtiva = "status";

// estado dos filtros: cliente/empresa são busca por texto; status filtra
// pelo Status geral calculado (ou "todos").
let metricasFiltroCliente = "";
let metricasFiltroEmpresa = "";
let metricasFiltroStatus = "todos";

/* ── acesso ao banco ──────────────────────────────────────── */

function metricasQuery(db, sql, params) {
  const stmt = db.prepare(sql);
  try {
    if (params) stmt.bind(params);
    const linhas = [];
    while (stmt.step()) linhas.push(stmt.getAsObject());
    return linhas;
  } finally {
    stmt.free();
  }
}

/* ── texto/formatação ─────────────────────────────────────── */

function normalizarTexto(texto) {
  return (texto ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function formatarMesLabel(anoMes) {
  const [ano, mes] = anoMes.split("-");
  return `${mes}/${ano.slice(2)}`;
}

function metricasNomeMesPorExtenso(anoMes) {
  const [ano, mes] = anoMes.split("-").map(Number);
  return `${NOMES_MESES[mes - 1]} de ${ano}`;
}

function metricasNomeMesExtensoCapitalizado(anoMes) {
  const texto = metricasNomeMesPorExtenso(anoMes);
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

// soma/subtrai meses a um "YYYY-MM", devolvendo outro "YYYY-MM".
function metricasSomarMeses(anoMes, delta) {
  const [ano, mes] = anoMes.split("-").map(Number);
  const total = (ano * 12 + (mes - 1)) + delta;
  const anoNovo = Math.floor(total / 12);
  const mesNovo = (total % 12) + 1;
  return `${anoNovo}-${String(mesNovo).padStart(2, "0")}`;
}

// gera a sequência cronológica de `n` meses terminando (inclusive) em `anoMesFim`.
function metricasMesesSequencia(anoMesFim, n) {
  const meses = [];
  for (let i = n - 1; i >= 0; i--) meses.push(metricasSomarMeses(anoMesFim, -i));
  return meses;
}

/* ── dados: histórico de tendência (mês selecionado) ─────────── */

function carregarMeses(db) {
  const linhas = metricasQuery(
    db,
    `SELECT ano_mes FROM ${TABELA_HISTORICO_METRICAS} GROUP BY ano_mes ORDER BY ano_mes`
  );
  return linhas.map((r) => ({ anoMes: r.ano_mes, label: formatarMesLabel(r.ano_mes) }));
}

// uma linha por cliente do mês pedido, só com as colunas usadas nesta tela.
// `nome_cliente` vem de clientes.nome_contato via LEFT JOIN (preserva todos
// os clientes históricos mesmo sem cadastro correspondente), com fallback
// para o próprio cliente_id quando o contato estiver nulo/vazio - nunca
// usado como chave, só como texto de exibição. Resultado cacheado por mês:
// trocar de mês e voltar não dispara nova consulta.
function carregarClientesDoMes(db, anoMes) {
  if (metricasClientesCache.has(anoMes)) return metricasClientesCache.get(anoMes);

  const linhas = metricasQuery(
    db,
    `SELECT
        h.cliente_id,
        COALESCE(NULLIF(TRIM(c.nome_contato), ''), h.cliente_id) AS nome_cliente,
        c.telefone,
        h.nome_empresa,
        h.frequencia_compra_3m, h.frequencia_compra_6m, h.frequencia_compra_9m,
        h.receita_media_3m, h.receita_media_6m, h.receita_media_9m,
        h.desconto_medio_3m, h.desconto_medio_6m, h.desconto_medio_9m,
        h.quantidade_produtos_distintos_media_3m,
        h.quantidade_produtos_distintos_media_6m,
        h.quantidade_produtos_distintos_media_9m,
        h.quantidade_itens_media_3m, h.quantidade_itens_media_6m, h.quantidade_itens_media_9m
     FROM ${TABELA_HISTORICO_METRICAS} AS h
     LEFT JOIN ${TABELA_CLIENTES_CADASTRO} AS c
            ON c.cliente_id = h.cliente_id
     WHERE h.ano_mes = :ano_mes
     ORDER BY nome_cliente, h.nome_empresa, h.cliente_id`,
    { ":ano_mes": anoMes }
  );
  metricasClientesCache.set(anoMes, linhas);
  return linhas;
}

/* ── dados: volume mensal do cliente selecionado (para os gráficos) ──── */

// os 9 meses terminando no mês selecionado, com zero nos meses sem linha
// em historico_cliente_volume (não omite meses sem compra - distorceria a
// evolução). Cacheado por cliente + mês final.
function carregarVolumeCliente(db, clienteId, anoMesFim) {
  const chave = `${clienteId}|${anoMesFim}`;
  if (metricasVolumeCache.has(chave)) return metricasVolumeCache.get(chave);

  const sequencia = metricasMesesSequencia(anoMesFim, 9);
  const anoMesInicio = sequencia[0];

  const linhas = metricasQuery(
    db,
    `SELECT ano_mes, quantidade_pedidos, receita_total
     FROM ${TABELA_HISTORICO_VOLUME}
     WHERE cliente_id = :cliente_id
       AND ano_mes BETWEEN :mes_inicial AND :mes_final
     ORDER BY ano_mes`,
    { ":cliente_id": clienteId, ":mes_inicial": anoMesInicio, ":mes_final": anoMesFim }
  );
  const porMes = new Map(linhas.map((r) => [r.ano_mes, r]));

  const pontos = sequencia.map((anoMes) => {
    const r = porMes.get(anoMes);
    return {
      anoMes,
      quantidade_pedidos: r ? r.quantidade_pedidos : 0,
      receita_total: r ? r.receita_total : 0,
    };
  });
  metricasVolumeCache.set(chave, pontos);
  return pontos;
}

/* ── dados: produtos com score de recorrência (aba "O que fazer") ────── */

// último mês da janela de recorrência: o mês vigente (selecionado na linha
// do tempo) ainda não fechou de fato quando é o mês mais recente da base,
// então a janela avalia os 9 meses ANTERIORES a ele, não incluindo-o - ex.:
// selecionado 1998-02 -> janela termina em 1998-01. Ver metricasMontarAbaFazer,
// que usa esta mesma função para exibir o mês final real na frase.
function metricasFimJanelaScore(anoMesSelecionado) {
  return metricasSomarMeses(anoMesSelecionado, -1);
}

// produtos comprados pelo cliente na janela fixa de 9 meses terminando no
// mês ANTERIOR ao selecionado (ver metricasFimJanelaScore), com o score de
// recorrência (quantos desses meses tiveram ao menos uma compra do
// produto), a categoria do produto e a Oferta vigente no mês selecionado
// em si (LEFT JOIN: produto sem linha em `descontos` naquele mês vira
// `oferta: null`, diferente de um desconto de 0% - ver metricasFormatarOferta).
// A categoria vem da mesma tabela `descontos`, mas buscada por produto (sem
// travar no mês da janela): como ela não muda com o tempo, um produto sem
// linha de desconto no mês exato ainda assim tem a categoria resolvida a
// partir de qualquer outro mês em que ele apareceu na tabela. Cacheado por
// cliente + mês selecionado, já que tanto o score quanto a oferta dependem
// do período.
//
// O Score final de cada produto soma a própria frequência com os pontos de
// frequência de TODOS os outros produtos que o cliente comprou na mesma
// categoria, dentro da mesma janela - ver metricasAdicionarScoreCategoria.
// Isso prioriza produtos de categorias em que o cliente já compra bastante
// (mesmo que o produto específico tenha sido comprado poucas vezes).
function carregarAcoesCliente(db, clienteId, anoMesSelecionado) {
  const chave = `${clienteId}|${anoMesSelecionado}`;
  if (metricasAcoesCache.has(chave)) return metricasAcoesCache.get(chave);

  const mesFinalJanela = metricasFimJanelaScore(anoMesSelecionado);
  const mesInicial = metricasSomarMeses(mesFinalJanela, -(JANELA_SCORE_RECORRENCIA - 1));

  const linhas = metricasQuery(
    db,
    `WITH compras AS (
        SELECT
            h.produto_id,
            MAX(h.produto_nome) AS produto_nome,
            COUNT(DISTINCT h.ano_mes) AS meses_com_compra
        FROM ${TABELA_HISTORICO_PRODUTOS_CLIENTE} AS h
        WHERE h.cliente_id = :cliente_id
          AND h.ano_mes BETWEEN :mes_inicial AND :mes_final_janela
        GROUP BY h.produto_id
     ),
     categorias AS (
        SELECT produto_id, MAX(categoria_id) AS categoria_id
        FROM ${TABELA_DESCONTOS}
        GROUP BY produto_id
     )
     SELECT
        c.produto_id,
        c.produto_nome,
        c.meses_com_compra,
        CAST((c.meses_com_compra * 100.0) / ${JANELA_SCORE_RECORRENCIA} AS INTEGER) AS frequencia,
        cat.categoria_id AS categoria_id,
        d.maior_desconto AS oferta
     FROM compras AS c
     LEFT JOIN categorias AS cat
            ON cat.produto_id = c.produto_id
     LEFT JOIN ${TABELA_DESCONTOS} AS d
            ON d.produto_id = c.produto_id
           AND d.ano_mes = :mes_oferta`,
    {
      ":cliente_id": clienteId,
      ":mes_inicial": mesInicial,
      ":mes_final_janela": mesFinalJanela,
      ":mes_oferta": anoMesSelecionado,
    }
  );
  // a consulta ordena pela frequência individual (meses_com_compra), mas o
  // Score final (calculado depois, em JS) soma o bônus de categoria - por
  // isso a lista precisa ser reordenada pelo Score já combinado, não pela
  // ordem que veio do SQL. Critério: 1º Score (maior primeiro), 2º Oferta
  // (maior desconto primeiro; produto sem registro de oferta - null - fica
  // por último dentro do mesmo Score), 3º nome do produto, só para
  // desempate determinístico quando Score e Oferta coincidem.
  const itens = metricasAdicionarScoreCategoria(linhas);
  itens.sort((a, b) => {
    const ofertaA = a.oferta ?? -1;
    const ofertaB = b.oferta ?? -1;
    return b.score - a.score
      || ofertaB - ofertaA
      || a.produto_nome.localeCompare(b.produto_nome);
  });
  metricasAcoesCache.set(chave, itens);
  return itens;
}

// soma, a cada produto, os pontos de frequência de todos os OUTROS produtos
// da mesma categoria que o cliente também comprou na janela - ex.: se
// Camembert Pierrot (categoria 4, frequência 11) e Mozzarella di Giovanni
// (categoria 4, frequência 11) foram ambos comprados, o Score de cada um
// vira 11 + 11 = 22 (a própria frequência mais a do outro produto da
// categoria). Produtos sem categoria resolvida não recebem nem contribuem
// com bônus de categoria (score = a própria frequência).
function metricasAdicionarScoreCategoria(linhas) {
  const somaPorCategoria = new Map();
  for (const r of linhas) {
    if (r.categoria_id === null || r.categoria_id === undefined) continue;
    somaPorCategoria.set(r.categoria_id, (somaPorCategoria.get(r.categoria_id) || 0) + r.frequencia);
  }

  return linhas.map((r) => {
    const temCategoria = r.categoria_id !== null && r.categoria_id !== undefined;
    const pontosOutrosDaCategoria = temCategoria
      ? somaPorCategoria.get(r.categoria_id) - r.frequencia
      : 0;
    return { ...r, score: r.frequencia + pontosOutrosDaCategoria };
  });
}

// exposta só para testes automatizados, mesmo motivo de metricasClassificarTendencia.
window.metricasAdicionarScoreCategoria = metricasAdicionarScoreCategoria;

/* ── regra de negócio: classificação de tendência individual ─────────── */

// variação relativa de `atual` em relação a `base` - usada para métricas em
// valor absoluto (receita, itens, quantidade), onde "quanto mudou" só faz
// sentido como percentual do valor mais antigo. Os valores das métricas
// nunca são negativos, então só duas situações de base zero podem
// acontecer: as duas pontas zeradas (sem variação, 0) ou a métrica "nasceu"
// nesse período (variação infinita, não NaN).
function variacaoRelativa(atual, base) {
  if (base === 0) return atual === 0 ? 0 : Infinity;
  return (atual - base) / Math.abs(base);
}

// Escolhe como medir a variação entre duas janelas, de acordo com o modo da
// métrica (ver METRICAS_FILTRAVEIS): "diferenca" é a subtração direta
// (atual − base) - usada só para frequência e desconto, que já são
// proporções entre 0 e 1, então a diferença já sai em "pontos percentuais"
// e comparar direto com a tolerância é o que faz sentido. Qualquer outro
// modo ("relativa", o padrão) usa a variação percentual sobre a base, para
// métricas em valor absoluto onde uma subtração direta não teria unidade
// comparável ao limite.
function calcularVariacao(atual, base, modo) {
  if (modo === "diferenca") return atual - base;
  return variacaoRelativa(atual, base);
}

// Classifica a tendência de UMA métrica a partir das três janelas acumuladas
// que já vêm prontas da gold (3m/6m/9m, todas terminando no mês selecionado).
// Compara sempre a janela mais recente (3m) contra as duas referências mais
// longas - 3m×6m e 3m×9m - nunca 6m×9m entre si: isso evita mascarar uma
// queda recente quando 6m e 9m coincidem (ex.: 66,7% / 100% / 100% já é uma
// queda visível de 3m contra as duas referências, mesmo com 6m == 9m).
// O índice de tendência é a MÉDIA das duas comparações (não exige que as
// duas tenham o mesmo sinal) e só passa de "normal" quando ultrapassa
// estritamente a tolerância de 20% (fronteira exata continua "normal").
function classificarTendencia(valor3m, valor6m, valor9m, modo = "relativa") {
  const comparacao36 = calcularVariacao(valor3m, valor6m, modo);
  const comparacao39 = calcularVariacao(valor3m, valor9m, modo);
  const indiceTendencia = (comparacao36 + comparacao39) / 2;
  const limite = TOLERANCIA_TENDENCIA + MARGEM_PONTO_FLUTUANTE;

  let estado = "normal";
  if (indiceTendencia > limite) estado = "aumentou";
  else if (indiceTendencia < -limite) estado = "diminuiu";

  return { estado, comparacao36, comparacao39, indiceTendencia, modo };
}

// exposta só para os testes automatizados da regra de classificação (não é
// usada por nenhuma outra página) - nome com prefixo para não colidir com
// nada de bi.js/grafo.js/vendas.js.
window.metricasClassificarTendencia = classificarTendencia;

/* ── regra de negócio: Status geral do cliente ───────────────────────── */

// Deriva o Status geral (bom/normal/atencao/ruim) a partir dos 3 estados
// individuais que participam da regra - frequência (F), receita (R) e
// quantidade (Q). Desconto e variedade de itens nunca definem o Status:
// são exibidas só como contexto na seção explicativa.
//
// Precedência obrigatória: Ruim > Atenção > Bom > Normal.
//   Ruim    = pelo menos duas entre F/R/Q estão "diminuiu"
//   Atenção = (não é Ruim) e F ou R está "diminuiu"
//   Bom     = (não é Ruim/Atenção) e F e R estão "aumentou"
//   Normal  = nenhuma das anteriores
//
// `motivos` traz as chaves das métricas que efetivamente decidiram o
// Status (usadas tanto na frase-resumo quanto para marcar o "papel" de
// cada métrica na seção explicativa).
function classificarStatusCliente(estados) {
  const F = estados.frequencia_compra.estado;
  const R = estados.receita_media.estado;
  const Q = estados.quantidade_itens_media.estado;

  const diminuiram = [];
  if (F === "diminuiu") diminuiram.push("frequencia_compra");
  if (R === "diminuiu") diminuiram.push("receita_media");
  if (Q === "diminuiu") diminuiram.push("quantidade_itens_media");

  if (diminuiram.length >= 2) {
    return { status: "ruim", motivos: diminuiram };
  }
  if (F === "diminuiu" || R === "diminuiu") {
    return { status: "atencao", motivos: diminuiram };
  }
  if (F === "aumentou" && R === "aumentou") {
    return { status: "bom", motivos: ["frequencia_compra", "receita_media"] };
  }
  return { status: "normal", motivos: [] };
}

// exposta só para testes automatizados, mesmo motivo de metricasClassificarTendencia.
window.metricasClassificarStatusCliente = classificarStatusCliente;

// pré-calcula o estado das 5 métricas e o Status geral de uma linha uma
// única vez por troca de mês, pra filtrar/selecionar/renderizar sem repetir
// a classificação a cada interação.
function metricasEnriquecerLinha(r) {
  const estados = {};
  for (const m of METRICAS_FILTRAVEIS) {
    estados[m.chave] = classificarTendencia(
      r[`${m.chave}_3m`], r[`${m.chave}_6m`], r[`${m.chave}_9m`], m.modo
    );
  }
  return { ...r, _estados: estados, _status: classificarStatusCliente(estados) };
}

/* ── filtros ──────────────────────────────────────────────── */

// Cliente: busca por texto (sem acento, sem caixa) em nome_cliente, com
// fallback pelo cliente_id (permite localizar pelo código sem exibi-lo na
// coluna). Empresa: mesma busca em nome_empresa. Status: filtra pelo Status
// geral já calculado ("todos" não filtra). Os três combinam em E.
function metricasFiltrarLinhas(linhas) {
  const clienteAlvo = normalizarTexto(metricasFiltroCliente);
  const empresaAlvo = normalizarTexto(metricasFiltroEmpresa);

  return linhas.filter((r) => {
    if (clienteAlvo
      && !normalizarTexto(r.nome_cliente).includes(clienteAlvo)
      && !normalizarTexto(r.cliente_id).includes(clienteAlvo)) return false;
    if (empresaAlvo && !normalizarTexto(r.nome_empresa).includes(empresaAlvo)) return false;
    if (metricasFiltroStatus !== "todos" && r._status.status !== metricasFiltroStatus) return false;
    return true;
  });
}

function metricasIniciarFiltros() {
  const campoCliente = document.getElementById("metricas-filtro-cliente");
  const campoEmpresa = document.getElementById("metricas-filtro-empresa");
  const campoStatus = document.getElementById("metricas-filtro-status");

  campoCliente.addEventListener("input", (ev) => {
    metricasFiltroCliente = ev.target.value;
    metricasRenderizarTabela();
  });
  campoEmpresa.addEventListener("input", (ev) => {
    metricasFiltroEmpresa = ev.target.value;
    metricasRenderizarTabela();
  });
  campoStatus.addEventListener("change", (ev) => {
    metricasFiltroStatus = ev.target.value;
    metricasRenderizarTabela();
  });

  document.getElementById("metricas-filtro-limpar").addEventListener("click", () => {
    metricasFiltroCliente = "";
    metricasFiltroEmpresa = "";
    metricasFiltroStatus = "todos";
    campoCliente.value = "";
    campoEmpresa.value = "";
    campoStatus.value = "todos";
    metricasRenderizarTabela();
  });
}

/* ── render: linha do tempo ───────────────────────────────── */

function metricasRenderizarTimeline() {
  const box = document.getElementById("metricas-tempo");
  box.textContent = "";

  for (const m of metricasMeses) {
    const item = document.createElement("div");
    item.className = "metricas-tempo-item";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "metricas-tempo-marcador";
    btn.dataset.anoMes = m.anoMes;
    btn.setAttribute("aria-label", `Selecionar ${metricasNomeMesPorExtenso(m.anoMes)}`);
    btn.addEventListener("click", () => metricasSelecionarMes(m.anoMes));

    const ponto = document.createElement("span");
    ponto.className = "metricas-tempo-ponto";
    btn.appendChild(ponto);

    // rótulo MM/AA sempre visível, embaixo de cada marcador (não só do
    // selecionado/vizinhos) - só o destaque visual muda com a seleção.
    const rotulo = document.createElement("span");
    rotulo.className = "metricas-tempo-rotulo";
    rotulo.dataset.anoMes = m.anoMes;
    rotulo.textContent = m.label;

    item.append(btn, rotulo);
    box.appendChild(item);
  }
}

// destaca o marcador selecionado (círculo maior + aria-current + rótulo em
// destaque); os rótulos dos demais meses continuam visíveis, só sem o
// destaque visual.
function metricasAtualizarMarcadoresAtivos() {
  const idx = metricasMeses.findIndex((m) => m.anoMes === metricasMesSelecionado);

  document.querySelectorAll(".metricas-tempo-marcador").forEach((btn) => {
    const selecionado = btn.dataset.anoMes === metricasMesSelecionado;
    btn.classList.toggle("selecionado", selecionado);
    if (selecionado) btn.setAttribute("aria-current", "date");
    else btn.removeAttribute("aria-current");
  });

  document.querySelectorAll(".metricas-tempo-rotulo").forEach((el, i) => {
    el.classList.toggle("metricas-tempo-rotulo--selecionado", i === idx);
  });
}

// mostra o mês/ano por extenso, bem visível, acima da linha do tempo -
// além do rótulo MM/AA de cada marcador, pra ficar óbvio qual período está
// selecionado sem precisar olhar pra linha do tempo.
function metricasAtualizarMesAtual() {
  const el = document.getElementById("metricas-mes-atual-valor");
  if (el) el.textContent = metricasNomeMesExtensoCapitalizado(metricasMesSelecionado);
}

function metricasIniciarTeclado() {
  const box = document.getElementById("metricas-tempo");
  box.addEventListener("keydown", (ev) => {
    const idxAtual = metricasMeses.findIndex((m) => m.anoMes === metricasMesSelecionado);
    let novoIdx = null;
    if (ev.key === "ArrowLeft") novoIdx = Math.max(0, idxAtual - 1);
    else if (ev.key === "ArrowRight") novoIdx = Math.min(metricasMeses.length - 1, idxAtual + 1);
    else if (ev.key === "Home") novoIdx = 0;
    else if (ev.key === "End") novoIdx = metricasMeses.length - 1;
    if (novoIdx === null) return;

    ev.preventDefault();
    const anoMes = metricasMeses[novoIdx].anoMes;
    metricasSelecionarMes(anoMes);
    const btn = box.querySelector(`.metricas-tempo-marcador[data-ano-mes="${anoMes}"]`);
    if (btn) {
      btn.focus();
      btn.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  });
}

function metricasSelecionarMes(anoMes) {
  if (anoMes === metricasMesSelecionado) return;
  metricasMesSelecionado = anoMes;
  metricasAtualizarMarcadoresAtivos();
  metricasAtualizarMesAtual();
  metricasCarregarEExibir();
}

/* ── render: tabela de clientes (mestre) ──────────────────── */

function metricasCriarTagStatus(status) {
  const span = document.createElement("span");
  span.className = `metricas-status-cliente metricas-status-cliente--${status}`;
  span.textContent = ROTULOS_STATUS[status];
  return span;
}

// busca os clientes do mês selecionado (cacheado) e já classifica as 5
// métricas + o Status geral de cada um; chamado só quando o mês muda, nunca
// por causa de um filtro (filtrar não dispara consulta nova).
function metricasCarregarEExibir() {
  let linhas;
  try {
    linhas = carregarClientesDoMes(metricasDb, metricasMesSelecionado);
  } catch (err) {
    window.mostrarErroMetricasClientes(
      `Não foi possível consultar as métricas de clientes. Detalhe: ${err.message}`
    );
    return;
  }
  metricasLinhasDoMes = linhas.map(metricasEnriquecerLinha);
  metricasRenderizarTabela();
}

// decide qual cliente fica selecionado após um novo render filtrado:
// preserva a seleção atual se ela continuar visível, senão cai para a
// primeira linha filtrada, senão não há seleção possível.
function metricasEscolherSelecao(filtradas) {
  if (metricasClienteSelecionado && filtradas.some((r) => r.cliente_id === metricasClienteSelecionado)) {
    return metricasClienteSelecionado;
  }
  return filtradas.length ? filtradas[0].cliente_id : null;
}

function metricasSelecionarCliente(clienteId) {
  metricasClienteSelecionado = clienteId;
  document.querySelectorAll(".metricas-table--linhas tbody tr").forEach((tr) => {
    const ativa = tr.dataset.clienteId === clienteId;
    tr.classList.toggle("metricas-row-selecionada", ativa);
    tr.setAttribute("aria-selected", ativa ? "true" : "false");
  });
  metricasRenderizarPainel();
}

function metricasRenderizarTabela() {
  const scroll = document.getElementById("metricas-tabela-scroll");
  const contagem = document.getElementById("metricas-tabela-contagem");
  scroll.textContent = "";

  const label = formatarMesLabel(metricasMesSelecionado);
  const total = metricasLinhasDoMes.length;

  if (!total) {
    contagem.textContent = "";
    const vazio = document.createElement("div");
    vazio.className = "metricas-empty";
    vazio.textContent = `Nenhum cliente encontrado para ${label}.`;
    scroll.appendChild(vazio);
    metricasLinhasFiltradas = [];
    metricasClienteSelecionado = null;
    metricasRenderizarPainel();
    return;
  }

  const filtradas = metricasFiltrarLinhas(metricasLinhasDoMes);
  metricasLinhasFiltradas = filtradas;

  contagem.textContent = filtradas.length === total
    ? `Retrato de ${label} · ${nfMetricas(0).format(total)} ${total === 1 ? "cliente" : "clientes"}`
    : `Retrato de ${label} · ${nfMetricas(0).format(filtradas.length)} de ${nfMetricas(0).format(total)} clientes`;

  if (!filtradas.length) {
    const vazio = document.createElement("div");
    vazio.className = "metricas-empty";
    vazio.textContent = "Nenhum cliente encontrado com os filtros aplicados.";
    scroll.appendChild(vazio);
    metricasClienteSelecionado = null;
    metricasRenderizarPainel();
    return;
  }

  const table = document.createElement("table");
  table.className = "metricas-table metricas-table--linhas";

  // larguras proporcionais fixas: sem elas o texto mais longo de Empresa
  // empurra Status pra fora da área visível do card (a causa da rolagem
  // horizontal indesejada).
  const colgroup = document.createElement("colgroup");
  for (const largura of [30, 44, 26]) {
    const col = document.createElement("col");
    col.style.width = `${largura}%`;
    colgroup.appendChild(col);
  }

  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  for (const titulo of ["Nome do cliente", "Empresa", "Status"]) {
    const th = document.createElement("th");
    th.textContent = titulo;
    trh.appendChild(th);
  }
  thead.appendChild(trh);

  const clienteSelecionado = metricasEscolherSelecao(filtradas);

  const tbody = document.createElement("tbody");
  for (const r of filtradas) {
    const tr = document.createElement("tr");
    tr.dataset.clienteId = r.cliente_id;
    tr.tabIndex = 0;
    tr.setAttribute("role", "row");
    tr.setAttribute("aria-selected", r.cliente_id === clienteSelecionado ? "true" : "false");
    tr.setAttribute("aria-label", `${r.nome_cliente} - ${r.nome_empresa} (cliente ${r.cliente_id})`);
    if (r.cliente_id === clienteSelecionado) tr.classList.add("metricas-row-selecionada");

    tr.addEventListener("click", () => metricasSelecionarCliente(r.cliente_id));
    tr.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        metricasSelecionarCliente(r.cliente_id);
      }
    });

    const tdCliente = document.createElement("td");
    tdCliente.className = "metricas-td-cliente";
    tdCliente.textContent = r.nome_cliente;

    const tdEmpresa = document.createElement("td");
    tdEmpresa.className = "metricas-td-empresa";
    tdEmpresa.textContent = r.nome_empresa;

    const tdStatus = document.createElement("td");
    tdStatus.className = "metricas-td-status";
    tdStatus.appendChild(metricasCriarTagStatus(r._status.status));

    tr.append(tdCliente, tdEmpresa, tdStatus);
    tbody.appendChild(tr);
  }

  table.append(colgroup, thead, tbody);
  scroll.appendChild(table);

  metricasClienteSelecionado = clienteSelecionado;
  metricasRenderizarPainel();
}

/* ── painel explicativo (detalhe do cliente selecionado) ──── */

function metricasCriarLinha(classe, texto) {
  const el = document.createElement("p");
  el.className = classe;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

// frase curta e determinística resumindo por que o cliente recebeu o
// Status atual, citando exatamente as métricas que decidiram (não inventa
// causalidade nem previsão - só descreve os sinais já calculados).
function metricasFraseStatus(statusObj) {
  const nomes = {
    frequencia_compra: "a frequência de compra",
    receita_media: "a receita média",
    quantidade_itens_media: "a quantidade comprada",
  };
  const juntar = (itens) => itens.length <= 1
    ? (itens[0] || "")
    : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`;
  const capitalizar = (t) => t.charAt(0).toUpperCase() + t.slice(1);

  if (statusObj.status === "bom") {
    return "Frequência de compra e receita média aumentaram.";
  }
  if (statusObj.status === "normal") {
    return "Frequência e receita permanecem dentro do comportamento normal.";
  }
  if (statusObj.status === "atencao") {
    const lista = juntar(statusObj.motivos.map((c) => nomes[c]));
    return `${capitalizar(lista)} diminuiu; acompanhe a evolução deste cliente.`;
  }
  const lista = juntar(statusObj.motivos.map((c) => nomes[c]));
  return `${capitalizar(lista)} diminuíram, atendendo ao critério de risco.`;
}

// papel de cada métrica na explicação: Principal (sempre, para frequência e
// receita - são as que decidem Bom/Atenção/Ruim), Agravante (quantidade,
// só quando ela "diminuiu" e participou de um Status Ruim) ou Contexto
// (desconto e variedade de itens nunca definem o Status).
function metricasPapelMetrica(chave, statusObj) {
  const participou = statusObj.motivos.includes(chave);
  if (chave === "frequencia_compra" || chave === "receita_media") {
    return participou ? "Principal · participou do Status" : "Principal · não alterou o Status";
  }
  if (chave === "quantidade_itens_media") {
    return participou && statusObj.status === "ruim"
      ? "Agravante · reforçou o Status Ruim"
      : "Contexto operacional";
  }
  return "Contexto · não define o Status";
}

function metricasFormula(rotulo, expressao) {
  const p = document.createElement("p");
  p.className = "vt-formula";
  const lb = document.createElement("span");
  lb.className = "vt-formula-label";
  lb.textContent = rotulo;
  p.append(lb, document.createTextNode(expressao));
  return p;
}

// formata a variação já calculada (diferença ou percentual) para exibição,
// com sinal explícito e a unidade certa pro modo ("p.p." pontos percentuais
// para diferença direta, "%" para variação relativa).
function metricasFormatarVariacaoTexto(v, modo) {
  if (v === Infinity) return "sem valor no período mais antigo (passou a existir agora)";
  const numero = nfMetricas(1).format(v * 100);
  const comSinal = v > 0 ? `+${numero}` : numero;
  return modo === "diferenca" ? `${comSinal} p.p.` : `${comSinal}%`;
}

// explicação de "frequência" em quantidade de meses ativos (só apresentação
// - não recalcula nada, é só Math.round(frequencia * tamanho da janela)).
function metricasExplicarFrequencia(sufixo, valor) {
  const tamanho = TAMANHO_JANELA[sufixo];
  const meses = Math.round(valor * tamanho);
  return `${formatarPercentual(valor)} (${meses}/${tamanho})`;
}

function metricasValorFormatado(m, sufixo, valor) {
  if (m.chave === "frequencia_compra") return metricasExplicarFrequencia(sufixo, valor);
  return m.formatar(valor);
}

function metricasMontarCardMetrica(m, r, statusObj) {
  const estadoObj = r._estados[m.chave];
  const valor3m = r[`${m.chave}_3m`];
  const valor6m = r[`${m.chave}_6m`];
  const valor9m = r[`${m.chave}_9m`];

  const card = document.createElement("div");
  card.className = "metricas-metrica-card";

  const topo = document.createElement("div");
  topo.className = "metricas-metrica-linha-topo";
  const nome = document.createElement("span");
  nome.className = "metricas-metrica-nome";
  nome.textContent = m.titulo;
  const tag = document.createElement("span");
  tag.className = `metricas-status metricas-status--${estadoObj.estado}`;
  tag.textContent = ROTULOS_ESTADO[estadoObj.estado];
  const papel = document.createElement("span");
  papel.className = "metricas-metrica-papel";
  papel.textContent = metricasPapelMetrica(m.chave, statusObj);
  topo.append(nome, tag, papel);

  const valores = metricasCriarLinha(
    "metricas-metrica-valores",
    `3m: ${metricasValorFormatado(m, "3m", valor3m)} · 6m: ${metricasValorFormatado(m, "6m", valor6m)} · 9m: ${metricasValorFormatado(m, "9m", valor9m)}`
  );

  const comparacoes = metricasCriarLinha(
    "metricas-metrica-comparacoes",
    `3×6: ${metricasFormatarVariacaoTexto(estadoObj.comparacao36, m.modo)} · ` +
    `3×9: ${metricasFormatarVariacaoTexto(estadoObj.comparacao39, m.modo)} · ` +
    `média: ${metricasFormatarVariacaoTexto(estadoObj.indiceTendencia, m.modo)}`
  );

  const interpretacao = metricasCriarLinha("metricas-metrica-interpretacao", metricasInterpretarEstado(m, estadoObj));

  card.append(topo, valores, comparacoes, interpretacao);
  return card;
}

function metricasInterpretarEstado(m, estadoObj) {
  const unidade = m.modo === "diferenca" ? "pontos percentuais" : "percentual";
  if (estadoObj.estado === "aumentou") {
    return `A variação média (3m contra 6m e 9m) superou +20% em ${unidade}.`;
  }
  if (estadoObj.estado === "diminuiu") {
    return `A variação média (3m contra 6m e 9m) ficou abaixo de −20% em ${unidade}.`;
  }
  return "A variação média (3m contra 6m e 9m) permaneceu dentro da tolerância de 20%.";
}

/* ── painel: gráficos mensais (SVG nativo) ────────────────── */

function metricasTicksBonitos(max, n = 4) {
  if (max <= 0) return { teto: 1, ticks: [0, 1] };
  const bruto = max / n;
  const mag = 10 ** Math.floor(Math.log10(bruto));
  const passo = [1, 2, 2.5, 5, 10].map((mult) => mult * mag).find((p) => p >= bruto) || mag * 10;
  const teto = Math.ceil(max / passo) * passo;
  const ticks = [];
  for (let v = 0; v <= teto; v += passo) ticks.push(v);
  return { teto, ticks };
}

const metricasFmtTickReceita = (v) =>
  v >= 1000 ? `${nfMetricas(v % 1000 === 0 ? 0 : 1).format(v / 1000)} mil` : nfMetricas(0).format(v);

// gráfico de linha simples e acessível: grade discreta, pontos, mês
// selecionado destacado, título/descrição textual pra leitores de tela.
// `inteiro` força os ticks do eixo Y a valores inteiros (frequência).
function metricasRenderizarGrafico(container, opts) {
  const { titulo, subtitulo, pontos, campo, cor, inteiro, formatarValor, mesSelecionado } = opts;
  container.textContent = "";

  const h2 = document.createElement("p");
  h2.className = "metricas-grafico-titulo";
  h2.textContent = titulo;
  const sub = document.createElement("p");
  sub.className = "metricas-grafico-sub";
  sub.textContent = subtitulo;
  container.append(h2, sub);

  const valores = pontos.map((p) => p[campo]);
  const todosZero = valores.every((v) => v === 0);

  if (todosZero) {
    const vazio = document.createElement("p");
    vazio.className = "metricas-empty";
    vazio.textContent = "Sem movimento neste período (todos os 9 meses em zero).";
    container.appendChild(vazio);
    return;
  }

  const W = Math.max(container.clientWidth || 280, 220);
  const H = 150;
  const M = { top: 14, right: 12, bottom: 20, left: 34 };
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;

  const escala = metricasTicksBonitos(Math.max(...valores));
  const y = (v) => M.top + ih - (v / escala.teto) * ih;
  const passo = pontos.length > 1 ? iw / (pontos.length - 1) : 0;
  const x = (i) => M.left + passo * i;

  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${titulo}: ${pontos.map((p) => `${formatarMesLabel(p.anoMes)} ${formatarValor(p[campo])}`).join(", ")}`);

  const el = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    svg.appendChild(e);
    return e;
  };

  for (const t of escala.ticks) {
    el("line", { x1: M.left, x2: W - M.right, y1: y(t), y2: y(t), class: "mg-grade" });
    const txt = el("text", { x: M.left - 6, y: y(t) + 3, "text-anchor": "end", class: "mg-eixo" });
    txt.textContent = inteiro ? nfMetricas(0).format(t) : metricasFmtTickReceita(t);
  }

  pontos.forEach((p, i) => {
    const ultimo = i === pontos.length - 1;
    if (!ultimo && i % 2 !== 0) return;
    const txt = el("text", { x: x(i), y: H - 4, "text-anchor": "middle", class: "mg-eixo" });
    txt.textContent = formatarMesLabel(p.anoMes);
  });

  const d = pontos.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p[campo])}`).join(" ");
  el("path", { d, class: "mg-linha", stroke: cor });

  pontos.forEach((p, i) => {
    const selecionado = p.anoMes === mesSelecionado;
    el("circle", {
      cx: x(i), cy: y(p[campo]), r: selecionado ? 4 : 3,
      fill: cor, class: `mg-ponto${selecionado ? " mg-ponto--selecionado" : ""}`,
    });
  });

  container.appendChild(svg);
}

/* ── painel: aba "O que fazer" (produtos por recorrência) ────────────── */

// Oferta e ausência de oferta são estados diferentes: `oferta` vem de um
// LEFT JOIN, então `null`/`undefined` significa "produto sem linha em
// descontos naquele mês" (nunca vira 0% silenciosamente), enquanto um
// desconto de fato 0% mostra "Sem desconto" - os dois textos deixam a
// diferença explícita para quem lê a tela.
function metricasFormatarOferta(oferta) {
  if (oferta === null || oferta === undefined) {
    return { texto: "Sem oferta", classe: "sem-registro", acessivel: "sem registro de desconto para este produto no mês selecionado" };
  }
  if (oferta === 0) {
    return { texto: "Sem desconto", classe: "sem-desconto", acessivel: "maior desconto observado no mês selecionado: 0%" };
  }
  return { texto: formatarPercentual(oferta), classe: "ativa", acessivel: `maior desconto observado no mês selecionado: ${formatarPercentual(oferta)}` };
}

function metricasMontarLinhaProduto(item) {
  const tr = document.createElement("tr");

  const tdNome = document.createElement("td");
  tdNome.className = "metricas-td-produto";
  tdNome.textContent = item.produto_nome;

  const tdCategoria = document.createElement("td");
  tdCategoria.className = "metricas-td-categoria";
  tdCategoria.textContent = item.categoria_id === null || item.categoria_id === undefined
    ? "–"
    : `${item.categoria_id}`;
  tdCategoria.setAttribute("aria-label", item.categoria_id === null || item.categoria_id === undefined
    ? "Sem categoria"
    : `Categoria ${item.categoria_id}`);

  const tdScore = document.createElement("td");
  tdScore.className = "metricas-td-score";
  const scorePontos = document.createElement("span");
  scorePontos.className = "metricas-score-pontos";
  scorePontos.textContent = `${item.score} ${item.score === 1 ? "ponto" : "pontos"}`;
  tdScore.append(scorePontos);

  const tdOferta = document.createElement("td");
  tdOferta.className = "metricas-td-oferta";
  const oferta = metricasFormatarOferta(item.oferta);
  const tagOferta = document.createElement("span");
  tagOferta.className = `metricas-oferta metricas-oferta--${oferta.classe}`;
  tagOferta.textContent = oferta.texto;
  tagOferta.setAttribute("aria-label", `Oferta: ${oferta.texto} - ${oferta.acessivel}`);
  tdOferta.appendChild(tagOferta);

  tr.append(tdNome, tdCategoria, tdScore, tdOferta);
  return tr;
}

// Conteúdo completo da aba "O que fazer": produtos comprados pelo cliente
// na janela fixa de 9 meses terminando no mês ANTERIOR ao selecionado (ver
// metricasFimJanelaScore - o mês vigente em si fica de fora da contagem),
// ordenados pelo Score final (maior primeiro) e, em caso de empate, pela
// Oferta (maior desconto primeiro). A consulta em si vive em
// carregarAcoesCliente; esta função só monta a apresentação.
function metricasMontarAbaFazer(clienteId, anoMesSelecionado) {
  const mesFinalJanela = metricasFimJanelaScore(anoMesSelecionado);

  const container = document.createElement("div");
  container.className = "metricas-fazer";

  const h4 = document.createElement("h4");
  h4.textContent = "Produtos com maior chande do cliente comprar";
  const sub = document.createElement("p");
  sub.className = "metricas-fazer-sub";
  sub.textContent = `Produtos já comprados pelo cliente nos ${JANELA_SCORE_RECORRENCIA} meses encerrados em ${formatarMesLabel(mesFinalJanela)}.`;
  const explicacaoScore = document.createElement("p");
  explicacaoScore.className = "metricas-fazer-sub metricas-fazer-explicacao";
  explicacaoScore.textContent = `Score = frequência de compra do produto (dentro de uma janela fixa de ${JANELA_SCORE_RECORRENCIA} meses) + frequência dos demais produtos que o cliente comprou na mesma categoria.`;
  container.append(h4, sub, explicacaoScore);

  let itens;
  try {
    itens = carregarAcoesCliente(metricasDb, clienteId, anoMesSelecionado);
  } catch (err) {
    const erro = document.createElement("div");
    erro.className = "metricas-empty";
    erro.textContent = `Não foi possível carregar os produtos deste cliente. Detalhe: ${err.message}`;
    container.appendChild(erro);
    return container;
  }

  if (!itens.length) {
    const vazio = document.createElement("div");
    vazio.className = "metricas-empty";
    vazio.textContent = `Nenhum produto comprado por este cliente nos ${JANELA_SCORE_RECORRENCIA} meses até ${formatarMesLabel(mesFinalJanela)}.`;
    container.appendChild(vazio);
    return container;
  }

  const table = document.createElement("table");
  table.className = "metricas-table metricas-table--fazer";

  const colgroup = document.createElement("colgroup");
  for (const largura of [34, 16, 26, 24]) {
    const col = document.createElement("col");
    col.style.width = `${largura}%`;
    colgroup.appendChild(col);
  }

  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  for (const titulo of ["Nome do produto", "Categoria", "Score", "Oferta"]) {
    const th = document.createElement("th");
    th.textContent = titulo;
    trh.appendChild(th);
  }
  thead.appendChild(trh);

  const tbody = document.createElement("tbody");
  for (const item of itens) tbody.appendChild(metricasMontarLinhaProduto(item));

  table.append(colgroup, thead, tbody);
  container.appendChild(table);
  return container;
}

/* ── painel: abas (Por que o Status / O que fazer) ────────────────────── */

// monta a barra de abas acessível e os dois painéis; respeita a aba
// atualmente ativa (`metricasAbaAtiva`, preservada entre trocas de cliente
// e de período) e liga clique + navegação por teclado (ArrowLeft/Right/
// Home/End com ativação imediata, igual ao padrão já usado na linha do
// tempo em metricasIniciarTeclado).
function metricasMontarAbas(conteudoStatus, conteudoFazer, onAtivar) {
  const abas = [
    { id: "status", conteudo: conteudoStatus },
    { id: "fazer", conteudo: conteudoFazer },
  ];

  const tablist = document.createElement("div");
  tablist.className = "metricas-abas";
  tablist.setAttribute("role", "tablist");
  tablist.setAttribute("aria-label", "Detalhes do cliente selecionado");

  const paineis = document.createElement("div");
  paineis.className = "metricas-abas-paineis";

  const botoes = [];
  const painelPorAba = {};

  for (const aba of abas) {
    const ativa = aba.id === metricasAbaAtiva;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "metricas-aba";
    btn.id = `metricas-aba-tab-${aba.id}`;
    btn.dataset.aba = aba.id;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", ativa ? "true" : "false");
    btn.setAttribute("aria-controls", `metricas-aba-painel-${aba.id}`);
    btn.tabIndex = ativa ? 0 : -1;
    btn.textContent = ROTULOS_ABA[aba.id];
    btn.classList.toggle("metricas-aba--ativa", ativa);
    botoes.push(btn);

    const painel = document.createElement("div");
    painel.className = "metricas-aba-painel";
    painel.id = `metricas-aba-painel-${aba.id}`;
    painel.setAttribute("role", "tabpanel");
    painel.setAttribute("aria-labelledby", btn.id);
    painel.tabIndex = 0;
    if (!ativa) painel.hidden = true;
    painel.appendChild(aba.conteudo);
    painelPorAba[aba.id] = painel;

    tablist.appendChild(btn);
    paineis.appendChild(painel);
  }

  const ativarAba = (id) => {
    metricasAbaAtiva = id;
    for (const btn of botoes) {
      const ativa = btn.dataset.aba === id;
      btn.setAttribute("aria-selected", ativa ? "true" : "false");
      btn.tabIndex = ativa ? 0 : -1;
      btn.classList.toggle("metricas-aba--ativa", ativa);
      painelPorAba[btn.dataset.aba].hidden = !ativa;
    }
    if (onAtivar) onAtivar(id);
  };

  for (const btn of botoes) {
    btn.addEventListener("click", () => ativarAba(btn.dataset.aba));
  }

  tablist.addEventListener("keydown", (ev) => {
    const idxAtual = botoes.findIndex((b) => b.dataset.aba === metricasAbaAtiva);
    let novoIdx = null;
    if (ev.key === "ArrowLeft") novoIdx = Math.max(0, idxAtual - 1);
    else if (ev.key === "ArrowRight") novoIdx = Math.min(botoes.length - 1, idxAtual + 1);
    else if (ev.key === "Home") novoIdx = 0;
    else if (ev.key === "End") novoIdx = botoes.length - 1;
    if (novoIdx === null) return;

    ev.preventDefault();
    const alvo = botoes[novoIdx];
    ativarAba(alvo.dataset.aba);
    alvo.focus();
  });

  const frag = document.createDocumentFragment();
  frag.append(tablist, paineis);
  return frag;
}

/* ── painel: montagem completa ────────────────────────────── */

function metricasMostrarPainelVazio(msg) {
  const painel = document.getElementById("metricas-painel");
  painel.textContent = "";
  const vazio = document.createElement("div");
  vazio.className = "metricas-empty";
  vazio.textContent = msg;
  painel.appendChild(vazio);
}

function metricasRenderizarPainel() {
  const painel = document.getElementById("metricas-painel");

  if (!metricasClienteSelecionado) {
    metricasMostrarPainelVazio("Selecione um cliente para visualizar o histórico e a justificativa do Status.");
    return;
  }

  const r = metricasLinhasFiltradas.find((linha) => linha.cliente_id === metricasClienteSelecionado)
    || metricasLinhasDoMes.find((linha) => linha.cliente_id === metricasClienteSelecionado);
  if (!r) {
    metricasMostrarPainelVazio("Selecione um cliente para visualizar o histórico e a justificativa do Status.");
    return;
  }

  painel.textContent = "";

  // cabeçalho: cliente + empresa + tag de Status + mês (permanece visível
  // acima das abas, igual nas duas)
  const cabecalho = document.createElement("div");
  cabecalho.className = "metricas-painel-cabecalho";
  const rotulo = document.createElement("span");
  rotulo.className = "metricas-painel-rotulo";
  rotulo.textContent = "Status do cliente";
  const linhaTitulo = document.createElement("div");
  linhaTitulo.className = "metricas-painel-titulo-linha";
  const h3 = document.createElement("h3");
  h3.textContent = `${r.nome_cliente} - ${r.nome_empresa}`;
  linhaTitulo.append(h3, metricasCriarTagStatus(r._status.status));
  const contatoEl = document.createElement("span");
  contatoEl.className = "metricas-painel-contato";
  const telefone = (r.telefone ?? "").trim();
  contatoEl.textContent = telefone ? `Contato: ${telefone}` : "Contato: não cadastrado";
  const mesEl = document.createElement("span");
  mesEl.className = "metricas-painel-mes";
  mesEl.textContent = `Cliente ${r.cliente_id} · Retrato de ${formatarMesLabel(metricasMesSelecionado)}`;
  cabecalho.append(rotulo, linhaTitulo, contatoEl, mesEl);

  // conteúdo da aba "Por que o Status": frase-resumo, os 2 gráficos mensais
  // e os 5 cards de métrica - idêntico ao que já existia, só reorganizado
  // dentro de um container próprio para virar o painel de uma aba.
  const conteudoStatus = document.createElement("div");
  const frase = document.createElement("p");
  frase.className = "metricas-painel-frase";
  frase.textContent = metricasFraseStatus(r._status);
  conteudoStatus.appendChild(frase);

  const pontos = carregarVolumeCliente(metricasDb, r.cliente_id, metricasMesSelecionado);
  const graficos = document.createElement("div");
  graficos.className = "metricas-graficos";
  const graficoFreq = document.createElement("div");
  graficoFreq.className = "metricas-grafico";
  const graficoReceita = document.createElement("div");
  graficoReceita.className = "metricas-grafico";
  graficos.append(graficoFreq, graficoReceita);
  conteudoStatus.appendChild(graficos);

  const porque = document.createElement("div");
  porque.className = "metricas-porque";
  const h4 = document.createElement("h4");
  h4.textContent = "Por que este Status?";
  porque.appendChild(h4);
  for (const m of METRICAS_FILTRAVEIS) {
    porque.appendChild(metricasMontarCardMetrica(m, r, r._status));
  }
  conteudoStatus.appendChild(porque);

  // conteúdo da aba "O que fazer": produtos + score de recorrência + oferta
  const conteudoFazer = metricasMontarAbaFazer(r.cliente_id, metricasMesSelecionado);

  // os gráficos SVG precisam do clientWidth real do container, que só
  // existe enquanto a aba "Por que o Status" está visível (um painel com
  // `hidden` tem clientWidth 0). Por isso o desenho é adiado para quando
  // essa aba realmente estiver visível: agora, se ela já abrir ativa, ou
  // sob demanda, se o usuário trocar para ela depois de abrir na aba
  // "O que fazer".
  const desenharGraficos = () => {
    metricasRenderizarGrafico(graficoFreq, {
      titulo: "Frequência mensal",
      subtitulo: "Pedidos realizados em cada mês",
      pontos, campo: "quantidade_pedidos", cor: "#58a6ff", inteiro: true,
      formatarValor: (v) => nfMetricas(0).format(v),
      mesSelecionado: metricasMesSelecionado,
    });
    metricasRenderizarGrafico(graficoReceita, {
      titulo: "Receita mensal",
      subtitulo: "Receita após descontos em cada mês",
      pontos, campo: "receita_total", cor: "#3fb950", inteiro: false,
      formatarValor: (v) => formatarDecimal2(v),
      mesSelecionado: metricasMesSelecionado,
    });
  };

  painel.append(
    cabecalho,
    metricasMontarAbas(conteudoStatus, conteudoFazer, (id) => {
      if (id === "status") desenharGraficos();
    })
  );
  painel.scrollTop = 0;

  if (metricasAbaAtiva === "status") desenharGraficos();
}

/* ── erro / vazio ─────────────────────────────────────────── */

function metricasMostrarMensagem(msg) {
  const scroll = document.getElementById("metricas-tabela-scroll");
  scroll.textContent = "";
  const vazio = document.createElement("div");
  vazio.className = "metricas-empty";
  vazio.textContent = msg;
  scroll.appendChild(vazio);
  document.getElementById("metricas-tabela-contagem").textContent = "";
  metricasMostrarPainelVazio("Selecione um cliente para visualizar o histórico e a justificativa do Status.");
}

window.mostrarErroMetricasClientes = function mostrarErroMetricasClientes(msg) {
  const box = document.getElementById("metricas-error");
  box.classList.remove("hidden");
  box.textContent = msg;

  const tempo = document.getElementById("metricas-tempo");
  tempo.textContent = "";

  metricasMostrarMensagem("Não foi possível carregar as métricas de clientes.");
};

/* ── init ─────────────────────────────────────────────────── */

window.iniciarMetricasClientes = function iniciarMetricasClientes(db) {
  try {
    metricasDb = db;
    metricasMeses = carregarMeses(db);
  } catch (err) {
    console.warn("metricas-clientes: falha ao carregar meses -", err.message);
    window.mostrarErroMetricasClientes(
      `Não foi possível carregar as métricas de clientes. Detalhe: ${err.message}`
    );
    return;
  }

  if (!metricasMeses.length) {
    metricasMostrarMensagem("Nenhum histórico de métricas de clientes disponível.");
    return;
  }

  metricasRenderizarTimeline();
  metricasIniciarTeclado();
  metricasIniciarFiltros();
  metricasSelecionarMes(metricasMeses[metricasMeses.length - 1].anoMes);
};
