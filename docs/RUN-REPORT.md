# Run report (2026-10-15, finished 2026-10-15 ~23:30 UTC)

Only verified facts are recorded here. Times are UTC unless marked ET (America/New_York).

## Progress log
| Step | Status | Evidence |
|---|---|---|
| 0. Re-verify live state | Done | 7 scheduled runs 2026-10-07 → 2026-10-15 SUCCEEDED; latest (started 2026-10-14 22:30 UTC) ran ScorePredictions → `newly_scored 1, already_scored 7, pending 1`. 108 real AAPL rows (2026-05-12 → 2026-10-14). Alarm OK. Schedule ENABLED. Cognito pool has 2 users (created by the user). |
| Local git | Done | `git init` inside `stock-project/` (decision D1). Secret scan clean. Commits listed by `git log`. |
| 1. Phase 8 item 2 (MACD, Bollinger, per-type dedup) | Done | Direct invocation dedup test; scheduled run 2026-10-15 22:30 UTC SUCCEEDED with the new code; watchlist test raised NVDA `BOLLINGER_BREAK` |
| 2. Phase 8 item 3 (watchlist) | Done; live since 2026-10-15 23:01 UTC | 4 live test executions, see Item 2 |
| 3. Phase 8 item 4 (retraining plan) | Done | `docs/retraining-plan.md` |
| 4. Phase 8 item 5a (CI + local git) | Done (not run on GitHub: no remote) | `.github/workflows/ci.yml`, `tests/secret_scan.py` |
| 5. Phase 8 item 5b/5c (CloudWatch dashboard, DLQ) | Done | DLQ test 13:55 UTC; DLQ attached to `stock-daily-pipeline` 23:01 UTC (verified with `get-schedule`) |
| 6. Step Functions logging | Parked (AccessDenied re-checked 2026-10-15) | see "Permissions" |
| 7. Phase 9 | (a)(b)(c)(e) parked, (d) already in place | see Item 7 |
| 8. Final docs | Done | `PROJECT_CONTEXT.md`, `TODO.md`, `README.md`, `docs/architecture.md`, `docs/aws-inventory.md`, `docs/demo-and-viva.md` updated 2026-10-15 ~23:30 UTC |

## Summary for the owner (read this first)
**(1) Completed and verified**
- Phase 8 item 2: MACD + Bollinger signals, per-type dedup, one combined email per run, dashboard bands. Evidence: direct-invocation dedup test; scheduled run 2026-10-15 22:30 UTC SUCCEEDED on the new code; live NVDA `BOLLINGER_BREAK` email from the watchlist test.
- Phase 8 item 3: watchlist AAPL MSFT GOOGL AMZN NVDA live since 2026-10-15 23:01 UTC. Evidence: 4 test executions (Item 2 table); 100 real rows each for the 4 new tickers; API 404 "no validated model" for NVDA predictions.
- Phase 8 item 4: `docs/retraining-plan.md` (nothing trained).
- Phase 8 item 5a: local git, `.gitignore`, secret scan (0 findings), CI workflow (never run: no remote).
- Phase 8 items 5b/5c: CloudWatch dashboard `stock-project`; SQS DLQ + 2 alarms, tested end to end, attached to the daily schedule.
- Final docs updated to match the deployed system.
- Tests: 59 Python unit tests (`.venv/Scripts/python tests/run_all.py`), `node tests/dashboard.test.js`, `node tests/dashboard.smoke.test.js`: all pass.

**(2) Parked** (details below): Step Functions execution logging (P1), Athena/Glue (P2), EventBridge custom bus (P3), X-Ray (P4), S3 lifecycle (P5), CloudFront (account verification), DynamoDB TTL (deliberately not enabled, D10). CloudTrail, Cognito groups, SAM/CloudFormation and Bedrock: plan notes only (`docs/phase9-notes.md`).

**(3) IAM JSON:** P1–P5 under "Permissions needed". All must be applied by you as the account administrator.

