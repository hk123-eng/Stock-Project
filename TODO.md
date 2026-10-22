# TODO — Cloud Stock Prediction Project

## Phase 0 — Audit (completed 2026-10-04, read-only; findings in PROJECT_CONTEXT.md §3–§6)
- [x] Inventory AWS resources in `ap-south-1`
- [x] Inspect Lambda code/configuration and layer (code + config inspected; layer versions/attachment checked, layer contents not inspected)
- [x] Inspect DynamoDB schema/data (114 synthetic AAPL rows; mixed `close` types; 14 duplicate dates)
- [x] Inspect S3 objects
- [x] Inspect Step Functions definition (plus all 5 executions)
- [x] Inspect SNS and IAM
- [x] Inspect CloudWatch logs
- [x] Confirm EventBridge status (no schedules, no rules)
- [x] Produce gap analysis
- [x] Avoid duplicate resources (audit created nothing; remains a standing rule for all later phases)

## Pending human decisions (from audit)
- [ ] Approve or decline deleting `stock-db-seeder` Lambda and `stock-db-seeder-role`
- [x] Synthetic rows: keep, never delete; real rows tagged `source=alphavantage`, all readers ignore untagged rows (decided by user 2026-10-05)
- [ ] Approve or decline deleting `layers/tflite-layer.zip` from S3 and layer version 1
- [x] DynamoDB write permission on `stock-lstm-inference-role`: added by user (`stock-predictions-write`, PutItem on `stock-*`)
- [x] Choose market-data API (Phase 1): Alpha Vantage, decided 2026-10-04
- [ ] Group-project question: if this is a team project, email support@alphavantage.co to confirm the use is allowed and request educational verification
- [x] Build permissions granted (StockIamScoped, StockProjectBuildAccess, StockProjectBuildAccessPhase3to6)
- [ ] **Contact AWS Support to verify the account for CloudFront** (still blocked 2026-10-15) (CreateDistribution: "Your account must be verified")
- [ ] Grant missing permission for Step Functions logging (JSON in PROJECT_CONTEXT.md §13)
- [x] Create your own Cognito user (2 users found in the pool on 2026-10-15; created by you)

## Phase 1 — Real data
- [x] Select free/low-cost stock API: Alpha Vantage free key, `TIME_SERIES_DAILY`, `outputsize=compact` (details and caveats in PROJECT_CONTEXT.md §8 Phase 1)
- [x] Obtain Alpha Vantage free API key (done by user)
- [x] Secure API credentials: SSM SecureString `/stock-project/alphavantage-api-key` (created by user, `alias/aws/ssm`); only `stock-ingest-role` may read it
- [x] Build ingestion Lambda `stock-ingest` (python3.12, arm64, `src/ingest/`), role `stock-ingest-role` (boundary + least-privilege inline policy), verified 2026-10-05
- [x] Never log full request URLs: verified 0 log events matching `apikey`/`alphavantage.co`; raw archive contains neither
- [x] Account for unadjusted prices: rows carry `adjusted=false`; documented as a limitation
- [x] Account for 100-data-point limit: documented; Phase 7 evaluation limited to this window
- [x] Validate/normalize data: OHLC/volume stored as DynamoDB Numbers (verified 100/100 `N`); invalid OHLC, symbol mismatch, non-numeric values are rejected (unit tests)
- [x] Write DynamoDB: 100 real rows 2026-05-12 → 2026-10-02 tagged `source=alphavantage`, `data_type=real`; idempotent (re-run: 0 inserted, 100 unchanged)
- [x] Coexistence with synthetic rows: real rows keyed at US close time in UTC (20:00Z/21:00Z), never colliding with synthetic keys; conditional write refuses to overwrite non-Alpha-Vantage rows (verified against a synthetic key); synthetic rows verified byte-identical to the audit snapshot
- [x] Archive raw data to S3 under `raw/alphavantage/<SYMBOL>/<latest date>/`
- [x] Handle API failures/rate limits: rate-limit `Note`/`Information`, `Error Message`, HTTP/network errors raise sanitized errors (unit-tested; live rate limit not triggered on purpose)
- [x] Test ingestion: 6 unit tests (`tests/test_ingest.py`) pass; 3 live invocations (bad input, first load, idempotent re-run)
- [x] Log retention 30 days on `/aws/lambda/stock-ingest`, `stock-lstm-inference`, `stock-db-seeder`

