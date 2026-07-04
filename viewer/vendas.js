/* Página Vendas - busca de produtos, carrinho e sugestões de co-compra.
   Reutiliza a mesma instância do sql.js aberta por bi.js (recebe o db
   pronto via window.iniciarVendas); não busca data.sqlite de novo.
   Mostra comportamento histórico de co-compra, não previsão nem
   probabilidade de compra. */
"use strict";

// nomes das tabelas centralizados aqui: se forem renomeadas na gold,
// só estas linhas precisam mudar.
const TABELA_PRODUTOS = "produtos";
const TABELA_ASSOCIACOES = "produtos_associados";
const TABELA_CLIENTES = "clientes";
const TABELA_HISTORICO_CLIENTE_PRODUTOS = "historico_cliente_produtos";
const TABELA_OFERTAS = "descontos";

const TOP_N_POR_PRODUTO = 5;
const MAX_RESULTADOS_CLIENTE = 20;

const nfVendas = (dec = 0) =>
  new Intl.NumberFormat("pt-BR", { minimumFractionDigits: dec, maximumFractionDigits: dec });

let vendasDb = null;
let vendasProdutos = []; // todos os produtos, com campo de busca normalizado
let vendasFiltrados = []; // resultado da busca atual, já ordenado para exibição
let vendasCarrinho = []; // ids de produto, na ordem em que foram adicionados
let vendasClientes = []; // todos os clientes, com campo de busca normalizado
let vendasClienteAtivo = null; // cliente selecionado, ou null
let vendasConsumoCliente = null; // Map produto_id -> quantidade_total do cliente ativo, ou null

// linha do tempo (mesmo padrão da página Métricas de clientes, duplicado
// aqui de propósito): define o "mês vigente" usado para calcular a Oferta
// máxima de cada produto - não tem relação com o cliente ativo nem com a
// pontuação de sugestão, que continuam vindas só do histórico de co-compra.
let vendasMeses = []; // [{ anoMes: "1997-04", label: "04/97" }, ...], em ordem cronológica
let vendasMesSelecionado = null; // "YYYY-MM"
const vendasOfertasCache = new Map(); // ano_mes -> Map(produto_id -> maior_desconto)
let vendasUltimasSugestoes = []; // última lista renderizada, para redesenhar só a coluna de oferta ao trocar de mês

/* ── acesso ao banco ──────────────────────────────────────── */

function vendasQuery(db, sql, params) {
  const stmt = db.prepare(sql);
  if (params) stmt.bind(params);
  const linhas = [];
  while (stmt.step()) linhas.push(stmt.getAsObject());
  stmt.free();
  return linhas;
}

/* ── texto (busca sem acento, sem caixa) ─────────────────── */

