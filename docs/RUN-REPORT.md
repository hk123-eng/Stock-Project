# Run report (started 2026-10-15)

Only verified facts are recorded here. Times are UTC unless marked ET (America/New_York).

## Progress log
| Step | Status | Evidence |
|---|---|---|
| 0. Re-verify live state | Done | 7 scheduled runs 2026-10-07 → 2026-10-15 SUCCEEDED; latest (started 2026-10-14 22:30 UTC) ran ScorePredictions → `newly_scored 1, already_scored 7, pending 1`. 108 real AAPL rows (2026-05-12 → 2026-10-14). Alarm OK. Schedule ENABLED. Cognito pool has 2 users (created by the user). |
| Local git | Done | `git init` inside `stock-project/` (decision D1). Secret scan clean. Commits listed by `git log`. |
| 1. Phase 8 item 2 (MACD, Bollinger, per-type dedup) | Code deployed + live-tested by direct invocation; pipeline run pending | see Item 1 |
| 2. Phase 8 item 3 (watchlist) | Lambdas/API/dashboard deployed; state machine + schedule switch pending (evening window) | see Item 2 |
| 3. Phase 8 item 4 (retraining plan) | Done | `docs/retraining-plan.md` |
| 4. Phase 8 item 5a (CI + local git) | Done (not run on GitHub: no remote) | `.github/workflows/ci.yml`, `tests/secret_scan.py` |
| 5. Phase 8 item 5b/5c (CloudWatch dashboard, DLQ) | Dashboard done; DLQ created, alarms created, test running; schedule DLQ attach pending (evening window) | see Item 5 |
| 6. Step Functions logging | Parked (AccessDenied re-checked 2026-10-15) | see "Permissions" |
| 7. Phase 9 | (a)(b)(c)(e) parked, (d) already in place | see Item 7 |

## Decisions taken with the defaults (no human available)
- **D1 – git location.** An empty git repo (no commits) already exists at `C:\Users\hrush` (the whole home folder). It was not touched. A separate repo was created in `C:\Users\hrush\stock-project`. No remote, nothing pushed.
- **D2 – test venv.** `boto3` was not installed for the system Python, so `tests/run_all.py` could not import the Lambdas. A local `.venv/` (git-ignored) with `boto3` is used: `.venv/Scripts/python tests/run_all.py`.
- **D3 – live pipeline test timing.** `stock-evaluate` writes a score only once. A test run during or just after market hours could freeze a score against a provisional close. Live pipeline tests therefore run only after the scheduled 18:30 ET run has processed the day (after 19:00 ET = 23:00 UTC), which also satisfies hard rule 7.
- **D4 – test alert labelling.** A labelled direct test invocation of `stock-signals` (execution id `test-phase8-item2-direct-invoke`) marked the 2026-10-14 `MACD_CROSS` as sent without emailing it (direct invocations never publish to SNS). Rather than edit or delete the row, `GET /alerts` now returns `test_alert: true` for executions whose id starts with `test-`, and the dashboard labels them "test run, not a production alert".
- **D5 – partial failures.** A failed ticker does not fail the execution: the run SUCCEEDS, the other tickers are processed, and the single combined email lists the failed tickers (subject starts "N FAILED"). The digest also publishes `StockProject/Pipeline TickerFailures`. Whole-run failures (invalid input, Map/digest/publish errors) still go to `PublishFailure` → FAILED → the existing alarm. Reason: the request asked for ONE summary failure alert; failing the execution as well would add a second (alarm) email.
- **D6 – suspicious price jump.** Ingest flags day-over-day close changes ≥ 25% (possible split; prices are unadjusted). If new data for AAPL contains one, the pipeline skips the LSTM prediction for that run and the email says so. Nothing is blocked for other tickers; the jump is reported.
- **D7 – rate limits.** Alpha Vantage throttle messages arrive with HTTP 200. "per day" quota → `DailyLimitError` (never retried); other throttles → `RateLimitError`; `IngestError` and `RateLimitError` share ONE retry after 60 s. Worst case: 2 calls per ticker per run.
- **D8 – digest Lambda instead of reusing stock-signals.** Separate `stock-alert-digest` with its own role that can only write its logs and `StockProject/Pipeline` metrics (least privilege; it reads no data).
- **D9 – second DLQ alarm.** The DLQ test message cannot be deleted (no delete rule; no `sqs:DeleteMessage`), so `stock-pipeline-dlq-not-empty` stays in ALARM until the message expires (14 days) or you purge it; while in ALARM it would not notify again. `stock-pipeline-dlq-new-message` (NumberOfMessagesSent ≥ 1 in 5 min) returns to OK by itself and notifies for every new failure.
- **D10 – DynamoDB TTL (Phase 9e) not enabled.** It is permitted, but no new or test-only items exist that should expire; enabling it would be a no-op, and an expiry attribute added later by mistake could expire real data. S3 lifecycle is denied anyway.

## Alpha Vantage call count (my own calls; limit 10/day)
| Date (UTC) | Calls | Purpose |
|---|---|---|
| 2026-10-15 | 0 so far | (scheduled runs are not counted here) |