## Phase 2 — Automation
- [x] EventBridge Scheduler `stock-daily-pipeline`: `cron(30 18 ? * MON-FRI *)` America/New_York (2.5 h after US close), role `stock-scheduler-role` (boundary; `states:StartExecution` on the pipeline only; trust limited by `aws:SourceAccount`)
- [x] Connect to Step Functions: verified with one-time schedule `stock-test-once-20261005` → execution SUCCEEDED with input `{"symbol":"AAPL"}`
- [x] Pass symbol correctly: explicit `{"symbol":"AAPL"}`; `ValidateInput` Choice (IsPresent/IsString/allow-list) → `InvalidInput` → SNS alert (verified with `{}` and `[1,2]`, no `States.Runtime`)
- [x] Persist predictions to DynamoDB `stock-predictions` (symbol / as_of_date), idempotent per as_of_date; inference now uses real rows only (`source=alphavantage`), synthetic rows ignored
- [x] Test automated run: manual valid run and scheduler-triggered run both SUCCEEDED
- [x] Retries/failure handling: Lambda service-error retries, 1 retry for `IngestError`, every Task catches `States.ALL` → `PublishFailure` (SNS); alarm `stock-pipeline-failed-executions` (Failed+TimedOut+Aborted ≥ 1) → SNS covers anything that escapes (verified: ALARM + SNS action succeeded)
- [x] Inference rollback point: Lambda version 1 = original code
- [ ] Enable Step Functions execution logging: BLOCKED, missing permission (see PROJECT_CONTEXT.md "Permissions requested")
- [ ] Delete inert one-time test schedule `stock-test-once-20261005` (needs approval + `scheduler:DeleteSchedule`)

## Phase 3 — Analytics + alerts
- [x] Calculate signals: Lambda `stock-signals` (python3.12, role `stock-signals-role`): close, change %, SMA20, SMA50, RSI14 (Wilder), 20-day volatility, from real rows only → DynamoDB `stock-signals` (symbol / trade_date)
- [x] Define alert thresholds: BIG_MOVE ±3%, SMA20/SMA50 cross, RSI14 entering ≥70/≤30, PREDICTED_MOVE ±2% (env vars `BIG_MOVE_PCT`, `PRED_MOVE_PCT`, `RSI_HIGH`, `RSI_LOW`)
- [x] Prevent alert spam: transition-only rules + at most one alert per (symbol, trade_date) via conditional write on `alert_sent_at`; no daily "success" email any more (verified: 2nd run on same day → `deduplicated: true`, no publish)
- [x] Add CloudWatch alarms: `stock-pipeline-failed-executions` (see Phase 2)
- [x] Test SNS: alert published via `PublishAlert` (test with temporary `PRED_MOVE_PCT=0.1`, restored to 2); failure alerts published via `PublishFailure`
- [x] Unit tests: `tests/test_signals.py` (8) + `tests/test_ingest.py` (6), run with `python tests/run_all.py`, all pass
- Fixed during testing: `close` is a DynamoDB reserved word; the signals update now uses attribute-name placeholders

## Phase 4 — API
- [x] Design API: HTTP API `stock-dashboard-api` (`sjdmkf8iag`) → Lambda `stock-api` (read-only role `stock-api-role`)
- [x] Latest price endpoint `GET /prices/latest`
- [x] Historical price endpoint `GET /prices` (real only; reports count of excluded synthetic rows) and `GET /prices/synthetic` (explicitly labelled)
- [x] Latest prediction endpoint `GET /predictions/latest`
- [x] Prediction history endpoint `GET /predictions` (joined with the actual next real close + error)
- [x] Signals endpoint `GET /signals`; also `GET /alerts`, `GET /evaluation`
- [x] Test API: all 8 routes + 404/400/405 cases via direct Lambda invocation (2026-10-05)