function normalizarTexto(texto) {
  return (texto ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function vendasFormatarMesLabel(anoMes) {
  const [ano, mes] = anoMes.split("-");
  return `${mes}/${ano.slice(2)}`;
}

/* ── dados: linha do tempo e oferta máxima por mês ───────────
   Oferta máxima vem de gold.descontos (maior_desconto do produto no mês
   selecionado). Ela é só contexto para a negociação - não influencia o
   score de sugestão nem a ordenação dos produtos, que continuam vindos
   exclusivamente do histórico de co-compra. */

function carregarMesesOferta(db) {
  const linhas = vendasQuery(
    db,
    `SELECT DISTINCT ano_mes FROM ${TABELA_OFERTAS} ORDER BY ano_mes`
  );
  return linhas.map((r) => ({ anoMes: r.ano_mes, label: vendasFormatarMesLabel(r.ano_mes) }));
}

// todas as ofertas do mês pedido, de uma vez (evita uma consulta por
// produto); cacheado por mês, já que trocar de mês e voltar não deveria
// disparar nova consulta.
function carregarOfertasDoMes(db, anoMes) {
  if (vendasOfertasCache.has(anoMes)) return vendasOfertasCache.get(anoMes);

  const linhas = vendasQuery(
    db,
    `SELECT produto_id, maior_desconto FROM ${TABELA_OFERTAS} WHERE ano_mes = :ano_mes`,
    { ":ano_mes": anoMes }
  );
  const mapa = new Map(linhas.map((r) => [r.produto_id, r.maior_desconto]));
  vendasOfertasCache.set(anoMes, mapa);
  return mapa;
}

// oferta do produto no mês selecionado, ou undefined se não houver
// registro (nenhum mês escolhido ainda, ou o produto não teve linha em
// descontos naquele mês) - ver vendasFormatarOferta para o tratamento
// dessa ausência, diferente de um desconto de fato 0%.
function vendasOfertaProduto(produtoId) {
  if (!vendasMesSelecionado) return undefined;
  const mapa = carregarOfertasDoMes(vendasDb, vendasMesSelecionado);
  return mapa.get(produtoId);
}

// mesmos três estados de gold.descontos usados em Métricas de clientes
// (duplicado aqui de propósito): ausência de registro (produto sem linha
// de desconto naquele mês) é diferente de um desconto de fato 0%.
function vendasFormatarOferta(oferta) {
  if (oferta === null || oferta === undefined) {
    return { texto: "Sem oferta", classe: "sem-registro" };
  }
  if (oferta === 0) {
    return { texto: "Sem desconto", classe: "sem-desconto" };
  }
  return { texto: `${nfVendas(1).format(oferta * 100)}%`, classe: "ativa" };
}

function vendasCriarTagOferta(produtoId) {
  const oferta = vendasFormatarOferta(vendasOfertaProduto(produtoId));
  const span = document.createElement("span");
  span.className = `vendas-oferta vendas-oferta--${oferta.classe}`;
  span.textContent = oferta.texto;
  span.setAttribute(
    "aria-label",
    `Oferta máxima${vendasMesSelecionado ? ` em ${vendasFormatarMesLabel(vendasMesSelecionado)}` : ""}: ${oferta.texto}`
  );
  return span;
}

/* ── render: linha do tempo ───────────────────── */

function vendasRenderizarTimeline() {
  const box = document.getElementById("vendas-tempo");
  box.textContent = "";

  for (const m of vendasMeses) {
    const item = document.createElement("div");
    item.className = "vendas-tempo-item";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "vendas-tempo-marcador";
    btn.dataset.anoMes = m.anoMes;
    btn.setAttribute("aria-label", `Selecionar ${m.label}`);
    btn.addEventListener("click", () => vendasSelecionarMes(m.anoMes));

    const ponto = document.createElement("span");
    ponto.className = "vendas-tempo-ponto";
    btn.appendChild(ponto);

    const rotulo = document.createElement("span");
    rotulo.className = "vendas-tempo-rotulo";
    rotulo.textContent = m.label;

    item.append(btn, rotulo);
    box.appendChild(item);
  }
}

function vendasAtualizarMarcadoresAtivos() {
  const idx = vendasMeses.findIndex((m) => m.anoMes === vendasMesSelecionado);

  document.querySelectorAll(".vendas-tempo-marcador").forEach((btn) => {
    const selecionado = btn.dataset.anoMes === vendasMesSelecionado;
    btn.classList.toggle("selecionado", selecionado);
    if (selecionado) btn.setAttribute("aria-current", "date");
    else btn.removeAttribute("aria-current");
  });

  document.querySelectorAll(".vendas-tempo-rotulo").forEach((el, i) => {
    el.classList.toggle("vendas-tempo-rotulo--selecionado", i === idx);
  });
}

function vendasAtualizarSubtituloTempo() {
  const sub = document.getElementById("vendas-tempo-sub");
  if (!sub || !vendasMesSelecionado) return;
  sub.textContent = `Oferta máxima calculada para ${vendasFormatarMesLabel(vendasMesSelecionado)}`;
}

function vendasIniciarTecladoTimeline() {
  const box = document.getElementById("vendas-tempo");
  box.addEventListener("keydown", (ev) => {
    const idxAtual = vendasMeses.findIndex((m) => m.anoMes === vendasMesSelecionado);
    let novoIdx = null;
    if (ev.key === "ArrowLeft") novoIdx = Math.max(0, idxAtual - 1);
    else if (ev.key === "ArrowRight") novoIdx = Math.min(vendasMeses.length - 1, idxAtual + 1);
    else if (ev.key === "Home") novoIdx = 0;
    else if (ev.key === "End") novoIdx = vendasMeses.length - 1;
    if (novoIdx === null) return;

    ev.preventDefault();
    const anoMes = vendasMeses[novoIdx].anoMes;
    vendasSelecionarMes(anoMes);
    const btn = box.querySelector(`.vendas-tempo-marcador[data-ano-mes="${anoMes}"]`);
    if (btn) {
      btn.focus();
      btn.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  });
}

// trocar de mês só atualiza a coluna de Oferta máxima (carrinho e
// sugestões) - não recalcula o score de sugestão nem reordena nada, já
// que a oferta é só contexto para a negociação.
function vendasSelecionarMes(anoMes) {
  if (anoMes === vendasMesSelecionado) return;
  vendasMesSelecionado = anoMes;
  vendasAtualizarMarcadoresAtivos();
  vendasAtualizarSubtituloTempo();
  renderizarCarrinho();
  renderizarSugestoes(vendasUltimasSugestoes);
}

/* ── dados ────────────────────────────────────────────────── */

function carregarProdutos(db) {
  const linhas = vendasQuery(
    db,
    `SELECT produto_id, produto_nome, categoria_nome, fornecedor_nome,
            quantidade_por_unidade, preco_unitario, descontinuado
     FROM ${TABELA_PRODUTOS}
     ORDER BY produto_nome`
  );
  return linhas.map((p) => ({
    id: p.produto_id,
    nome: p.produto_nome,
    categoria: p.categoria_nome,
    fornecedor: p.fornecedor_nome,
    embalagem: p.quantidade_por_unidade,
    preco: p.preco_unitario,
    descontinuado: !!p.descontinuado,
    busca: normalizarTexto(`${p.produto_nome} ${p.categoria_nome ?? ""} ${p.fornecedor_nome ?? ""}`),
  }));
}

function filtrarProdutos(produtos, termo) {
  const alvo = normalizarTexto(termo);
  if (!alvo) return produtos;
  return produtos.filter((p) => p.busca.includes(alvo));
}

// produtos já consumidos pelo cliente primeiro (quantidade_total DESC,
// empate por nome) e os nunca consumidos depois (ordem alfabética). Sem
// cliente ativo, ordem alfabética simples. Um único comparador cobre os
// dois grupos: quando as quantidades empatam (inclusive 0 == 0), cai no
// desempate por nome.
function ordenarProdutosParaExibicao(produtos) {
  if (!vendasConsumoCliente) {
    return [...produtos].sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  }
  return [...produtos].sort((a, b) => {
    const qa = vendasConsumoCliente.get(a.id) ?? 0;
    const qb = vendasConsumoCliente.get(b.id) ?? 0;
    if (qa !== qb) return qb - qa;
    return a.nome.localeCompare(b.nome, "pt-BR");
  });
}

// filtra pelo texto e, em seguida, aplica a ordenação por consumo do
// cliente ativo (ou alfabética, sem cliente) - nessa ordem, sempre.
function vendasAtualizarListaProdutos() {
  const termo = document.getElementById("vendas-busca").value;
  const filtrados = filtrarProdutos(vendasProdutos, termo);
  renderizarProdutos(ordenarProdutosParaExibicao(filtrados));
}

function formatarConsumoCliente(produtoId) {
  if (!vendasConsumoCliente) return "-";
  const qtd = vendasConsumoCliente.get(produtoId) ?? 0;
  return `${nfVendas(0).format(qtd)} un.`;
}

/* ── clientes ─────────────────────────────────────────────── */

function carregarClientes(db) {
  const linhas = vendasQuery(
    db,
    `SELECT cliente_id, nome_empresa, nome_contato, cidade, pais
     FROM ${TABELA_CLIENTES}
     ORDER BY nome_empresa`
  );
  return linhas.map((c) => ({
    id: c.cliente_id,
    nomeEmpresa: c.nome_empresa,
    nomeContato: c.nome_contato,
    cidade: c.cidade,
    pais: c.pais,
    busca: normalizarTexto(
      `${c.cliente_id} ${c.nome_empresa} ${c.nome_contato ?? ""} ${c.cidade ?? ""} ${c.pais ?? ""}`
    ),
  }));
}

function filtrarClientes(clientes, termo) {
  const alvo = normalizarTexto(termo);
  if (!alvo) return [];
  return clientes.filter((c) => c.busca.includes(alvo)).slice(0, MAX_RESULTADOS_CLIENTE);
}

function formatarMetaCliente(c) {
  return [c.nomeContato, c.cidade, c.pais].filter(Boolean).join(" · ");
}

// consumo total do cliente por produto - sempre soma de quantidade_consumida,
// nunca contagem de linhas (uma linha é um mês; um produto pode aparecer em
// vários meses).
function carregarConsumoCliente(db, clienteId) {
  const linhas = vendasQuery(
    db,
    `SELECT produto_id, SUM(quantidade_consumida) AS quantidade_total
     FROM ${TABELA_HISTORICO_CLIENTE_PRODUTOS}
     WHERE cliente_id = :cliente_id
     GROUP BY produto_id`,
    { ":cliente_id": clienteId }
  );
  const mapa = new Map();
  for (const r of linhas) mapa.set(r.produto_id, r.quantidade_total);
  return mapa;
}

// trocar de cliente (selecionar um novo com outro já ativo) não limpa o
// carrinho - só troca o histórico de consumo usado para ordenar/anotar
// a lista de produtos e a coluna da tabela de sugestões.
function selecionarCliente(clienteId) {
  const cliente = vendasClientes.find((c) => c.id === clienteId);
  if (!cliente) return;

  vendasClienteAtivo = cliente;
  vendasConsumoCliente = carregarConsumoCliente(vendasDb, clienteId);

  document.getElementById("vendas-cliente-busca").value = "";
  vendasEsconderResultadosCliente();
  renderizarClienteAtivo();
  vendasAtualizarListaProdutos();
  recalcularSugestoes();
}

function limparClienteSelecionado() {
  vendasClienteAtivo = null;
  vendasConsumoCliente = null;
  renderizarClienteAtivo();
  vendasAtualizarListaProdutos();
  recalcularSugestoes();
}

function renderizarClienteAtivo() {
  const bloco = document.getElementById("vendas-cliente-ativo");
  if (!vendasClienteAtivo) {
    bloco.classList.add("hidden");
    return;
  }
  document.getElementById("vendas-cliente-ativo-empresa").textContent = vendasClienteAtivo.nomeEmpresa;
  document.getElementById("vendas-cliente-ativo-meta").textContent = formatarMetaCliente(vendasClienteAtivo);
  bloco.classList.remove("hidden");
}

function vendasEsconderResultadosCliente() {
  document.getElementById("vendas-cliente-resultados").classList.add("hidden");
}

function renderizarResultadosCliente(lista, termo) {
  const box = document.getElementById("vendas-cliente-resultados");
  box.textContent = "";

  if (!termo) {
    box.classList.add("hidden");
    return;
  }

  if (!lista.length) {
    const vazio = document.createElement("div");
    vazio.className = "vendas-cliente-resultado-vazio";
    vazio.textContent = "Nenhum cliente encontrado.";
    box.appendChild(vazio);
    box.classList.remove("hidden");
    return;
  }

  for (const c of lista) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "vendas-cliente-resultado-item";

    const empresa = document.createElement("div");
    empresa.className = "vendas-cliente-resultado-empresa";
    empresa.textContent = c.nomeEmpresa;

    const meta = document.createElement("div");
    meta.className = "vendas-cliente-resultado-meta";
    meta.textContent = formatarMetaCliente(c);

    item.append(empresa, meta);
    item.addEventListener("click", () => selecionarCliente(c.id));
    box.appendChild(item);
  }
  box.classList.remove("hidden");
}

// consulta os acompanhantes históricos de um produto do carrinho, já
// excluindo os que estão no carrinho e ordenados/limitados ao top 5
function consultarAssociacoesDoProduto(db, xId, idsExcluidos) {
  const totalRows = vendasQuery(
    db,
    `SELECT COUNT(DISTINCT id_compra) AS n
     FROM ${TABELA_ASSOCIACOES}
     WHERE produto_comprado_id = :x`,
    { ":x": xId }
  );
  const pedidosComX = totalRows.length ? totalRows[0].n : 0;
  if (pedidosComX === 0) return [];

  const pares = vendasQuery(
    db,
    `SELECT produto_acompanhante_id AS y_id, produto_acompanhante_nome AS y_nome,
            COUNT(DISTINCT id_compra) AS pedidos_com_x_e_y,
            COUNT(DISTINCT CASE
                WHEN quantidade_outros_produtos_distintos > 0 THEN id_compra
            END) AS pedidos_com_outros
     FROM ${TABELA_ASSOCIACOES}
     WHERE produto_comprado_id = :x AND produto_acompanhante_id IS NOT NULL
     GROUP BY produto_acompanhante_id, produto_acompanhante_nome`,
    { ":x": xId }
  );

  const candidatos = pares
    .filter((r) => !idsExcluidos.includes(r.y_id))
    .map((r) => {
      const pctAssociacao = (r.pedidos_com_x_e_y / pedidosComX) * 100;
      const pctOutros = r.pedidos_com_x_e_y > 0
        ? (r.pedidos_com_outros / r.pedidos_com_x_e_y) * 100
        : 0;
      return {
        yId: r.y_id,
        yNome: r.y_nome,
        pedidosComX, // N
        pedidosComXeY: r.pedidos_com_x_e_y, // M
        pedidosComOutros: r.pedidos_com_outros, // O
        pctAssociacao, // Z
        pctOutros,
      };
    });

  candidatos.sort((a, b) =>
    b.pctAssociacao - a.pctAssociacao ||
    a.pctOutros - b.pctOutros ||
    b.pedidosComXeY - a.pedidosComXeY ||
    a.yNome.localeCompare(b.yNome, "pt-BR"));

  return candidatos.slice(0, TOP_N_POR_PRODUTO);
}

// junta as listas top-5 de cada produto do carrinho quando o mesmo Y é
// sugerido por mais de um X. A associação combinada usa união
// probabilística (1 - produto dos complementos), não soma direta -
// senão duas origens fracas poderiam ultrapassar 100% facilmente.
// O "outros produtos" combinado é a média ponderada pela quantidade de
// pedidos conjuntos de cada origem, para que associações com mais
// pedidos pesem mais que associações com poucos pedidos.
//
// As duas métricas viram um único índice de oportunidade - um score de
// priorização, não uma probabilidade de compra - que penaliza sugestões
// cujos pedidos conjuntos quase sempre vieram com um terceiro produto
// no meio (associação_combinada × (1 - 0,25 × outros_combinado), com
// as duas parcelas em fração 0-1 antes de escalar de volta para pontos).
function combinarSugestoes(candidatosPorOrigem) {
  // yId -> { yId, yNome, origens: [{ nome, pedidosComX, pedidosComXeY, pctAssociacao, pedidosComOutros, pctOutros }] }
  const porProduto = new Map();

  for (const { origemNome, itens } of candidatosPorOrigem) {
    for (const item of itens) {
      if (!porProduto.has(item.yId)) {
        porProduto.set(item.yId, { yId: item.yId, yNome: item.yNome, origens: [] });
      }
      porProduto.get(item.yId).origens.push({
        nome: origemNome,
        pedidosComX: item.pedidosComX,
        pedidosComXeY: item.pedidosComXeY,
        pctAssociacao: item.pctAssociacao,
        pedidosComOutros: item.pedidosComOutros,
        pctOutros: item.pctOutros,
      });
    }
  }

  return Array.from(porProduto.values()).map((s) => {
    const complemento = s.origens.reduce((acc, o) => acc * (1 - o.pctAssociacao / 100), 1);
    const associacaoCombinada = Math.min(100, Math.max(0, (1 - complemento) * 100));

    const totalPedidosConjuntos = s.origens.reduce((acc, o) => acc + o.pedidosComXeY, 0);
    const mediaOutrosProdutos = totalPedidosConjuntos > 0
      ? s.origens.reduce((acc, o) => acc + o.pctOutros * o.pedidosComXeY, 0) / totalPedidosConjuntos
      : 0;

    const indiceOportunidade = associacaoCombinada * (1 - 0.25 * (mediaOutrosProdutos / 100));

    return {
      yId: s.yId,
      yNome: s.yNome,
      associacaoCombinada,
      mediaOutrosProdutos,
      indiceOportunidade,
      totalPedidosConjuntos,
      origens: s.origens, // dados individuais preservados p/ o tooltip explicativo
    };
  });
}

function ordenarSugestoes(lista) {
  return [...lista].sort((a, b) =>
    b.indiceOportunidade - a.indiceOportunidade ||
    b.totalPedidosConjuntos - a.totalPedidosConjuntos ||
    a.yNome.localeCompare(b.yNome, "pt-BR"));
}

/* ── carrinho ─────────────────────────────────────────────── */

function adicionarAoCarrinho(produtoId) {
  if (vendasCarrinho.includes(produtoId)) return;
  const produto = vendasProdutos.find((p) => p.id === produtoId);
  if (!produto) return;

  vendasCarrinho.push(produtoId);
  renderizarProdutos(vendasFiltrados);
  renderizarCarrinho();
  recalcularSugestoes();
}

function removerDoCarrinho(produtoId) {
  vendasCarrinho = vendasCarrinho.filter((id) => id !== produtoId);
  renderizarProdutos(vendasFiltrados);
  renderizarCarrinho();
  recalcularSugestoes();
}

function limparCarrinho() {
  vendasCarrinho = [];
  renderizarProdutos(vendasFiltrados);
  renderizarCarrinho();
  recalcularSugestoes();
}

function recalcularSugestoes() {
  if (!vendasCarrinho.length) {
    renderizarSugestoes([]);
    return;
  }

  const candidatosPorOrigem = vendasCarrinho.map((id) => {
    const produto = vendasProdutos.find((p) => p.id === id);
    return {
      origemId: id,
      origemNome: produto ? produto.nome : `#${id}`,
      itens: consultarAssociacoesDoProduto(vendasDb, id, vendasCarrinho),
    };
  });

  const combinadas = combinarSugestoes(candidatosPorOrigem);
  renderizarSugestoes(ordenarSugestoes(combinadas));
}

/* ── render: lista de produtos ───────────────────────────── */

function renderizarProdutos(produtos) {
  vendasFiltrados = produtos;

  const contagem = document.getElementById("vendas-lista-contagem");
  contagem.textContent = produtos.length === vendasProdutos.length
    ? `${nfVendas(0).format(produtos.length)} produtos`
    : `${nfVendas(0).format(produtos.length)} de ${nfVendas(0).format(vendasProdutos.length)} produtos`;

  const box = document.getElementById("vendas-lista");
  box.textContent = "";

  if (!produtos.length) {
    const vazio = document.createElement("div");
    vazio.className = "vendas-empty";
    vazio.textContent = "Nenhum produto encontrado para essa busca.";
    box.appendChild(vazio);
    return;
  }

  for (const p of produtos) {
    const noCarrinho = vendasCarrinho.includes(p.id);

    const row = document.createElement("div");
    row.className = "vendas-row";

    const info = document.createElement("div");
    info.className = "vendas-row-info";
    const nome = document.createElement("span");
    nome.className = "vendas-row-nome";
    nome.textContent = p.nome;
    const meta = document.createElement("span");
    meta.className = "vendas-row-meta";
    meta.textContent = `${p.categoria} · ${p.embalagem}`;
    info.append(nome, meta);

    const consumo = document.createElement("div");
    consumo.className = "vendas-row-consumo";
    const consumoLabel = document.createElement("span");
    consumoLabel.className = "vendas-row-consumo-label";
    consumoLabel.textContent = "Consumo do cliente";
    const consumoValor = document.createElement("span");
    consumoValor.className = "vendas-row-consumo-valor";
    consumoValor.textContent = formatarConsumoCliente(p.id);
    consumo.append(consumoLabel, consumoValor);

    const metrics = document.createElement("div");
    metrics.className = "vendas-row-metrics";
    const preco = document.createElement("span");
    preco.className = "vendas-row-preco";
    preco.textContent = nfVendas(2).format(p.preco);
    metrics.append(preco);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "vendas-btn";
    if (noCarrinho) {
      btn.textContent = "No carrinho";
      btn.disabled = true;
    } else {
      btn.textContent = "Adicionar";
      btn.addEventListener("click", () => adicionarAoCarrinho(p.id));
    }

    row.append(info, consumo, metrics, btn);
    box.appendChild(row);
  }
}

/* ── render: carrinho ─────────────────────────────────────── */

function renderizarCarrinho() {
  const contagem = document.getElementById("vendas-carrinho-contagem");
  const n = vendasCarrinho.length;
  contagem.textContent = n === 1 ? "1 produto no carrinho" : `${nfVendas(0).format(n)} produtos no carrinho`;

  const box = document.getElementById("vendas-carrinho");
  box.textContent = "";

  if (!n) {
    const vazio = document.createElement("div");
    vazio.className = "vendas-empty";
    vazio.textContent = "Adicione produtos para montar a negociação.";
    box.appendChild(vazio);
    return;
  }

  for (const id of vendasCarrinho) {
    const p = vendasProdutos.find((prod) => prod.id === id);
    if (!p) continue;

    const row = document.createElement("div");
    row.className = "vendas-row";

    const info = document.createElement("div");
    info.className = "vendas-row-info";
    const nome = document.createElement("span");
    nome.className = "vendas-row-nome";
    nome.textContent = p.nome;
    const meta = document.createElement("span");
    meta.className = "vendas-row-meta";
    meta.textContent = p.categoria;
    info.append(nome, meta);

    const preco = document.createElement("span");
    preco.className = "vendas-row-preco";
    preco.textContent = nfVendas(2).format(p.preco);

    const oferta = document.createElement("div");
    oferta.className = "vendas-row-oferta";
    const ofertaLabel = document.createElement("span");
    ofertaLabel.className = "vendas-row-oferta-label";
    ofertaLabel.textContent = "Oferta máxima";
    oferta.append(ofertaLabel, vendasCriarTagOferta(id));

    const btnRemover = document.createElement("button");
    btnRemover.type = "button";
    btnRemover.className = "vendas-btn-remove";
    btnRemover.textContent = "×";
    btnRemover.setAttribute("aria-label", `Remover ${p.nome} do carrinho`);
    btnRemover.addEventListener("click", () => removerDoCarrinho(id));

    row.append(info, preco, oferta, btnRemover);
    box.appendChild(row);
  }
}

/* ── render: sugestões ───────────────────────────────────── */

function renderizarSugestoes(lista) {
  vendasUltimasSugestoes = lista;

  const box = document.getElementById("vendas-sugestoes");
  box.textContent = "";

  if (!vendasCarrinho.length) {
    const vazio = document.createElement("div");
    vazio.className = "vendas-empty";
    vazio.textContent = "Adicione um produto ao carrinho para receber sugestões.";
    box.appendChild(vazio);
    return;
  }

  if (!lista.length) {
    const vazio = document.createElement("div");
    vazio.className = "vendas-empty";
    vazio.textContent = "Nenhuma associação encontrada para os produtos do carrinho.";
    box.appendChild(vazio);
    return;
  }

  // tabela enxuta: uma linha por sugestão (~64-80px), sem cards altos
  const table = document.createElement("table");
  table.className = "vendas-sug-table";

  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  const th = (texto, extraClass, titulo) => {
    const el = document.createElement("th");
    if (extraClass) el.className = extraClass;
    el.textContent = texto;
    if (titulo) el.title = titulo;
    return el;
  };
  trh.append(
    th("Produto"),
    th("Score", "num", "Pontuação de priorização, não uma probabilidade de compra - passe o mouse ou dê foco na linha para o detalhamento completo"),
    th("Consumo do cliente", "num", "Quantidade que o cliente ativo já consumiu deste produto - apenas contexto, não influencia o score"),
    th("Oferta máxima", "num", "Maior desconto observado para este produto no mês selecionado na linha do tempo - não influencia o score"),
    th("", "acao"),
  );
  thead.appendChild(trh);

  const tbody = document.createElement("tbody");
  for (const s of lista) {
    const produto = vendasProdutos.find((p) => p.id === s.yId);
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.setAttribute("role", "button");
    tr.setAttribute("aria-label", `Por que ${s.yNome} foi sugerido`);

    const tdProduto = document.createElement("td");
    const nome = document.createElement("div");
    nome.className = "vendas-sug-nome";
    nome.textContent = s.yNome;
    nome.title = s.yNome;
    tdProduto.appendChild(nome);
    if (produto) {
      const meta = document.createElement("div");
      meta.className = "vendas-sug-meta";
      meta.textContent = produto.categoria;
      tdProduto.appendChild(meta);
    }

    const tdIndice = document.createElement("td");
    tdIndice.className = "num";
    const indiceVal = document.createElement("span");
    indiceVal.className = "vendas-sug-num";
    indiceVal.textContent = `${nfVendas(1).format(s.indiceOportunidade)} pts`;
    tdIndice.appendChild(indiceVal);

    const tdConsumo = document.createElement("td");
    tdConsumo.className = "num vendas-sug-consumo";
    tdConsumo.textContent = formatarConsumoCliente(s.yId);

    const tdOferta = document.createElement("td");
    tdOferta.className = "num";
    tdOferta.appendChild(vendasCriarTagOferta(s.yId));

    const tdAcao = document.createElement("td");
    tdAcao.className = "acao";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "vendas-btn-sm";
    btn.textContent = "Adicionar";
    btn.addEventListener("click", () => adicionarAoCarrinho(s.yId));
    tdAcao.appendChild(btn);

    tr.append(tdProduto, tdIndice, tdConsumo, tdOferta, tdAcao);
    vendasLigarTooltipLinha(tr, s);
    tbody.appendChild(tr);
  }

  table.append(thead, tbody);
  box.appendChild(table);
}

/* ── tooltip explicativo da sugestão ──────────────────────── */
// Explica em linguagem simples por que cada Y foi sugerido, usando os
// nomes reais dos produtos (nunca "X"/"Y" na interface) e, no final,
// a mesma fórmula usada em combinarSugestoes com os valores reais
// substituídos - só para leitura; o cálculo em si já foi feito antes,
// sem arredondamento, em indiceOportunidade/associacaoCombinada/etc.

let vendasTooltipSobreLinha = false;
let vendasTooltipSobreTooltip = false;
let vendasTooltipFecharTimer = null;

function vendasInterpretarSomenteOsDois(pedidosSomente, pctSomente) {
  if (pedidosSomente === 0) {
    return "Sempre que esses dois produtos foram comprados juntos, havia outros produtos no pedido. " +
      "Isso mostra que eles aparecem juntos, mas não permite afirmar que um está diretamente ligado ao outro.";
  }

  if (pctSomente >= 70) {
    return "Na maioria das vezes em que foram comprados juntos, o pedido tinha somente esses dois produtos. " +
      "Isso é um sinal mais forte de que um produto costuma acompanhar o outro.";
  }

  if (pctSomente >= 40) {
    return "Em alguns pedidos, somente esses dois produtos foram comprados. Em outros, havia mais produtos. " +
      "Eles possuem uma relação, mas ela ainda não é tão clara.";
  }

  return "Na maioria das vezes, esses dois produtos apareceram em pedidos com vários outros itens. " +
    "Eles são comprados juntos, mas isso pode acontecer por fazerem parte de compras maiores.";
}

function vendasCriarLinha(classe, texto) {
  const el = document.createElement("p");
  el.className = classe;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

// explicação completa de UMA origem (produto X do carrinho) para UM
// produto sugerido (Y): quantos pedidos tinham X, quantos tinham X e Y,
// e como esses pedidos se dividem entre "só os dois" e "com outros
// produtos junto". Usada tanto para uma única origem quanto, repetida,
// para cada origem quando várias sugerem o mesmo Y - ambos os casos
// devem ter a mesma riqueza de informação, então essa é a única versão.
function vendasRenderizarExplicacaoOrigem(o, yNome) {
  const frag = document.createDocumentFragment();
  const pedidosSomente = o.pedidosComXeY - o.pedidosComOutros;
  const pctSomente = o.pedidosComXeY > 0 ? (pedidosSomente / o.pedidosComXeY) * 100 : 0;

  frag.appendChild(vendasCriarLinha("vt-paragrafo",
    `${o.nome} apareceu em ${nfVendas(0).format(o.pedidosComX)} pedidos. Em ${nfVendas(0).format(o.pedidosComXeY)} ` +
    `deles, ${yNome} também foi comprado. Isso representa ${nfVendas(1).format(o.pctAssociacao)}% dos pedidos ` +
    `com ${o.nome}.`));

  frag.appendChild(vendasCriarLinha("vt-paragrafo",
    `Entre ${o.pedidosComXeY === 1 ? "esse pedido" : `esses ${nfVendas(0).format(o.pedidosComXeY)} pedidos`}:`));

  const ul = document.createElement("ul");
  ul.className = "vt-lista";
  const liOutros = document.createElement("li");
  liOutros.textContent =
    `${nfVendas(0).format(o.pedidosComOutros)} ${o.pedidosComOutros === 1 ? "pedido" : "pedidos"}, ou ` +
    `${nfVendas(1).format(o.pctOutros)}%, também ${o.pedidosComOutros === 1 ? "continha" : "continham"} outros produtos;`;
  const liSomente = document.createElement("li");
  liSomente.textContent =
    `${nfVendas(0).format(pedidosSomente)} ${pedidosSomente === 1 ? "pedido" : "pedidos"}, ou ` +
    `${nfVendas(1).format(pctSomente)}%, ${pedidosSomente === 1 ? "continha" : "continham"} somente esses dois produtos.`;
  ul.append(liOutros, liSomente);
  frag.appendChild(ul);

  frag.appendChild(vendasCriarLinha("vt-paragrafo vt-interpretacao",
    vendasInterpretarSomenteOsDois(pedidosSomente, pctSomente)));

  return frag;
}

// seção "por que foi sugerido": para uma única origem, a explicação
// completa direto; para várias, uma seção completa e separada por
// origem - nunca a frase resumida "N de M pedidos... -Z%."
function vendasMontarSecaoOrigens(s) {
  const frag = document.createDocumentFragment();
  frag.appendChild(vendasCriarLinha("vt-titulo", "Por que este produto foi sugerido?"));

  if (s.origens.length === 1) {
    frag.appendChild(vendasRenderizarExplicacaoOrigem(s.origens[0], s.yNome));
  } else {
    frag.appendChild(vendasCriarLinha("vt-paragrafo",
      `Este produto foi sugerido por sua relação com ${nfVendas(0).format(s.origens.length)} produtos do ` +
      `carrinho. Abaixo está a evidência de cada relação.`));

    s.origens.forEach((o, i) => {
      const bloco = document.createElement("div");
      bloco.className = "vt-relacao";
      const titulo = document.createElement("div");
      titulo.className = "vt-relacao-titulo";
      titulo.textContent = `Relação ${i + 1}: ${o.nome} → ${s.yNome}`;
      bloco.appendChild(titulo);
      bloco.appendChild(vendasRenderizarExplicacaoOrigem(o, s.yNome));
      frag.appendChild(bloco);
    });
  }

  return frag;
}

function vendasFormula(rotulo, expressao) {
  const p = document.createElement("p");
  p.className = "vt-formula";
  const lb = document.createElement("span");
  lb.className = "vt-formula-label";
  lb.textContent = rotulo;
  p.append(lb, document.createTextNode(expressao));
  return p;
}

function vendasListaBullets(itens) {
  const ul = document.createElement("ul");
  ul.className = "vt-lista";
  for (const texto of itens) {
    const li = document.createElement("li");
    li.textContent = texto;
    ul.appendChild(li);
  }
  return ul;
}

function vendasNumeroExtenso(n) {
  const nomes = { 2: "dois", 3: "três", 4: "quatro", 5: "cinco" };
  return nomes[n] ?? nfVendas(0).format(n);
}

// conclusão em linguagem simples do cálculo combinado (só p/ múltiplas origens)
function vendasConclusaoScore(s) {
  const inicio =
    `Os ${vendasNumeroExtenso(s.origens.length)} produtos do carrinho apontaram para ${s.yNome}, ` +
    `aumentando a força combinada da sugestão para ${nfVendas(1).format(s.associacaoCombinada)}%.`;

  if (s.mediaOutrosProdutos <= 0) {
    return `${inicio} Nenhuma dessas compras conjuntas aconteceu em pedidos maiores, então o score ` +
      `manteve-se em ${nfVendas(1).format(s.indiceOportunidade)} pontos.`;
  }
  return `${inicio} Como ${nfVendas(1).format(s.mediaOutrosProdutos)}% dessas compras conjuntas aconteceram ` +
    `em pedidos maiores, o score recebeu uma redução e terminou em ${nfVendas(1).format(s.indiceOportunidade)} pontos.`;
}

// seção técnica: mesma fórmula de combinarSugestoes, com os valores reais
// substituídos e arredondados só para exibição (o cálculo em si já foi
// feito à parte, sem arredondamento, em s.associacaoCombinada/mediaOutrosProdutos/indiceOportunidade).
// Para uma única origem, a explicação de 3 linhas de sempre; para várias,
// mostra também os números individuais que alimentaram cada etapa.
function vendasMontarSecaoScore(s) {
  const frag = document.createDocumentFragment();
  frag.appendChild(vendasCriarLinha("vt-titulo", "Como o score foi calculado"));

  if (s.origens.length === 1) {
    const o = s.origens[0];
    frag.appendChild(vendasFormula("Associação combinada: ",
      `1 − (1 − ${nfVendas(3).format(o.pctAssociacao / 100)}) = ${nfVendas(1).format(s.associacaoCombinada)}%`));
    frag.appendChild(vendasFormula("Outros produtos combinado: ",
      `(${nfVendas(1).format(o.pctOutros)}% × ${nfVendas(0).format(o.pedidosComXeY)}) ÷ ` +
      `${nfVendas(0).format(o.pedidosComXeY)} = ${nfVendas(1).format(s.mediaOutrosProdutos)}%`));
    frag.appendChild(vendasFormula("Score final: ",
      `${nfVendas(1).format(s.associacaoCombinada)} × (1 − 0,25 × ${nfVendas(3).format(s.mediaOutrosProdutos / 100)}) = ` +
      `${nfVendas(1).format(s.indiceOportunidade)} pontos`));
    return frag;
  }

  frag.appendChild(vendasCriarLinha("vt-subtitulo", "Associações individuais:"));
  frag.appendChild(vendasListaBullets(s.origens.map((o) =>
    `${o.nome} → ${s.yNome}: ${nfVendas(0).format(o.pedidosComXeY)} ÷ ${nfVendas(0).format(o.pedidosComX)} = ` +
    `${nfVendas(1).format(o.pctAssociacao)}%`)));

  frag.appendChild(vendasCriarLinha("vt-subtitulo", "Associação combinada:"));
  const termosAssoc = s.origens.map((o) => `(1 − ${nfVendas(3).format(o.pctAssociacao / 100)})`).join(" × ");
  frag.appendChild(vendasCriarLinha("vt-formula",
    `1 − (${termosAssoc}) = ${nfVendas(1).format(s.associacaoCombinada)}%`));

  frag.appendChild(vendasCriarLinha("vt-subtitulo", "Pedidos com outros produtos:"));
  frag.appendChild(vendasListaBullets(s.origens.map((o) =>
    `${o.nome} → ${s.yNome}: ${nfVendas(0).format(o.pedidosComOutros)} de ${nfVendas(0).format(o.pedidosComXeY)} = ` +
    `${nfVendas(1).format(o.pctOutros)}%`)));

  frag.appendChild(vendasCriarLinha("vt-subtitulo", "Outros produtos combinado:"));
  const numerador = s.origens.map((o) => `(${nfVendas(1).format(o.pctOutros)}% × ${nfVendas(0).format(o.pedidosComXeY)})`).join(" + ");
  const denominador = s.origens.map((o) => nfVendas(0).format(o.pedidosComXeY)).join(" + ");
  frag.appendChild(vendasCriarLinha("vt-formula",
    `(${numerador}) ÷ (${denominador}) = ${nfVendas(1).format(s.mediaOutrosProdutos)}%`));

  frag.appendChild(vendasCriarLinha("vt-subtitulo", "Score final:"));
  frag.appendChild(vendasCriarLinha("vt-formula",
    `${nfVendas(1).format(s.associacaoCombinada)} × (1 − 0,25 × ${nfVendas(3).format(s.mediaOutrosProdutos / 100)}) = ` +
    `${nfVendas(1).format(s.indiceOportunidade)} pontos`));

  frag.appendChild(vendasCriarLinha("vt-paragrafo vt-conclusao", vendasConclusaoScore(s)));

  return frag;
}

function vendasMontarTooltip(s) {
  const frag = document.createDocumentFragment();
  frag.appendChild(vendasMontarSecaoOrigens(s));
  frag.appendChild(document.createElement("hr")).className = "vt-sep";
  frag.appendChild(vendasMontarSecaoScore(s));
  return frag;
}

function vendasPosicionarTooltip(el, ancoraRect) {
  const pad = 10;
  const tw = el.offsetWidth;
  const th = el.offsetHeight;

  let x = ancoraRect.right - tw;
  if (x < pad) x = pad;
  if (x + tw > window.innerWidth - pad) x = window.innerWidth - pad - tw;

  let y = ancoraRect.bottom + 2;
  if (y + th > window.innerHeight - pad) {
    y = ancoraRect.top - th - 2;
    if (y < pad) y = pad;
  }

  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
}

function vendasMostrarTooltipLinha(tr, s) {
  const tt = document.getElementById("vendas-tooltip");
  tt.textContent = "";
  tt.appendChild(vendasMontarTooltip(s));
  tt.classList.remove("hidden");
  vendasPosicionarTooltip(tt, tr.getBoundingClientRect());
}

function vendasEsconderTooltip() {
  document.getElementById("vendas-tooltip").classList.add("hidden");
}

function vendasAgendarFecharTooltip() {
  clearTimeout(vendasTooltipFecharTimer);
  vendasTooltipFecharTimer = setTimeout(() => {
    if (!vendasTooltipSobreLinha && !vendasTooltipSobreTooltip) vendasEsconderTooltip();
  }, 120);
}

// liga hover (mouse) e foco (teclado) na linha da sugestão; fecha ao
// sair com o mouse (com folga pra alcançar o próprio tooltip), Esc, ou
// perder o foco - sem interferir no clique do botão "Adicionar"
function vendasLigarTooltipLinha(tr, s) {
  const abrir = () => {
    vendasTooltipSobreLinha = true;
    vendasMostrarTooltipLinha(tr, s);
  };
  tr.addEventListener("pointerenter", abrir);
  tr.addEventListener("focus", abrir);
  tr.addEventListener("pointerleave", () => {
    vendasTooltipSobreLinha = false;
    vendasAgendarFecharTooltip();
  });
  tr.addEventListener("blur", () => {
    vendasTooltipSobreLinha = false;
    vendasEsconderTooltip();
  });
}

function vendasIniciarTooltipGlobal() {
  const tt = document.getElementById("vendas-tooltip");
  tt.addEventListener("pointerenter", () => { vendasTooltipSobreTooltip = true; });
  tt.addEventListener("pointerleave", () => {
    vendasTooltipSobreTooltip = false;
    vendasAgendarFecharTooltip();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !tt.classList.contains("hidden")) vendasEsconderTooltip();
  });
}

/* ── erro ─────────────────────────────────────────────────── */

window.mostrarErroVendas = function mostrarErroVendas(msg) {
  const box = document.getElementById("vendas-error");
  box.classList.remove("hidden");
  box.textContent = msg;

  const listaBox = document.getElementById("vendas-lista");
  listaBox.textContent = "";
  const vazio = document.createElement("div");
  vazio.className = "vendas-empty";
  vazio.textContent = "Não foi possível carregar os produtos.";
  listaBox.appendChild(vazio);
};

/* ── init ─────────────────────────────────────────────────── */

function vendasIniciarBuscaCliente() {
  const wrap = document.getElementById("vendas-cliente-busca-wrap");
  const campoCliente = document.getElementById("vendas-cliente-busca");

  campoCliente.addEventListener("input", (ev) => {
    const termo = ev.target.value.trim();
    renderizarResultadosCliente(filtrarClientes(vendasClientes, termo), termo);
  });
  campoCliente.addEventListener("focus", (ev) => {
    const termo = ev.target.value.trim();
    if (termo) renderizarResultadosCliente(filtrarClientes(vendasClientes, termo), termo);
  });

  document.addEventListener("click", (ev) => {
    if (!wrap.contains(ev.target)) vendasEsconderResultadosCliente();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") vendasEsconderResultadosCliente();
  });

  document.getElementById("vendas-cliente-limpar").addEventListener("click", limparClienteSelecionado);
}

window.iniciarVendas = function iniciarVendas(db) {
  try {
    vendasDb = db;
    vendasProdutos = carregarProdutos(db);
    vendasClientes = carregarClientes(db);
  } catch (err) {
    console.warn("vendas: falha ao carregar produtos -", err.message);
    window.mostrarErroVendas(`Não foi possível carregar os produtos. Detalhe: ${err.message}`);
    return;
  }

  // linha do tempo de ofertas: falha aqui não deve travar o resto da
  // página - só a coluna/tag de Oferta máxima fica indisponível.
  try {
    vendasMeses = carregarMesesOferta(db);
  } catch (err) {
    console.warn("vendas: falha ao carregar linha do tempo de ofertas -", err.message);
    vendasMeses = [];
  }

  if (vendasMeses.length) {
    vendasRenderizarTimeline();
    vendasIniciarTecladoTimeline();
    vendasMesSelecionado = vendasMeses[vendasMeses.length - 1].anoMes;
    vendasAtualizarMarcadoresAtivos();
    vendasAtualizarSubtituloTempo();
  } else {
    const sub = document.getElementById("vendas-tempo-sub");
    if (sub) sub.textContent = "Nenhum dado de oferta disponível.";
  }

  vendasAtualizarListaProdutos();
  renderizarCarrinho();
  renderizarSugestoes([]);
  renderizarClienteAtivo();
  vendasIniciarTooltipGlobal();
  vendasIniciarBuscaCliente();

  const campoBusca = document.getElementById("vendas-busca");
  campoBusca.addEventListener("input", vendasAtualizarListaProdutos);

  document.getElementById("vendas-limpar").addEventListener("click", limparCarrinho);
};
