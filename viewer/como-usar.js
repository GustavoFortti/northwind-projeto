/* Página "Como usar o sistema?" - renderiza docs/sistema.md (que já inclui
   o diagrama exportado do Excalidraw como imagem). Não depende do
   sql.js/data.sqlite - inicia direto, sem esperar bi.js. */
"use strict";

/* ── documento: parser mínimo de Markdown -> DOM ──────────────
   Cobre só o subconjunto usado em docs/sistema.md: headings (#/##/###),
   parágrafos, listas (- e 1.), **negrito**, [links](url) e ![imagens](src).
   Nunca usa innerHTML com o conteúdo do arquivo - tudo é construído via
   createElement/textContent, igual ao resto do Viewer. */

// docs/sistema.md referencia arquivos irmãos com caminho relativo à própria
// pasta docs/ (./sistema.svg, ./Recomendação de produtos.png) - como o
// documento é inserido na página principal (viewer/index.html), o caminho
// precisa ser reancorado para "docs/..." antes de virar src/href. Também
// aceita a forma "<caminho>" do Markdown (destino entre `<` `>`, usada por
// alguns editores para caminhos com espaço/acento), removendo os colchetes
// antes de resolver.
function comoUsarResolveCaminho(url) {
  const limpo = url.trim().replace(/^<(.*)>$/, "$1");
  if (/^[a-z][a-z0-9+.-]*:/i.test(limpo) || limpo.startsWith("/") || limpo.startsWith("#")) return limpo;
  return `docs/${limpo.replace(/^\.\//, "")}`;
}

// aplica **negrito** e [texto](link) dentro de um bloco de texto plano,
// anexando nós de texto/elementos ao container (nunca innerHTML).
function comoUsarParseInline(texto, container) {
  const regra = /\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)]+)\)/g;
  let ultimo = 0;
  let m;
  while ((m = regra.exec(texto))) {
    if (m.index > ultimo) container.appendChild(document.createTextNode(texto.slice(ultimo, m.index)));
    if (m[1] !== undefined) {
      const strong = document.createElement("strong");
      strong.textContent = m[1];
      container.appendChild(strong);
    } else {
      const a = document.createElement("a");
      a.href = comoUsarResolveCaminho(m[3]);
      a.textContent = m[2];
      if (/^[a-z][a-z0-9+.-]*:/i.test(m[3])) {
        a.target = "_blank";
        a.rel = "noopener";
      }
      container.appendChild(a);
    }
    ultimo = regra.lastIndex;
  }
  if (ultimo < texto.length) container.appendChild(document.createTextNode(texto.slice(ultimo)));
}

function comoUsarMontarImagem(alt, src) {
  const img = document.createElement("img");
  img.src = comoUsarResolveCaminho(src);
  img.alt = alt;
  img.loading = "lazy";
  return img;
}

// um bloco (parágrafo/lista/heading) vira um ou mais elementos, na ordem
// em que aparecem no documento.
function comoUsarMontarBloco(linhas) {
  const primeira = linhas[0];

  const heading = primeira.match(/^(#{1,3})\s+(.*)$/);
  if (heading) {
    const el = document.createElement(`h${heading[1].length}`);
    comoUsarParseInline(heading[2], el);
    return [el];
  }

  const imagemSozinha = linhas.length === 1 && primeira.trim().match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
  if (imagemSozinha) {
    return [comoUsarMontarImagem(imagemSozinha[1], imagemSozinha[2])];
  }

  const ehItemLista = (l) => /^[-*]\s+/.test(l) || /^\d+\.\s+/.test(l);
  if (linhas.every(ehItemLista)) {
    const ordenada = /^\d+\.\s+/.test(primeira);
    const lista = document.createElement(ordenada ? "ol" : "ul");
    for (const linha of linhas) {
      const texto = linha.replace(/^([-*]|\d+\.)\s+/, "");
      const li = document.createElement("li");
      comoUsarParseInline(texto, li);
      lista.appendChild(li);
    }
    return [lista];
  }

  const p = document.createElement("p");
  comoUsarParseInline(linhas.join(" "), p);
  return [p];
}

function comoUsarMarkdownParaDom(md) {
  const frag = document.createDocumentFragment();
  const blocos = md
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((b) => b.split("\n").filter((l) => l.trim() !== ""))
    .filter((linhas) => linhas.length > 0);

  for (const linhas of blocos) {
    for (const el of comoUsarMontarBloco(linhas)) frag.appendChild(el);
  }
  return frag;
}

async function comoUsarCarregarDocumento() {
  const box = document.getElementById("como-usar-doc");
  try {
    const resp = await fetch("docs/sistema.md");
    if (!resp.ok) throw new Error(`HTTP ${resp.status} ao buscar docs/sistema.md`);
    const md = await resp.text();
    box.textContent = "";
    box.appendChild(comoUsarMarkdownParaDom(md));
  } catch (err) {
    box.textContent = "";
    const vazio = document.createElement("div");
    vazio.className = "metricas-empty";
    vazio.textContent = `Não foi possível carregar o documento. Detalhe: ${err.message}`;
    box.appendChild(vazio);
  }
}

/* ── init ─────────────────────────────────────────────────── */

comoUsarCarregarDocumento();
