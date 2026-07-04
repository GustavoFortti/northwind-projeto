/* Carregamento do banco e navegação entre páginas do Viewer.
   Abre viewer/data.sqlite uma única vez (sql.js/WASM) e repassa a conexão
   para cada página via window.iniciarX(db); precisa ser servido via HTTP
   (ex.: python3 -m http.server na pasta viewer/) - aberto direto via file://
   o browser bloqueia o fetch do .sqlite/.wasm. */
"use strict";

/* ── navegação entre páginas ─────────────────────────────── */

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) =>
      b.classList.toggle("active", b === btn));
    const page = btn.dataset.page;
    document.getElementById("page-vendas").classList.toggle("hidden", page !== "vendas");
    document.getElementById("page-metricas-clientes").classList.toggle("hidden", page !== "metricas-clientes");
  });
});

/* ── carregamento único do banco ──────────────────────────── */

async function carregar() {
  const SQL = await initSqlJs({ locateFile: (f) => "lib/" + f });
  const resp = await fetch("data.sqlite");
  if (!resp.ok) throw new Error(`HTTP ${resp.status} ao buscar data.sqlite`);
  const db = new SQL.Database(new Uint8Array(await resp.arrayBuffer()));
  return db;
}

carregar()
  .then((db) => {
    if (window.iniciarVendas) window.iniciarVendas(db);
    if (window.iniciarMetricasClientes) window.iniciarMetricasClientes(db);
  })
  .catch((err) => {
    const msg =
      "Não foi possível ler data.sqlite - sirva a pasta viewer/ por HTTP " +
      "(ex.: python3 -m http.server 8080) e abra http://localhost:8080. " +
      `Detalhe: ${err.message}`;
    if (window.mostrarErroVendas) window.mostrarErroVendas(msg);
    if (window.mostrarErroMetricasClientes) window.mostrarErroMetricasClientes(msg);
  });