**(4) Manual steps for you**
1. Sign in to the dashboard in a browser with your Cognito user (`cd dashboard && python -m http.server 8080`, open http://localhost:8080/), check AAPL and NVDA views, the Bollinger toggle, model health.
2. Open an AWS Support case to verify the account for CloudFront; afterwards run `bash infra/cloudfront/finish-cloudfront.sh` (it checks that anonymous S3 access stays 403).
3. GitHub: create an empty private repository, then `git remote add origin <url>` and `git push -u origin main` from `stock-project/`. CI will run on push (tests only; no AWS credentials needed).
4. Optional cleanup (deletions; none done): `stock-db-seeder` Lambda + `stock-db-seeder-role`; layer `tflite-runtime-py310` v1; S3 `layers/tflite-layer.zip`; schedules `stock-test-once-20261005` and `stock-test-dlq-20261015`; purge the DLQ test message (SQS console → `stock-pipeline-dlq` → Purge) so `stock-pipeline-dlq-not-empty` returns to OK (otherwise it expires ~2026-10-29); Lambda versions `stock-signals:1`, `stock-api:1`, `stock-ingest:1` are rollback points — keep them until you are happy.
5. Alpha Vantage: if this is a group project, email support@alphavantage.co (commercial/other use: premium@alphavantage.co per their terms) to confirm the use is allowed.
6. When you are done building, detach the build policies from IAM user `stock-project` (`StockProjectBuildAccess`, `StockProjectBuildAccessPhase3to6`, `StockProjectPhase8`, and `StockIamScoped` if no more roles are needed).
7. Check the first scheduled watchlist run (Fri 2026-10-16 18:30 ET = 22:30 UTC): Step Functions console or the email (an email arrives only if there is a new alert, a jump warning or a failed ticker).
8. Who ran execution `7f73a430-…` with `{"symbol":"XYZ"}` at 2026-10-15 18:55 UTC? Not the deploy user. If it was you, nothing to do.

**(5) Resources and cost** — created in this run: Lambda `stock-alert-digest` + role `stock-alert-digest-role` (boundary) + its log group (30 days); SQS `stock-pipeline-dlq`; alarms `stock-pipeline-dlq-not-empty`, `stock-pipeline-dlq-new-message`; CloudWatch dashboard `stock-project`; metric namespace `StockProject/Pipeline`; test schedule `stock-test-dlq-20261015` (inert); Lambda versions `stock-signals:1`, `stock-api:1`, `stock-ingest:1`. Modified: state machine definition, `stock-daily-pipeline` target (input + DLQ), `stock-scheduler-role` inline policy (+`sqs:SendMessage` on the DLQ), code of `stock-ingest`/`stock-signals`/`stock-api`, dashboard files in the private bucket. Nothing deleted. Expected cost **$0.00/month** within free tiers (3 alarms ≤ 10 free, 1 dashboard ≤ 3 free, 4 custom metrics ≤ 10 free, SQS/Lambda/Step Functions far below free limits: about 20 Lambda invocations per weekday; the 5-ticker test entered 60 states, so about 1,300 state transitions a month against 4,000 free). Worst case without free tiers: well under $0.50/month — the largest item would be the CloudWatch dashboard ($3/month) only if the 3-dashboard free tier were exceeded, which it is not (this is the only dashboard).

**(6) Alpha Vantage calls:** 7 of my 10 on 2026-10-15 (table below).

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
| 2026-10-15 23:01 UTC | 5 | `test-watchlist-20261015T230152` (1 per ticker; backfilled MSFT/GOOGL/AMZN/NVDA) |
| 2026-10-15 23:03 UTC | 1 | `test-isolation-20261015T230353` (AAPL only; ZZZZ rejected before ingest) |
| 2026-10-15 23:04 UTC | 0 | `test-invalid-20261015T230433` (`{}` rejected before the Map) |
| 2026-10-15 23:04 UTC | 1 | `test-legacy-20261015T230444` (`{"symbol":"AAPL"}`) |
| **2026-10-15 total** | **7 of my 10** | No retries happened (no throttle message). |

Other calls on 2026-10-15 UTC, not mine: the scheduled run at 22:30 UTC (1 call, AAPL, old input). Execution `7f73a430-…` at 18:55 UTC with input `{"symbol":"XYZ"}` was **not started by the deploy user** (probably a manual console test); it failed at ValidateInput as designed and made 0 calls. Day total on the key: 8 of 25 (Alpha Vantage counts by its own day, which may not match UTC).
From 2026-10-16 each scheduled run uses 5 calls (worst case 10 with retries).

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
- **Switch (2026-10-15 23:01 UTC, 19:01 ET):** `bash infra/stepfunctions/switch-to-watchlist.sh`: snapshots saved (`stock-prediction-pipeline.pre-watchlist.asl.json`, `infra/scheduler/stock-daily-pipeline.pre-watchlist.json`), definition validated (OK) and updated, schedule updated (same cron/timezone/role/retries; input `{"symbols":["AAPL","MSFT","GOOGL","AMZN","NVDA"]}`; DLQ). Verified with `get-schedule`: ENABLED.
- **Scheduled run before the switch** (2026-10-15 22:30 UTC, old definition, new ingest/signals code): SUCCEEDED; ingest `inserted 1, updated 1, unchanged 98`, `data_quality` 99 pairs checked, 0 jumps; prediction 337.7887 for as-of 2026-10-15 (inputs outside scaler range); signals computed incl. MACD 4.0223 / signal 3.8743, %B 0.8213, no rule fired; score `newly_scored 1, already_scored 8, pending 1`.
- **Live tests after the switch:**
  | Execution | Input | Result |
  |---|---|---|
  | `test-watchlist-20261015T230152` | 5 tickers | SUCCEEDED, 90 s. AAPL: `unchanged 99, updated 1`, prediction only for AAPL, score unchanged (`already_scored 9`). MSFT/GOOGL/AMZN/NVDA: `inserted 100` each (2026-05-26 → 2026-10-15). Jumps in window: 0 for all 5. New alert: NVDA `BOLLINGER_BREAK` (close 217.23 below lower band 217.58, %B −0.016). Digest email published, subject "Stock watchlist: NVDA BOLLINGER_BREAK". |
  | `test-isolation-20261015T230353` | `["AAPL","ZZZZ"]` | SUCCEEDED. AAPL ok; ZZZZ `failed_step validate` ("not in the watchlist"). Email published, subject "Stock watchlist: 1 FAILED". The failed symbol appears JSON-quoted (`"ZZZZ"`) in the email: deliberate (`States.JsonToString`, so a non-string value cannot break the failure path). |
  | `test-invalid-20261015T230433` | `{}` | FAILED (as designed) via InvalidInput → PublishFailure (task succeeded) → Fail. `stock-pipeline-failed-executions` went OK → ALARM at 23:05:49 UTC, SNS action succeeded (it returns to OK by itself; the 18:55 UTC `XYZ` run had done the same at 18:56:49 UTC). |
  | `test-legacy-20261015T230444` | `{"symbol":"AAPL"}` | SUCCEEDED via LegacyInput; nothing new, digest `send false`, no email. |
- API after the switch (direct invocation): NVDA `/prices` 200 (100 rows), `/signals` 200, `/alerts` shows the BOLLINGER_BREAK with `test_alert: true`, `/predictions/latest` 404 "no validated model"; AAPL `/predictions/latest` 200.
- **Note on the NVDA alert:** it was emailed for real, by a test execution. Its dedup flag is set, so the scheduled run will not email it again; the API/dashboard label it "test run" because `alert_execution` starts with `test-`.
- **Note on revised bars:** AAPL 2026-10-14 was `updated` at 22:30 UTC and 2026-10-15 at 23:01 UTC; the close of 2026-10-15 was 342.0 both times, so the score written at 22:30 is unaffected. The other fields do not show what changed (probably a late volume revision).
- Fixed: `infra/stepfunctions/run_test.py` printed the prediction and signals columns swapped (summary only; the execution was unaffected).
- Not tested live: a ticker failing inside a Lambda (covered by `tests/test_state_machine.py` structure tests and unit tests) and a real Alpha Vantage throttle (unit tests only, to save calls).

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
- DLQ attached to `stock-daily-pipeline` at 2026-10-15 23:01 UTC (`DeadLetterConfig.Arn` = `stock-pipeline-dlq`, verified).
- Test schedule `stock-test-dlq-20261015` (one-time, 2026-10-15 13:55 UTC, targets non-existent state machine `stock-dlq-test-does-not-exist`, 0 retries, ActionAfterCompletion NONE → inert afterwards). **Listed for your cleanup.**
- **DLQ test result (2026-10-15):** the schedule fired at 13:55:00 UTC; Scheduler put 1 message in `stock-pipeline-dlq` (peeked with visibility timeout 0, not deleted): `ERROR_CODE AccessDeniedException` (scheduler role may only start `stock-prediction-pipeline`), `RETRY_ATTEMPTS 0`, `SCHEDULE_ARN …/stock-test-dlq-20261015`. `stock-pipeline-dlq-new-message` → ALARM, SNS action succeeded 13:57:13 UTC; `stock-pipeline-dlq-not-empty` → ALARM, SNS action succeeded 13:58:46 UTC. You should have received 2 ALARM emails. The test message stays until it expires (14 days, ~2026-10-29) or you purge the queue; until then `-not-empty` stays in ALARM (D9).

## Item 7 – Phase 9 (checked with `iam simulate-principal-policy`, read-only)
| Item | Result |
|---|---|
| (a) Athena + Glue table | Parked: `glue:CreateDatabase`, `glue:CreateTable`, `athena:StartQueryExecution` denied |
| (b) EventBridge custom bus | Parked: `events:CreateEventBus`, `events:PutRule`, `events:PutTargets` denied |
| (c) X-Ray | Parked: Lambda roles would need `xray:PutTraceSegments`/`PutTelemetryRecords`, which `StockRoleBoundary` does not allow (boundary edits are forbidden); the state machine role may not be edited (rule 8); HTTP APIs do not support X-Ray tracing (REST APIs only) |
| (d) API throttling | Already in place since Phase 5: `$default` stage 10 rps / burst 20 (verified 2026-10-15) |
| (e) TTL / lifecycle | S3 lifecycle denied; DynamoDB TTL permitted but intentionally not enabled (D10) |

## CloudFront (checked 2026-10-15 ~14:00 UTC)
Still blocked. `infra/cloudfront/finish-cloudfront.sh` stopped at step 1: `CreateDistributionWithTags` → "Your account must be verified before you can add new CloudFront resources". Nothing was created; the dashboard bucket still has no bucket policy and Block Public Access ×4 (anonymous GET → 403). The script's final curl checks were fixed (`/dev/null` does not work for Windows curl with `MSYS_NO_PATHCONV=1`).

## Permissions needed (ready to paste; nothing was worked around)
All of these are for **you (account administrator) to apply in IAM**. The deploy user cannot and did not change its own permissions or the boundary.

### P1 – Step Functions execution logging (policy on IAM user `stock-project`; unchanged from PROJECT_CONTEXT.md §13)
Re-checked 2026-10-15: `logs:CreateLogGroup` on `/aws/vendedlogs/states/stock-prediction-pipeline` → AccessDenied.
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "StockSfnLogGroup", "Effect": "Allow",
     "Action": ["logs:CreateLogGroup", "logs:PutRetentionPolicy"],
     "Resource": "arn:aws:logs:ap-south-1:542601847637:log-group:/aws/vendedlogs/states/stock-*"},
    {"Sid": "SfnLogDelivery", "Effect": "Allow",
     "Action": ["logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
                "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups"],
     "Resource": "*"}
  ]
}
```

### P2 – Phase 9a Athena over S3 (policy on IAM user `stock-project`)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "GlueCatalogStockProject", "Effect": "Allow",
     "Action": ["glue:CreateDatabase", "glue:GetDatabase", "glue:CreateTable", "glue:GetTable", "glue:UpdateTable", "glue:GetPartitions"],
     "Resource": ["arn:aws:glue:ap-south-1:542601847637:catalog",
                  "arn:aws:glue:ap-south-1:542601847637:database/stock_project",
                  "arn:aws:glue:ap-south-1:542601847637:table/stock_project/*"]},
    {"Sid": "AthenaPrimaryWorkgroup", "Effect": "Allow",
     "Action": ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution"],
     "Resource": "arn:aws:athena:ap-south-1:542601847637:workgroup/primary"},
    {"Sid": "AthenaResultsPrivatePrefix", "Effect": "Allow",
     "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"],
     "Resource": "arn:aws:s3:::stock-prediction-raw-542601847637-ap-south-1-an/athena-results/*"},
    {"Sid": "AthenaBucketLocation", "Effect": "Allow",
     "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
     "Resource": "arn:aws:s3:::stock-prediction-raw-542601847637-ap-south-1-an"}
  ]
}
```