## Item 1 – Phase 8 item 2: MACD + Bollinger + per-type dedup
- Code: `src/signals/lambda_function.py` – `ema_series`, `macd(12,26,9)`, `bollinger(20, 2, population σ)`; rules `MACD_CROSS`, `BOLLINGER_BREAK` (transition-only, `ENABLE_<TYPE>=false` switches a rule off); dedup per (symbol, trade_date, type) via conditional write on `alert_sent_<TYPE>`; only new alerts are returned.
- Tests: `tests/test_signals_macd_bb.py` (13 tests, hand-computed expected values), `tests/test_api.py`, `tests/dashboard.test.js`.
- Rollback points: `stock-signals` version 1 and `stock-api` version 1 = code before this item.
- Live: deployed 2026-10-15 13:36 UTC. Direct invocation on 2026-10-14 data: first call returned `MACD_CROSS` (bullish, MACD 3.982 vs signal 3.837) and set `alert_sent_MACD_CROSS`; the repeat returned `alerts: [], already_sent: ["MACD_CROSS"], deduplicated: true`. Read-only dry run over 2026-10-08 … 2026-10-13: no MACD/Bollinger rule fired.
- Dashboard (MACD/Bollinger in the signals panel, Bollinger bands on the chart) uploaded; anonymous GET → 403.

## Item 2 – Phase 8 item 3: watchlist
- `infra/stepfunctions/build_definition.py --watchlist` → `stock-prediction-pipeline.watchlist.asl.json` (validated by `aws stepfunctions validate-state-machine-definition`: OK). Map, MaxConcurrency 1, 15 s Wait between tickers, per-ticker Catch → per-ticker failure result, predict only AAPL and only when no new suspicious jump, digest → one SNS email.
- New Lambda `stock-alert-digest` (python3.12 arm64 128 MB, role `stock-alert-digest-role` with `StockRoleBoundary`, logs + `cloudwatch:PutMetricData` on `StockProject/Pipeline` only). Log group retention 30 days. Direct test invocation OK (it published one test datapoint `TickerFailures=1` at about 13:45 UTC).
- `stock-ingest` updated (DailyLimitError/RateLimitError split, `data_quality` jump check). Rollback point: `stock-ingest` version 1.
- `stock-api`: allow-list = AAPL MSFT GOOGL AMZN NVDA; `/predictions*`, `/evaluation`, `/model-health` → 404 "no validated model" for non-AAPL; every 200 response has `model_status`. Live-checked by direct invocation (NVDA /predictions → 404, TSLA → 400).
- Dashboard ticker selector; non-AAPL shows "Prices and signals only; no validated model"; AAPL shows "experimental, does not beat baseline". Headless smoke test `tests/dashboard.smoke.test.js` renders both.
- Pending: switch state machine + schedule input after 19:00 ET, full test run (5 AV calls: 1 per ticker = backfill for the 4 new tickers).

## Item 3 – Phase 8 item 4: retraining plan
`docs/retraining-plan.md`. Nothing trained. Measured inputs (2026-10-15): of the last 60 real AAPL closes, 6 are above the scaler max $339.7869 and 34 are within 5% of it or above; walk-forward bias −$4.67 (n=19) when the last close was ≥ 95% of the max vs −$0.43 (n=21) otherwise — stated as a hypothesis only.

## Item 4 – Phase 8 item 5a: CI
`.github/workflows/ci.yml` (Python 3.12 + Node 20; secret scan, `tests/run_all.py`, dashboard tests; no AWS credentials, `permissions: contents: read`). Not run on GitHub (no remote by instruction).

## Item 5 – Phase 8 items 5b/5c
- Permissions verified read-only: `StockProjectPhase8` (v1: `cloudwatch:PutDashboard` on `dashboard/stock-*`; `sqs:CreateQueue/SetQueueAttributes/TagQueue` on `stock-*`) attached to `stock-project`; `StockRoleBoundary` default version v2 includes `sqs:SendMessage` on `stock-*`.
- CloudWatch dashboard `stock-project` created (36 metrics; validation messages: none). Definition: `infra/cloudwatch/dashboard-stock-project.json`.
- SQS `stock-pipeline-dlq`: SSE-SQS on, retention 1,209,600 s (14 days), queue policy = SendMessage only from `stock-scheduler-role` + deny non-TLS.
- `stock-scheduler-role` inline policy now also allows `sqs:SendMessage` on that queue only.
- Alarms `stock-pipeline-dlq-not-empty` and `stock-pipeline-dlq-new-message` → SNS `stock-prediction-alerts`.
- Test schedule `stock-test-dlq-20261015` (one-time, 2026-10-15 13:55 UTC, targets non-existent state machine `stock-dlq-test-does-not-exist`, 0 retries, ActionAfterCompletion NONE → inert afterwards). **Listed for your cleanup.**

## Item 7 – Phase 9 (checked with `iam simulate-principal-policy`, read-only)
| Item | Result |
|---|---|
| (a) Athena + Glue table | Parked: `glue:CreateDatabase`, `glue:CreateTable`, `athena:StartQueryExecution` denied |
| (b) EventBridge custom bus | Parked: `events:CreateEventBus`, `events:PutRule`, `events:PutTargets` denied |
| (c) X-Ray | Parked: Lambda roles would need `xray:PutTraceSegments`/`PutTelemetryRecords`, which `StockRoleBoundary` does not allow (boundary edits are forbidden); the state machine role may not be edited (rule 8); HTTP APIs do not support X-Ray tracing (REST APIs only) |
| (d) API throttling | Already in place since Phase 5: `$default` stage 10 rps / burst 20 (verified 2026-10-15) |
| (e) TTL / lifecycle | S3 lifecycle denied; DynamoDB TTL permitted but intentionally not enabled (D10) |
