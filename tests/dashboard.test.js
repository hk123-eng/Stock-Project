// Offline tests for dashboard data shaping: node tests/dashboard.test.js
const assert = require("node:assert/strict");
const { fmt, buildSeries, evaluationSummary, healthView, escapeHtml } = require("../dashboard/app.js");

assert.equal(fmt.money(333.69), "$333.69");
assert.equal(fmt.money(null), "—");
assert.equal(fmt.pct(0.326), "+0.33%");
assert.equal(fmt.pct(-1.5), "-1.50%");

const s = buildSeries(
  [{ trade_date: "2026-10-01", close: 330.32 }, { trade_date: "2026-10-02", close: 333.69 }],
  [{ as_of_date: "2026-10-02", target_date_estimate: "2026-10-05", predicted_close: 334.78, actual_date: null }],
  [{ timestamp: "2026-09-15T10:24:25Z", close: 202.2, data_type: "synthetic" }],
);
assert.deepEqual(s.real.map((p) => p.x), ["2026-10-01", "2026-10-02"]);
assert.equal(s.preds[0].x, "2026-10-05", "unscored prediction is plotted at its estimated target date");
assert.equal(s.syn[0].x, "2026-09-15");
assert.equal(buildSeries([], [], undefined).syn.length, 0, "synthetic is opt-in");

const scored = buildSeries([], [{ as_of_date: "2026-10-01", target_date_estimate: "2026-10-02", predicted_close: 1, actual_date: "2026-10-05" }], []);
assert.equal(scored.preds[0].x, "2026-10-05", "scored prediction is plotted at the actual next trading day");

const worse = evaluationSummary({ n_predictions: 40, first_target_date: "a", last_target_date: "b", directional_accuracy_pct: 50,
  model: { mae: 6, rmse: 7, mape_pct: 2, mean_error_bias: -5 }, naive_last_close_baseline: { mae: 3, rmse: 4, mape_pct: 1 } });
assert.match(worse.verdict, /does NOT beat/);
const better = evaluationSummary({ n_predictions: 40, first_target_date: "a", last_target_date: "b",
  model: { mae: 2, rmse: 3, mape_pct: 1, mean_error_bias: 0 }, naive_last_close_baseline: { mae: 3, rmse: 4, mape_pct: 1 } });
assert.match(better.verdict, /lower than the naive baseline by \$1\.00/);
assert.equal(evaluationSummary(null), null);

const live = (n, beats) => ({ live: { scored_days: n, min_days_for_verdict: 20, beats_baseline: beats,
  all: { days: n, model_mae: 1.89, naive_mae: 0.8 }, rolling: { days: n, model_mae: 1.89, naive_mae: 0.8 } },
  days: [{ actual_date: "2026-10-05", error: 1.8875, naive_error: 0.8 }], backtest: null });
const h1 = healthView(live(1, null));
assert.equal(h1.insufficient, true);
assert.match(h1.verdict, /^Insufficient data: 1 of 20 scored days\. No verdict yet\.$/);
assert.doesNotMatch(h1.verdict, /beat/, "no beats/does-not-beat wording below 20 days");
assert.deepEqual(h1.model, [{ x: "2026-10-05", y: 1.8875 }]);
assert.match(healthView(live(20, false)).verdict, /does NOT beat/);
assert.match(healthView(live(25, true)).verdict, /LSTM beats/);
assert.equal(healthView(null), null);

assert.equal(escapeHtml('<img src=x onerror="a">'), "&lt;img src=x onerror=&quot;a&quot;&gt;");
console.log("dashboard tests: all passed");