### P3 – Phase 9b EventBridge custom bus (two parts)
(1) Policy on IAM user `stock-project`:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "StockBusAndRules", "Effect": "Allow",
     "Action": ["events:CreateEventBus", "events:DescribeEventBus", "events:PutRule", "events:DescribeRule", "events:PutTargets", "events:ListTargetsByRule"],
     "Resource": ["arn:aws:events:ap-south-1:542601847637:event-bus/stock-pipeline",
                  "arn:aws:events:ap-south-1:542601847637:rule/stock-pipeline/stock-*"]},
    {"Sid": "EventsLogTarget", "Effect": "Allow",
     "Action": ["logs:CreateLogGroup", "logs:PutRetentionPolicy"],
     "Resource": "arn:aws:logs:ap-south-1:542601847637:log-group:/aws/events/stock-*"},
    {"Sid": "EventsLogsResourcePolicy", "Effect": "Allow",
     "Action": ["logs:PutResourcePolicy", "logs:DescribeResourcePolicies"], "Resource": "*"}
  ]
}
```
(2) A new default version of `StockRoleBoundary` that adds this statement (so `stock-alert-digest-role` may publish run events):
```json
{"Sid": "StockBusPutEvents", "Effect": "Allow", "Action": "events:PutEvents",
 "Resource": "arn:aws:events:ap-south-1:542601847637:event-bus/stock-pipeline"}
