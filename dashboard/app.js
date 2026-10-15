// Dashboard rendering. Shows only data returned by the API; synthetic rows are
// hidden by default and, when shown, are labelled SYNTHETIC on chart and table.
(function (root) {
  "use strict";

  // ---------- pure helpers (unit-tested in tests/dashboard.test.js) ----------
  const fmt = {
    money: (v) => (v == null ? "—" : "$" + Number(v).toFixed(2)),
    pct: (v) => (v == null ? "—" : (v > 0 ? "+" : "") + Number(v).toFixed(2) + "%"),
    num: (v, d = 2) => (v == null ? "—" : Number(v).toFixed(d)),
  };

  function buildSeries(prices, predictions, synthetic) {
    const real = prices.map((p) => ({ x: p.trade_date, y: p.close }));
    const preds = predictions
      .filter((p) => p.predicted_close != null)
      .map((p) => ({ x: p.actual_date || p.target_date_estimate, y: p.predicted_close, asOf: p.as_of_date }));
    const syn = (synthetic || []).map((p) => ({ x: p.timestamp.slice(0, 10), y: p.close }));
    return { real, preds, syn };
  }

  function evaluationSummary(ev) {
    if (!ev || !ev.model) return null;
    const m = ev.model, b = ev.naive_last_close_baseline;
    const beats = m.mae < b.mae;
    return {
      n: ev.n_predictions,
      period: `${ev.first_target_date} → ${ev.last_target_date}`,
      modelMae: m.mae, modelRmse: m.rmse, modelMape: m.mape_pct, bias: m.mean_error_bias,
      naiveMae: b.mae, naiveRmse: b.rmse, naiveMape: b.mape_pct,
      directional: ev.directional_accuracy_pct,
      verdict: beats
        ? `The LSTM's MAE is lower than the naive baseline by $${(b.mae - m.mae).toFixed(2)}.`
        : `The LSTM does NOT beat the naive “tomorrow = today” baseline (MAE $${m.mae.toFixed(2)} vs $${b.mae.toFixed(2)}).`,
    };
  }

  // Live model health (from /model-health). No verdict until the API says enough days are scored.
  function healthView(mh) {
    if (!mh || !mh.live) return null;
    const L = mh.live;
    const insufficient = L.beats_baseline == null;
    return {
      n: L.scored_days, min: L.min_days_for_verdict, insufficient,
      verdict: insufficient
        ? `Insufficient data: ${L.scored_days} of ${L.min_days_for_verdict} scored days. No verdict yet.`
        : `Over ${L.scored_days} live scored days the LSTM ${L.beats_baseline ? "beats" : "does NOT beat"} the naive “tomorrow = today” baseline.`,
      all: L.all, rolling: L.rolling,
      model: mh.days.map((d) => ({ x: d.actual_date, y: Math.abs(d.error) })),
      naive: mh.days.map((d) => ({ x: d.actual_date, y: Math.abs(d.naive_error) })),
      backtest: mh.backtest,
    };
  }

  // Bollinger(n, k) bands per day with POPULATION sigma, matching src/signals (stock-signals).
  function bollingerSeries(prices, n = 20, k = 2) {
    const out = [];
    for (let i = n - 1; i < prices.length; i++) {
      const w = prices.slice(i - n + 1, i + 1).map((p) => Number(p.close));
      const mid = w.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(w.reduce((a, b) => a + (b - mid) ** 2, 0) / n);
      out.push({ x: prices[i].trade_date, mid, upper: mid + k * sd, lower: mid - k * sd });
    }
    return out;
  }

  // Rows for the signals panel; missing values show as "—".
  function signalRows(sg) {
    const macdState = sg.macd == null || sg.macd_signal == null ? "—"
      : sg.macd > sg.macd_signal ? "MACD above signal" : "MACD below signal";
    return [
      ["SMA 20", fmt.money(sg.sma_20)], ["SMA 50", fmt.money(sg.sma_50)],
      ["RSI 14", fmt.num(sg.rsi_14, 1)], ["20-day volatility", sg.volatility_20d_pct == null ? "—" : fmt.num(sg.volatility_20d_pct) + "%"],
      ["Trend", sg.sma_20 == null || sg.sma_50 == null ? "—" : sg.sma_20 > sg.sma_50 ? "SMA20 above SMA50" : "SMA20 below SMA50"],
      ["MACD (12,26,9)", sg.macd == null ? "—" : `${fmt.num(sg.macd, 3)} / signal ${fmt.num(sg.macd_signal, 3)}`],
      ["MACD histogram", fmt.num(sg.macd_hist, 3)], ["MACD state", macdState],
      ["Bollinger (20, 2σ)", sg.bb_lower == null ? "—" : `${fmt.money(sg.bb_lower)} – ${fmt.money(sg.bb_upper)}`],
      ["Bollinger %B", fmt.num(sg.bb_pct_b, 2)],
    ];
  }

  function alertNote(a) {
    if (a.test_alert) return ' <span class="small">(test run, not a production alert)</span>';
    return a.notified ? ' <span class="small">(emailed)</span>' : "";
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  if (typeof module !== "undefined") {
    module.exports = { fmt, buildSeries, evaluationSummary, healthView, bollingerSeries, signalRows, alertNote, escapeHtml };
    return;
  }

  // ---------- browser ----------
  const C = root.STOCK_CONFIG;
  const $ = (id) => document.getElementById(id);
  let chart, healthChart, state = {};

  async function api(path) {
    const t = root.StockAuth.token();
    if (!t) throw Object.assign(new Error("Signed out"), { auth: true });
    const r = await fetch(`${C.apiBase}${path}${path.includes("?") ? "&" : "?"}symbol=${C.symbol}`, {
      headers: { Authorization: `Bearer ${t}` },
    });
    if (r.status === 401) throw Object.assign(new Error("Session expired"), { auth: true });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  }

  function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

  function renderChart() {
    const showSyn = $("show-synthetic").checked;
    const s = buildSeries(state.prices.prices, state.predictions ? state.predictions.predictions : [],
      showSyn && state.synthetic ? state.synthetic.prices : []);
    const datasets = [
      { label: "AAPL close (real, Alpha Vantage, unadjusted)", data: s.real, borderColor: cssVar("--series-1"),
        backgroundColor: cssVar("--series-1"), borderWidth: 2, pointRadius: 0, tension: 0.15 },
      { label: "LSTM prediction (next close)", data: s.preds, borderColor: cssVar("--series-2"),
        backgroundColor: cssVar("--series-2"), showLine: false, pointRadius: 5, pointStyle: "rectRot" },
    ];
    if ($("show-bands").checked) {
      const bb = bollingerSeries(state.prices.prices);
      datasets.push(
        { label: "Bollinger upper (20, 2σ)", data: bb.map((b) => ({ x: b.x, y: b.upper })), borderColor: cssVar("--muted"),
          borderWidth: 1, pointRadius: 0, borderDash: [2, 3] },
        { label: "Bollinger lower (20, 2σ)", data: bb.map((b) => ({ x: b.x, y: b.lower })), borderColor: cssVar("--muted"),
          borderWidth: 1, pointRadius: 0, borderDash: [2, 3] });
    }
    if (showSyn) datasets.push({ label: "SYNTHETIC test data — NOT market data", data: s.syn,
      borderColor: cssVar("--muted"), borderDash: [5, 4], borderWidth: 1.5, pointRadius: 0 });
    const labels = [...new Set([...s.real, ...s.preds, ...s.syn].map((p) => p.x))].sort();
    if (chart) chart.destroy();
    chart = new root.Chart($("price-chart"), {
      type: "line",
      data: { labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "nearest", intersect: false },
        scales: {
          x: { ticks: { color: cssVar("--muted"), maxTicksLimit: 8 }, grid: { color: cssVar("--grid") } },
          y: { ticks: { color: cssVar("--muted"), callback: (v) => "$" + v }, grid: { color: cssVar("--grid") } },
        },
        plugins: { legend: { labels: { color: cssVar("--text"), usePointStyle: true } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: $${Number(c.parsed.y).toFixed(2)}` } } },
      },
    });
    $("synthetic-note").hidden = !showSyn;
  }

  function renderHealth() {
    const h = healthView(state.modelHealth);
    if (!h) { $("health").innerHTML = "<p>No model-health data yet.</p>"; return; }
    const row = (label, w) => `<tr><td>${label}</td><td>${w.days}</td><td>$${fmt.num(w.model_mae)}</td><td>$${fmt.num(w.naive_mae)}</td></tr>`;
    const bt = h.backtest;
    $("health").innerHTML = `<p class="${h.insufficient ? "warn" : "verdict"}">${escapeHtml(h.verdict)}</p>
      <table><thead><tr><th>Window</th><th>Days</th><th>LSTM MAE</th><th>Naive MAE</th></tr></thead><tbody>
      ${row("All scored days", h.all)}${row(`Last ${h.min}`, h.rolling)}</tbody></table>
      <p class="small">n = ${h.n} live scored days. Error = predicted close − actual next real close; naive predicts today's close.${
        bt ? ` Separate source, not live: walk-forward backtest over ${bt.n_predictions} days (${escapeHtml(bt.first_target_date)} → ${escapeHtml(bt.last_target_date)}), LSTM MAE $${fmt.num(bt.model_mae)} vs naive $${fmt.num(bt.naive_mae)}.` : ""}</p>`;
    if (healthChart) healthChart.destroy();
    healthChart = new root.Chart($("health-chart"), {
      type: "line",
      data: { labels: h.model.map((p) => p.x), datasets: [
        { label: "LSTM absolute error", data: h.model, borderColor: cssVar("--series-2"), backgroundColor: cssVar("--series-2"), pointRadius: 3 },
        { label: "Naive absolute error", data: h.naive, borderColor: cssVar("--muted"), backgroundColor: cssVar("--muted"), borderDash: [5, 4], pointRadius: 3 },
      ] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: { ticks: { color: cssVar("--muted"), maxTicksLimit: 8 }, grid: { color: cssVar("--grid") } },
          y: { beginAtZero: true, ticks: { color: cssVar("--muted"), callback: (v) => "$" + v }, grid: { color: cssVar("--grid") } },
        },
        plugins: { legend: { labels: { color: cssVar("--text"), usePointStyle: true } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: $${Number(c.parsed.y).toFixed(2)}` } } },
      },
    });
  }

  function render() {
    const lp = state.latest.latest, prev = state.latest.previous;
    const chg = prev ? (lp.close / prev.close - 1) * 100 : null;
    $("price").textContent = fmt.money(lp.close);
    $("price-sub").innerHTML = `<span class="${chg >= 0 ? "up" : "down"}">${fmt.pct(chg)}</span> · close of ${escapeHtml(lp.trade_date)}`;
    $("data-note").textContent = state.prices.note + ` ${state.prices.synthetic_rows_excluded} legacy synthetic rows exist in the table and are excluded.`;

    const p = state.latestPrediction && state.latestPrediction.prediction;
    if (p) {
      $("pred").textContent = fmt.money(p.predicted_close);
      $("pred-sub").innerHTML = `${fmt.pct(p.predicted_change_pct)} vs ${fmt.money(p.last_close)} · from data to ${escapeHtml(p.as_of_date)}`;
      $("pred-warn").hidden = !p.inputs_outside_scaler_range;
    }

    const sg = state.signals && state.signals.signals.slice(-1)[0];
    if (sg) {
      $("signals").innerHTML = signalRows(sg).map(([k, v]) => `<div><dt>${k}</dt><dd>${escapeHtml(v)}</dd></div>`).join("") +
        `<p class="small">Computed for ${escapeHtml(sg.trade_date)} from real data.</p>`;
    }

    const al = state.alerts ? state.alerts.alerts.slice().reverse() : [];
    $("alerts").innerHTML = al.length ? al.map((a) => `<li><strong>${escapeHtml(a.trade_date)}</strong> ${
      a.alerts.map((x) => `<span class="tag">${escapeHtml(x.type)}</span> ${escapeHtml(x.detail)}`).join("<br>")}${
      alertNote(a)}</li>`).join("") : "<li>No alerts raised yet.</li>";

    const ph = state.predictions ? state.predictions.predictions.slice().reverse() : [];
    $("pred-rows").innerHTML = ph.length ? ph.map((r) => `<tr><td>${escapeHtml(r.as_of_date)}</td><td>${fmt.money(r.predicted_close)}</td>
      <td>${r.actual_date ? escapeHtml(r.actual_date) : "pending"}</td><td>${fmt.money(r.actual_close)}</td>
      <td>${r.error == null ? "—" : (r.error > 0 ? "+" : "") + r.error.toFixed(2)}</td></tr>`).join("")
      : '<tr><td colspan="5">No predictions yet.</td></tr>';

    const ev = evaluationSummary(state.evaluation);
    $("eval").innerHTML = ev ? `<p class="verdict">${escapeHtml(ev.verdict)}</p>
      <table><thead><tr><th></th><th>MAE</th><th>RMSE</th><th>MAPE</th></tr></thead><tbody>
      <tr><td>LSTM</td><td>$${fmt.num(ev.modelMae)}</td><td>$${fmt.num(ev.modelRmse)}</td><td>${fmt.num(ev.modelMape)}%</td></tr>
      <tr><td>Naive (tomorrow = today)</td><td>$${fmt.num(ev.naiveMae)}</td><td>$${fmt.num(ev.naiveRmse)}</td><td>${fmt.num(ev.naiveMape)}%</td></tr>
      </tbody></table><p class="small">${ev.n} walk-forward predictions, ${escapeHtml(ev.period)}. Directional accuracy ${fmt.num(ev.directional, 1)}%. Mean error (bias) $${fmt.num(ev.bias)}.</p>`
      : "<p>No evaluation published yet.</p>";
    renderChart();
    renderHealth();
  }

  async function load() {
    $("status").textContent = "Loading…";
    const [prices, latest, latestPrediction, predictions, signals, alerts, evaluation, synthetic, modelHealth] = await Promise.all([
      api("/prices?limit=100"), api("/prices/latest"), api("/predictions/latest"), api("/predictions?limit=100"),
      api("/signals?limit=1"), api("/alerts?limit=20"), api("/evaluation"), api("/prices/synthetic?limit=500"),
      api("/model-health?limit=100"),
    ]);
    if (!prices || !latest) throw new Error("No real price data available yet.");
    state = { prices, latest, latestPrediction, predictions, signals, alerts, evaluation, synthetic, modelHealth };
    render();
    $("status").textContent = `Signed in as ${root.StockAuth.user() || "user"} · loaded ${new Date().toLocaleString()}`;
  }

  function showError(e) {
    if (e.auth) { $("app").hidden = true; $("signin").hidden = false; return; }
    $("status").textContent = "Error: " + e.message;
  }

  async function start() {
    $("login-btn").onclick = () => root.StockAuth.login();
    $("logout-btn").onclick = () => root.StockAuth.logout();
    $("refresh-btn").onclick = () => load().catch(showError);
    $("show-synthetic").onchange = () => state.prices && renderChart();
    $("show-bands").onchange = () => state.prices && renderChart();
    try {
      await root.StockAuth.handleCallback();
    } catch (e) { $("signin-msg").textContent = e.message; }
    if (!root.StockAuth.token()) { $("signin").hidden = false; return; }
    $("app").hidden = false;
    $("actions").hidden = false;
    load().catch(showError);
  }

  document.addEventListener("DOMContentLoaded", start);
})(typeof window !== "undefined" ? window : globalThis);