## Phase 5 — Authentication
- [x] Cognito user pool `stock-dashboard-users` (`ap-south-1_OsBj5ZbkR`, Lite, admin-only sign-up, deletion protection), hosted UI domain, public SPA client (code + PKCE). 0 users.
- [x] Protect API: JWT authorizer on all 8 routes; throttle 10 rps / burst 20; CORS allow-list
- [x] Test authentication: no token / garbage / forged unsigned token → 401; unknown route/POST → 404; CORS only for allowed origin; hosted UI 200, unregistered redirect rejected, no sign-up link
- [ ] Test authenticated request end-to-end (needs the user's own Cognito login)
- [x] Verify least privilege: all new roles have StockRoleBoundary + scoped inline policies (see docs/aws-inventory.md)
- [ ] Optional MFA (needs `cognito-idp:SetUserPoolMfaConfig`, not granted)

## Phase 6 — Dashboard
- [x] Frontend `dashboard/` (static HTML/CSS/JS, CSP, Cognito PKCE login, sessionStorage tokens)
- [x] Chart.js 4.4.1 from cdnjs with SRI
- [x] Current price, historical chart, prediction (+ out-of-range warning), prediction history with actuals, signals, alerts, evaluation card
- [x] Synthetic rows hidden by default; opt-in toggle shows them labelled SYNTHETIC
- [x] Offline tests `node tests/dashboard.test.js` pass; JS syntax checks pass
- [x] S3 hosting: private bucket `stock-dashboard-542601847637-ap-south-1` (Block Public Access ×4, anonymous GET → 403), files uploaded
- [x] CloudFront OAC `E1BHMZIJ62GXYK` created
- [ ] CloudFront distribution: BLOCKED by account verification; then run `infra/cloudfront/finish-cloudfront.sh`
- [ ] Browser test of the signed-in dashboard (needs the user's login)

## Phase 7 — ML validation
- [ ] Inspect training data: not possible, because no training code/data is in the repo or S3
- [x] Inspect scaler/model ranges: MinMaxScaler, 1,674 samples, $54.12–$339.79; recent real closes reach $341.07
- [x] Document model version (stored on every prediction item)
- [x] Define prediction target: next trading day close (inferred; training code unavailable)
- [x] Compare predictions vs actuals: `GET /predictions` scores each live prediction against the next real close
- [x] Basic backtesting/evaluation: 40-day walk-forward on real prices; LSTM MAE $6.18 vs naive $3.33 (docs/model-evaluation.md)
- [x] Document limitations
- [ ] Retrain on longer adjusted data and re-fit scaler (recommended, out of scope)

## Phase 8 — Improvements (plan approved 2026-10-06; one item at a time)
### 1. Prediction scoring + model health
- [x] Lambda `stock-evaluate` + bounded role `stock-evaluate-role`; scores unscored predictions, stores model + naive error, publishes `StockProject/ModelHealth` metrics (live-tested 2026-10-06: 1 scored, re-run idempotent)
- [x] Pipeline step `ScorePredictions` after the alert step (validated, deployed; failure path re-tested)
- [x] Observe the first scheduled run with ScorePredictions (verified 2026-10-15: 7 scheduled runs 2026-10-07 → 2026-10-15 SUCCEEDED, 8 predictions scored)
- [x] `GET /model-health` (JWT) with "insufficient data" below 20 scored days; `/predictions` uses stored scores
- [x] Dashboard Model health panel + offline tests; uploaded to private bucket
- [ ] Signed-in browser check of the panel (needs the user's login)
### 2. MACD + Bollinger signals, per-type alert dedup (2026-10-15)
- [x] MACD(12,26,9), Bollinger(20, 2σ population) in `stock-signals`; rules MACD_CROSS, BOLLINGER_BREAK (transition-only, switchable)
- [x] Dedup per (symbol, trade_date, type) via `alert_sent_<TYPE>`; live-verified by direct invocation (repeat → `already_sent`)
- [x] Known-value tests (hand-computed) `tests/test_signals_macd_bb.py`; API `notified_types`/`test_alert`; dashboard values + bands
- [x] Observe a pipeline run with the new signals code (scheduled run 2026-10-15 22:30 UTC SUCCEEDED; watchlist test run 23:01 UTC raised NVDA BOLLINGER_BREAK)
### 3. Watchlist AAPL MSFT GOOGL AMZN NVDA, one combined alert email per run (2026-10-15)
- [x] Map definition generated + validated (`--watchlist`), structural tests `tests/test_state_machine.py`
- [x] Lambda `stock-alert-digest` + bounded role; tests `tests/test_digest.py`; direct invocation OK
- [x] Ingest: DailyLimitError vs RateLimitError (HTTP-200 throttle messages), suspicious-jump (split) check; deployed (rollback `stock-ingest:1`)
- [x] API allow-list + "no validated model" 404s; dashboard ticker selector + smoke test; deployed/uploaded
- [x] Switch state machine + schedule input `{"symbols":[...]}` (2026-10-15 23:01 UTC); full test run SUCCEEDED in 90 s, 4 new tickers backfilled 100 rows each, 0 suspicious jumps
- [x] Forced per-ticker failure test (`["AAPL","ZZZZ"]`): SUCCEEDED, ZZZZ reported failed, email "1 FAILED"; also `{}` → FAILED via PublishFailure and legacy `{"symbol":"AAPL"}` → SUCCEEDED
- [ ] First scheduled watchlist run (2026-10-16 18:30 ET): check it in the console or email
- [ ] Not tested live: a ticker failing inside a Lambda; a real Alpha Vantage throttle
### 4. Retraining plan document
- [x] `docs/retraining-plan.md` (2026-10-15). Nothing trained.
### 5. CI, CloudWatch dashboard, Scheduler DLQ
- [x] 5a: local git + `.gitignore` + secret scan + `.github/workflows/ci.yml` (no remote; you create the repo and push)
- [x] 5b: CloudWatch dashboard `stock-project` (36 metrics)
- [x] 5c: SQS `stock-pipeline-dlq` (SSE-SQS, 14 d, scheduler-only policy), scheduler role `sqs:SendMessage`, alarms `stock-pipeline-dlq-not-empty` + `stock-pipeline-dlq-new-message`
- [x] 5c: DLQ test via inert schedule `stock-test-dlq-20261015`: message in DLQ, both alarms → ALARM → SNS (2026-10-15)
- [x] 5c: DLQ attached to `stock-daily-pipeline` (2026-10-15 23:01 UTC, verified with get-schedule)
- [ ] Purge the DLQ test message (optional; it expires ~2026-10-29); until then `stock-pipeline-dlq-not-empty` stays in ALARM

## Phase 9 — stretch (checked 2026-10-15)
- [ ] (a) Athena + Glue table — parked, permissions missing (JSON in docs/RUN-REPORT.md)
- [ ] (b) EventBridge custom bus + rule — parked, permissions missing
- [ ] (c) X-Ray — parked (boundary lacks xray actions; pipeline role must not be edited; HTTP API unsupported)
- [x] (d) API Gateway throttling — already 10 rps / burst 20
- [ ] (e) TTL/lifecycle — S3 lifecycle denied; DynamoDB TTL deliberately not enabled (no test-only data)
- [ ] CloudTrail, Cognito groups, SAM/CloudFormation, Bedrock — plan notes only (docs)

## Cleanup
- [ ] Confirm seeder is no longer needed (last used 2026-09-16; not yet confirmed)
- [ ] Delete seeder Lambda only after approval
- [ ] Delete seeder IAM role only after approval
- [ ] Delete `layers/tflite-layer.zip` (81 MB) from S3 only after approval
- [ ] Delete unused layer `tflite-runtime-py310` v1 only after approval
- [x] Set retention on Lambda log groups: 30 days on all six `/aws/lambda/stock-*` (incl. `stock-evaluate`, 2026-10-06)
- [ ] Delete inert test schedules `stock-test-once-20261005` and `stock-test-dlq-20261015` (approval + permission)
- [ ] Remove unused permissions
- [ ] Verify no public resources (audit checked: S3 Block Public Access on and no bucket policy; no Lambda resource policies or function URLs; SNS policy limited to this account; no API Gateway/CloudFront. Not a full account-wide check.)
- [ ] Review AWS cost (zero-spend budget exists; Cost Explorer not reviewed)

## Final demo
- [x] Architecture diagram (`docs/architecture.md`, Mermaid)
- [x] AWS resource inventory (`docs/aws-inventory.md`)
- [ ] Screenshots (after login exists)
- [x] End-to-end demo script (`docs/demo-and-viva.md`)
- [ ] Project report
- [x] Viva Q&A (`docs/demo-and-viva.md`)

## Final run (2026-10-22) — work order items
### 1. Additive items
- [x] 1a DynamoDB PITR on stock-prices, stock-predictions, stock-signals (ENABLED, 35 days)
- [x] 1b EventBridge bus `stock-events` + rule `stock-events-log-all` → `stock-event-logger` (test event logged)
- [x] 1c Stream on stock-prices (NEW_IMAGE) + `stock-stream-handler` (filtered ESM; direct-invoke test OK)
- [ ] 1c Observe a real INSERT → PriceIngested in the logger log (after the 2026-10-22 22:30 UTC scheduled run)
- [x] 1d S3 raw/ event → `stock-archive-validator` (test object + 44-archive backfill: 44 ok)
- [x] 1e Athena + Glue (`stock_project`, `stock-workgroup`), docs/athena-queries.md
- [x] 1f 2 log metric filters (IngestErrors, IngestThrottles) + 2 dashboard widgets
- [x] 1g Cognito groups viewer/admin (0 members) + GET /me (401 without token; signed-in check pending your login)
### 2. Live Lambdas (window 19:00–09:30 ET only)
- [ ] X-Ray active tracing (not stock-lstm-inference); state machine tracing parked (IAM JSON)
- [ ] SNS message attributes — PARKED by owner decision A (2026-10-22)
- [ ] `stock-api` alias `live` + API integration repoint + route tests
### 3. State machine (window 19:00–09:30 ET only)
- [ ] Parallel Signals ‖ Score per ticker; skip Predict + Signals when inserted == 0 and updated == 0 (decision B)
### 4–7
- [ ] SFN logging: IAM JSON shown to owner; enable ERROR logging + 30-day retention after confirmation
- [ ] Local baseline benchmark → docs/model-evaluation.md
- [ ] GitHub remote + push after "push"
- [ ] Final docs