```

### P4 – Phase 9c X-Ray (two parts; HTTP API itself cannot be traced)
(1) A new default version of `StockRoleBoundary` that adds:
```json
{"Sid": "XRayWrite", "Effect": "Allow",
 "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"],
 "Resource": "*"}
```
(2) The same statement as an inline policy on `stock-prediction-sfn-role` (the deploy user is not allowed to edit that role). The deploy user can then add it to the `stock-*` Lambda roles and turn on tracing with permissions it already has.

### P5 – Phase 9e S3 lifecycle for a test prefix (optional; policy on IAM user `stock-project`)
```json
{"Version": "2012-10-17", "Statement": [{"Sid": "RawBucketLifecycle", "Effect": "Allow",
  "Action": ["s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration"],
  "Resource": "arn:aws:s3:::stock-prediction-raw-542601847637-ap-south-1-an"}]}
```
The only rule intended: expire objects under `athena-results/` after 7 days. No rule would ever cover `raw/`, `models/` or `predictions/`.

### Not needed any more
The DLQ and CloudWatch dashboard permissions you granted (`StockProjectPhase8`, boundary v2) were sufficient.

---

# Final run (started 2026-10-22 12:18 UTC)

Work order from the owner (2026-10-22). Decisions on "go": **A** SNS message attributes parked, alert path unchanged; **B** skip Predict and Signals only when ingest reports `inserted == 0 and updated == 0`. Items 2 and 3 run only 19:00 ET → 09:30 ET, never 16:00–18:30 ET.

## Step 0 (read-only, 2026-10-22 12:18–12:31 UTC)
- Scheduled runs since 2026-10-16 all SUCCEEDED (16, 19, 20, 21 Oct ET; 87–89 s each), including the first five-ticker run (2026-10-16 22:30 UTC = 04:00 IST 17 Oct). The two FAILED executions in the last 10 were deliberate invalid inputs (`{}` test, and `{"symbol":"XYZ"}` not started by the deploy user).
- Real rows: AAPL 113 (2026-05-12 → 2026-10-21) + 114 legacy synthetic rows untouched; MSFT/GOOGL/AMZN/NVDA 104 each (2026-05-26 → 2026-10-21).
- Predictions: 14 rows, all AAPL; 13 scored. Live MAE model $4.18 vs naive $2.25 (n=13; verdict "insufficient data (13 of 20)").
- Alerts: tests = AAPL 2026-10-02 PREDICTED_MOVE (temporary 0.1% threshold), AAPL 2026-10-14 MACD_CROSS (direct invoke, not emailed); NVDA 2026-10-15 BOLLINGER_BREAK is a real signal emailed by a test execution (labelled test). Real, from scheduled runs: GOOGL 10-16 MACD_CROSS, AMZN 10-19 BIG_MOVE, MSFT 10-19 MACD_CROSS, AAPL 10-20 MACD_CROSS, GOOGL 10-21 BOLLINGER_BREAK.
- Bollinger bands DO draw: headless Chrome render of the deployed `index.html` (real CSP, Chart.js via cdnjs + SRI, real AAPL API data from a direct `stock-api` invoke; only fetch/login mocked): upper/lower bands 81 finite points each over 100 closes. Not a signed-in browser test.
- `StockProjectPhase9` (v1, 2026-10-15 16:12 UTC) is attached to `stock-project`; `StockRoleBoundary` default v3 (adds stream reads, X-Ray Put*, `events:PutEvents` on `stock-*` buses).
- DLQ purged by the owner (CloudTrail `PurgeQueue`, root, 2026-10-22 12:26 UTC).

## Prices checked (AWS Price List API, ap-south-1, 2026-10-22)
| Item | Price | Expected use | Monthly |
|---|---|---|---|
| DynamoDB PITR | $0.228 per GB-month | ~0.16 MB over 3 tables | < $0.001 |
| DynamoDB Streams reads | 2.5M read units free, then $0.000000228 | Lambda trigger reads (free for Lambda triggers) | $0 |
| EventBridge custom events | $1.00 per million | ~5 PriceIngested/weekday ≈ 110 | ≈ $0.0001 |
| Lambda requests | $0.20 per million (free tier 1M) | +~10/weekday | $0 |
| Athena | $5.00 per TB scanned (10 MB minimum per query) | a few test queries | < $0.01 |
| Glue Data Catalog | $1 per 100,000 objects (first 1M free) | 1 database + 3 tables | $0 |
| CloudWatch custom metrics | $0.30 per metric-month (first 10 free) | 4 existing + 2 | $0 |
| CloudWatch Logs | $0.67/GB ingested, $0.03/GB-month | a few KB/day | < $0.01 |
| S3 requests | $0.005/1k PUT, $0.004/10k GET | ~5 manifests + reads/weekday | < $0.01 |
| X-Ray | $5.00 per million traces stored (100k free) | ~30/weekday | $0 |
| HTTP API | $1.05 per million requests | /me tests | $0 |

## Item 1 – additive items
### 1a PITR — done 2026-10-22 12:44 UTC
`stock-prices`, `stock-predictions`, `stock-signals`: PointInTimeRecoveryStatus ENABLED, 35-day window. Before-state saved in `infra/rollback/2026-10-22/pitr-before-*.json` (all DISABLED). Rollback: `aws dynamodb update-continuous-backups --table-name <t> --point-in-time-recovery-specification PointInTimeRecoveryEnabled=false`.

### 1b EventBridge bus `stock-events` + `stock-event-logger` — done 12:46 UTC
- Bus `stock-events` (no resource policy → only this account can put events). Rule `stock-events-log-all` (pattern `{"account":["542601847637"]}`, i.e. every event) → Lambda `stock-event-logger` (python3.12 arm64 128 MB, `src/event_logger/`).
- Role `stock-event-logger-role` (StockRoleBoundary; inline policy: its own log group only). Lambda permission limited to that rule ARN + source account.
- `logs:CreateLogGroup` is denied to the `stock-project` user, so (as for every existing function) the function role creates its own log group on first run; retention was then set to 30 days.
- Test: labelled event `source stock.test`, `ManualTest` (EventId 4f4b8b98-…) → logged as one JSON line. Unit tests `tests/test_event_logger.py` (2).

### 1c DynamoDB Streams + `stock-stream-handler` — deployed 12:50 UTC; live path pending the next scheduled run
- `stock-prices` stream enabled (NEW_IMAGE), stream ARN `…/stream/2026-10-22T12:47:43.682`. Table description before the change: `infra/rollback/2026-10-22/stock-prices-before-stream.json`. Rollback: delete the event source mapping, then `update-table --stream-specification StreamEnabled=false` (deletion → owner approval).
- Lambda `stock-stream-handler` (`src/stream_handler/`), role `stock-stream-handler-role` (boundary; stream read on `stock-prices` only, `events:PutEvents` on `stock-events` only, own logs; **no DynamoDB write, no SNS**).
- Event source mapping `16773a60-4c27-42bd-a6f5-7a9203cb29d9`: LATEST, batch 10, 2 retries, max record age 1 h, bisect on error, filter `eventName INSERT` and `NewImage.source.S = alphavantage` (`infra/lambda/stock-stream-handler-esm-filter.json`). The handler re-checks both conditions.
- Test (direct invoke, labelled `test-final-run-20261022-*`, symbol TEST, nothing written to DynamoDB): 3 records → 1 published (INSERT alphavantage); MODIFY and untagged INSERT skipped; the PriceIngested event appeared in the `stock-event-logger` log. Unit tests `tests/test_stream_handler.py` (4).
- Not yet observed: a real INSERT through the stream (no test rows are written to `stock-prices`; the scheduled run at 22:30 UTC will insert ~5 rows).

### Repository fix
`tests/secret_scan.py` was excluded by the `.gitignore` pattern `*secret*`, so the CI workflow would have failed on GitHub. Added `!tests/secret_scan.py`.

### 1d S3 `raw/` event → `stock-archive-validator` — done 2026-10-22 12:54 UTC
- Bucket notification configuration before the change: **empty** (`{}`), saved as `infra/rollback/2026-10-22/raw-bucket-notification-before.json`. `infra/s3/merge_notification.py` merges the new rule into whatever exists (keeps all other entries); applied `infra/s3/raw-bucket-notification.json`: `s3:ObjectCreated:*`, prefix `raw/` → `stock-archive-validator`. Rollback: `aws s3api put-bucket-notification-configuration --bucket stock-prediction-raw-542601847637-ap-south-1-an --notification-configuration file://infra/rollback/2026-10-22/raw-bucket-notification-before.json`.
- Lambda `stock-archive-validator` (`src/archive_validator/`, python3.12 arm64 128 MB, 60 s), role `stock-archive-validator-role` (boundary; `s3:GetObject` on `raw/*`, `s3:PutObject` on `manifests/*` only, own logs). Lambda permission: `s3.amazonaws.com`, source ARN = the bucket, source account.
- Checks per archive: JSON parses; `Meta Data` and `Time Series (Daily)` present; symbol matches the key; every day has numeric OHLCV; **no API key and no URL** (`api_?key`, `https?://`, `alphavantage.co`; only the finding names are stored, never the matched text). Writes one single-line JSON manifest to `manifests/<path after raw/>.manifest.json` with the checks and the parsed daily rows (so Athena can read it). Code refuses to write under `raw/`; the trigger prefix `raw/` does not cover `manifests/`, so it cannot trigger itself.
- Live test: labelled object `raw/_test/validator-test-20261022.json` (symbol TEST, "NOT market data") → S3 event → manifest `manifests/_test/validator-test-20261022.json.manifest.json`, status ok. **Both objects are on the cleanup list.**
- Backfill (direct invoke, 3 batches): all **44** existing `raw/alphavantage/` archives validated, **44 ok, 0 failed** (no key/URL found in any archive) → 44 manifests under `manifests/alphavantage/` (531,908 bytes).
- From the next scheduled run, each ingest archive (5 per weekday) is validated automatically.
- Unit tests `tests/test_archive_validator.py` (7).

