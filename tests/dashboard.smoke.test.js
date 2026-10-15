// Headless smoke test: runs dashboard/app.js in a fake DOM with a mocked API and checks that the
// AAPL view and a no-model view (NVDA) render without errors. node tests/dashboard.smoke.test.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const src = fs.readFileSync(path.join(__dirname, "..", "dashboard", "app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "dashboard", "index.html"), "utf8");
const ids = [...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);
const modelOnly = (html.match(/class="card model-only"/g) || []).length;

function makeEnv(symbol) {
  const els = {};
  for (const id of ids) els[id] = { id, innerHTML: "", textContent: "", hidden: false, checked: id === "show-bands", value: "", className: "" };
  const modelEls = Array.from({ length: modelOnly }, () => ({ hidden: false }));
  const calls = [];
  const prices = Array.from({ length: 30 }, (_, i) => ({ trade_date: `2026-09-${String(i + 1).padStart(2, "0")}`, close: 300 + i }));
  const bodies = {
    "/prices": { note: "real", synthetic_rows_excluded: 0, prices },
    "/prices/latest": { latest: prices[29], previous: prices[28] },
    "/prices/synthetic": { prices: [] },
    "/signals": { signals: [{ trade_date: "2026-09-30", sma_20: 1, sma_50: 2, rsi_14: 50, volatility_20d_pct: 1, macd: 1, macd_signal: 2, macd_hist: -1, bb_lower: 290, bb_upper: 330, bb_pct_b: 0.5 }] },
    "/alerts": { alerts: [{ trade_date: "2026-09-30", alerts: [{ type: "MACD_CROSS", detail: "x" }], notified: true, test_alert: false }] },
    "/predictions/latest": { prediction: { predicted_close: 331, predicted_change_pct: 1, last_close: 329, as_of_date: "2026-09-30", inputs_outside_scaler_range: true } },
    "/predictions": { predictions: [{ as_of_date: "2026-09-29", predicted_close: 330, actual_date: "2026-09-30", actual_close: 329, error: 1 }] },
    "/evaluation": null,
    "/model-health": { live: { scored_days: 1, min_days_for_verdict: 20, beats_baseline: null, all: { days: 1 }, rolling: { days: 1 } }, days: [{ actual_date: "2026-09-30", error: 1, naive_error: 0.5 }], backtest: null },
  };
  const listeners = {};
  const ctx = {
    window: null, console,
    STOCK_CONFIG: { apiBase: "https://api.example", symbol, watchlist: ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"], modelSymbols: ["AAPL"] },
    StockAuth: { token: () => "t", user: () => "tester", handleCallback: async () => {}, login() {}, logout() {} },
    Chart: class { constructor(el, cfg) { ctx.charts[el.id] = cfg; } destroy() {} }, charts: {},
    document: {
      getElementById: (id) => { assert.ok(els[id], `missing element #${id}`); return els[id]; },
      querySelectorAll: (sel) => (sel === ".model-only" ? modelEls : []),
      documentElement: {},
      addEventListener: (ev, fn) => { listeners[ev] = fn; },
    },
    getComputedStyle: () => ({ getPropertyValue: () => "#000" }),
    fetch: async (url) => {
      const u = new URL(url);
      calls.push(u.pathname + "?" + u.searchParams.get("symbol"));
      const body = bodies[u.pathname];
      return { status: body == null ? 404 : 200, ok: body != null, json: async () => body };
    },
  };
  ctx.window = ctx; ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return { ctx, els, modelEls, calls, listeners };
}

(async () => {
  for (const [symbol, hasModel] of [["AAPL", true], ["NVDA", false]]) {
    const env = makeEnv(symbol);
    await env.listeners.DOMContentLoaded();
    await new Promise((r) => setTimeout(r, 20));
    const { els, modelEls, calls } = env;
    assert.doesNotMatch(els.status.textContent, /Error/, `${symbol}: ${els.status.textContent}`);
    assert.match(els.status.textContent, /Signed in as tester/);
    assert.ok(calls.every((c) => c.endsWith(`?${symbol}`)), "every request uses the selected ticker");
    assert.equal(calls.some((c) => c.startsWith("/predictions") || c.startsWith("/model-health") || c.startsWith("/evaluation")), hasModel);
    assert.ok(modelEls.every((e) => e.hidden === !hasModel));
    assert.match(els["model-note"].textContent, hasModel ? /experimental, does not beat baseline/ : /Prices and signals only; no validated model/);
    assert.match(els.signals.innerHTML, /MACD below signal/);
    assert.match(els.ticker.innerHTML, /NVDA \(no model\)/);
    const labels = env.ctx.charts["price-chart"].data.datasets.map((d) => d.label);
    assert.ok(labels[0].startsWith(`${symbol} close`));
    assert.ok(labels.includes("Bollinger upper (20, 2σ)"));
  }
  console.log("dashboard smoke tests: AAPL and NVDA views render");
})().catch((e) => { console.error(e); process.exit(1); });
