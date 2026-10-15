# Run report (started 2026-10-15)

Only verified facts are recorded here. Times are UTC unless marked ET (America/New_York).

## Progress log
| Step | Status | Evidence |
|---|---|---|
| 0. Re-verify live state | Done | 7 scheduled runs 2026-10-07 → 2026-10-15 SUCCEEDED; latest (started 2026-10-14 22:30 UTC) ran ScorePredictions → `newly_scored 1, already_scored 7, pending 1`. 108 real AAPL rows (2026-05-12 → 2026-10-14). Alarm OK. Schedule ENABLED. Cognito pool has 2 users (created by the user). |
| Local git | Done | `git init` inside `stock-project/` (see decision D1). Secret scan clean. Baseline commit `6217c1e`. |
| 1. Phase 8 item 2 (MACD, Bollinger, per-type dedup) | In progress | See below |

## Decisions taken with the defaults (no human available)
- **D1 – git location.** An empty git repo (no commits) already exists at `C:\Users\hrush` (the whole home folder). It was not touched. A separate repo was created in `C:\Users\hrush\stock-project`. No remote, nothing pushed.
- **D2 – test venv.** `boto3` was not installed for the system Python, so `tests/run_all.py` could not import the Lambdas. A local `.venv/` (git-ignored) with `boto3` is used: `.venv/Scripts/python tests/run_all.py`.
- **D3 – live pipeline test timing.** `stock-evaluate` writes a score only once. A test run during or just after market hours could freeze a score against a provisional close. Live pipeline tests therefore run only after the scheduled 18:30 ET run has processed the day (after 19:00 ET), which also satisfies hard rule 7.
- **D4 – test alert labelling.** A labelled direct test invocation of `stock-signals` (execution id `test-phase8-item2-direct-invoke`) marked the 2026-10-14 `MACD_CROSS` as sent without emailing it (direct invocations never publish to SNS). Rather than edit or delete the row, `GET /alerts` now returns `test_alert: true` for executions whose id starts with `test-`, and the dashboard labels them "test run, not a production alert".

## Alpha Vantage call count (my own calls; limit 10/day)
| Date (UTC) | Calls | Purpose |
|---|---|---|
| 2026-10-15 | 0 | (scheduled runs not counted here) |

## Item 1 – Phase 8 item 2: MACD + Bollinger + per-type dedup
- Code: `src/signals/lambda_function.py` – `ema_series`, `macd(12,26,9)`, `bollinger(20, 2, population σ)`; rules `MACD_CROSS`, `BOLLINGER_BREAK` (transition-only, `ENABLE_<TYPE>=false` switches a rule off); dedup per (symbol, trade_date, type) via conditional write on `alert_sent_<TYPE>`; only new alerts are returned.
- Tests: `tests/test_signals_macd_bb.py` (13 tests, hand-computed expected values), `tests/test_api.py` +1, `tests/dashboard.test.js` extended.
- Rollback points: `stock-signals` version 1 and `stock-api` version 1 = code before this item.
- Deployed 2026-10-15 ~13:36 UTC. Live direct-invocation test on 2026-10-14 data: first call returned `MACD_CROSS` (bullish, MACD 3.982 vs signal 3.837) and set `alert_sent_MACD_CROSS`; the repeat returned `alerts: [], already_sent: ["MACD_CROSS"], deduplicated: true`.
- Dashboard (signals panel with MACD/Bollinger, Bollinger bands on the price chart) uploaded to the private bucket; anonymous GET → 403.