### 1e Athena + Glue Data Catalog — done 2026-10-22 13:05 UTC
- Raw archives are pretty-printed nested JSON (Athena JSON SerDes need one record per line), so the tables read the single-line manifests from 1d instead; `raw/` is untouched.
- Workgroup `stock-workgroup` (enforced; results `athena-results/` SSE-S3; **BytesScannedCutoffPerQuery 10,485,760**, the minimum; CloudWatch metrics off). Glue database `stock_project`; table `archive_manifests` and view `daily_prices`, both hand-written DDL in `infra/athena/` (no crawler). Runner `infra/athena/run_query.py`.
- Tested queries in `docs/athena-queries.md`: days per ticker (AAPL 113, others 104 each), weekly change %, revised bars, archive quality (44 ok), and a cross-check: count and sum of closes per ticker match DynamoDB real rows exactly.
- Finding: across archives, 28 bars were revised and **only the volume** changed (no close ever changed). That is why every scheduled ingest reports `updated 1`. Consequence for decision B (skip only when `inserted == 0 and updated == 0`): on a normal day after a trading day `updated` is 1, so the skip will fire only when Alpha Vantage returns nothing new at all (e.g. a holiday run after the previous day's volume was already final).
- 9 Athena queries ran; each scanned ≤ 531,908 bytes (billed at the 10 MB minimum ≈ $0.00005 each).
