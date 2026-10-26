# Demo script and viva Q&A

## Before the demo (one-time)
1. **Create your login** (Cognito console → user pool `stock-dashboard-users` → Create user, with your email and a temporary password). Sign-up is admin-only by design.
2. **Dashboard URL:** after CloudFront is unblocked and `infra/cloudfront/finish-cloudfront.sh` has run, use `https://<distribution>.cloudfront.net/`. Until then, run it locally:
   `cd dashboard && python -m http.server 8080`, then open `http://localhost:8080/` (registered as a Cognito callback).
3. Confirm the SNS email subscription still works (test emails were sent on 2026-10-05 and 2026-10-15).
4. Alpha Vantage budget: each 5-ticker run uses 5 of the 25 daily calls. Keep demo runs to one or two, and never run during US market hours (a provisional close would be scored).

## 10-minute demo flow
| # | Show | Say |
|---|---|---|
| 1 | `docs/architecture.md` diagram | "Serverless pipeline in Mumbai: Scheduler → Step Functions (a Map over a 5-ticker watchlist) → five Lambdas → DynamoDB/S3 → one combined SNS email, plus a Cognito-protected API and dashboard." |
| 2 | EventBridge Scheduler → `stock-daily-pipeline` | "Runs Mon–Fri 18:30 New York time, after the US close, with input `{"symbols":["AAPL","MSFT","GOOGL","AMZN","NVDA"]}`; failed starts go to the SQS dead-letter queue." |
| 3 | Step Functions → open the latest scheduled execution (or start one with `{"symbols":["AAPL","NVDA"]}` = 2 API calls) → graph view | The Map runs one ticker at a time with a 15 s pause. Open an IngestPrices output: `unchanged 100` shows idempotency; `data_quality` shows the split/jump check. Only AAPL goes through Predict; Signals and Score run as a Parallel state. A repeat run with nothing new takes the skip path (`skipped: "no new or updated rows"`, e.g. `test-parallel-20261026T040642`). |
| 3b | Start an execution with `{"symbols":["AAPL","ZZZZ"]}` | AAPL is processed; ZZZZ fails alone; the run SUCCEEDS and the email subject says "1 FAILED". |
| 4 | Start an execution with `{}` | Goes ValidateInput → InvalidInput → PublishFailure; show the failure email. "Before, this was an unhandled `States.Runtime` error with no alert." |
| 5 | CloudWatch → Alarms → `stock-pipeline-failed-executions` | "Safety net: any failed, timed-out or aborted run alerts by email, even errors the workflow can't catch." |
| 6 | DynamoDB → `stock-prices` → query AAPL | Point out `source=alphavantage`, `data_type=real`, Number types, and the legacy synthetic rows with no `source` that are ignored everywhere. |
| 7 | S3 `raw/alphavantage/…` | "Raw API responses archived for audit; the API key is never stored or logged." |
| 8 | Dashboard → sign in (Cognito hosted UI) | Latest close, prediction (with out-of-range warning, labelled experimental), signals incl. MACD and Bollinger %B, alerts, prediction history. Tick "Show Bollinger bands". |
| 8b | Ticker selector → NVDA | "Prices and signals only; no validated model": the prediction panels are hidden and the API returns 404 for model routes. |
| 8c | CloudWatch → Dashboards → `stock-project` | Executions, tickers processed/failed, DLQ depth, Lambda errors, API traffic, AAPL model vs naive error, ingest errors/throttles. |
| 8d | CloudWatch → X-Ray traces (filter `stock-ingest`) | One trace shows ingest → S3 put → `stock-archive-validator`. |
| 8e | CloudWatch Logs `/aws/lambda/stock-event-logger` | A `PriceIngested` event per new real row, from DynamoDB Streams via the `stock-events` bus. |
| 9 | Toggle "Show legacy synthetic rows" | The dashed grey series is labelled SYNTHETIC; it's off by default. |
| 10 | Model evaluation card / `docs/model-evaluation.md` | "Honest result: the LSTM's MAE is $6.18 vs $3.33 for the naive baseline. It does not beat 'tomorrow = today'." |
| 11 | `curl` the API with no token → 401 | "Every route needs a Cognito JWT." |

## Viva Q&A

**Q: Why serverless?**
The workload runs once a day for seconds. Lambda, Step Functions, DynamoDB on-demand, Scheduler and HTTP API all bill per use, and the expected cost is $0/month inside free tiers. EC2, RDS or a NAT gateway would cost money 24/7.

**Q: Why Step Functions instead of one big Lambda?**
Visible per-step state, built-in retries and catches, a failure path that always alerts, an execution history for auditing, and each Lambda keeps its own least-privilege role.

**Q: How do you stop duplicate data?**
Rows are keyed by (symbol, US close time in UTC); ingestion skips identical rows and uses a conditional put. Predictions are keyed by (symbol, as_of_date). Each alert type has its own conditional flag `alert_sent_<TYPE>` per (symbol, trading day), so a rule is emailed at most once, and two different rules on the same day both get reported. All new alerts of a run go into ONE email.

**Q: Why a Map with MaxConcurrency 1?**
The Alpha Vantage free tier allows 25 calls per day and throttles bursts. Five tickers sequentially with a 15 s gap use 5 calls and never burst. A throttle comes back as HTTP 200 with a "Note"/"Information" message; the code turns the daily-quota message into `DailyLimitError` (never retried) and others into `RateLimitError` (1 retry after 60 s).

**Q: What if one ticker fails?**
Each ticker has its own Catch. The other tickers continue, the run still succeeds, and the single digest email lists the failed ticker (tested live with `["AAPL","ZZZZ"]`). A failure of the whole run (bad input, digest or SNS error) still fails the execution and triggers the alarm.

**Q: Why only AAPL predictions?**
The LSTM was trained on AAPL only and does not beat a naive baseline even there. Running it on other tickers would produce numbers with no validation, so the other tickers get prices and signals only.

**Q: Prices are unadjusted. What about stock splits?**
Ingestion flags any day-over-day close change of 25% or more as a possible split and reports it in the email; if new AAPL data contains one, that run skips the prediction. History is not adjusted (the adjusted endpoint is premium-only). On 2026-10-15 no ticker had such a jump in its 100-day window.

**Q: What about the synthetic data from the prototype?**
It was kept (nothing is deleted) but isolated. Real rows are tagged `source=alphavantage`; every reader (inference, signals, API) filters on that tag. The real sort-key times (20:00Z/21:00Z) can't collide with the synthetic ones, and writes refuse to overwrite a non-Alpha-Vantage row. The dashboard only shows synthetic rows on request, labelled SYNTHETIC.

**Q: How is the API key protected?**
It's an SSM SecureString encrypted with KMS. Only `stock-ingest-role` can read it. It's never logged, returned or archived. Alpha Vantage requires the key in the URL, so the code never logs URLs and re-raises network errors without them. Logs and archives were searched to confirm the key isn't present.

**Q: How does authentication work?**
Cognito hosted UI with the OAuth authorization-code flow and PKCE (a public SPA client, no secret). The browser sends the ID token to API Gateway, whose JWT authorizer checks signature, issuer, audience and expiry before the Lambda runs. Forged and unsigned tokens get 401. Self sign-up is disabled.

**Q: How is the dashboard hosted without a public bucket?**
A private S3 bucket (Block Public Access on) behind CloudFront with Origin Access Control: the bucket policy allows `s3:GetObject` only to that one distribution. (Distribution pending AWS account verification.)

**Q: Why run Signals and Score in parallel, and when is a ticker skipped?**
They are independent (signals read prices, scoring reads predictions and prices), so a Parallel state runs both; each branch catches its own errors so one cannot cancel the other. If ingest reports `inserted == 0 and updated == 0`, nothing changed, so Predict and Signals are skipped and only AAPL scoring runs (tested live 2026-10-26).

**Q: How do you trace a run?**
X-Ray active tracing on the 8 project Lambdas. The trace header travels with the S3 put, so an ingest trace also contains the archive validator. HTTP APIs do not support X-Ray; state-machine tracing needs a permission that has not been granted.

**Q: What is least privilege here?**
Each Lambda has its own role scoped to exact tables, prefixes and the one SSM parameter. All new roles carry the `StockRoleBoundary` permissions boundary. The scheduler role can only start this one state machine.

**Q: How accurate is the model?**
Measured on 40 real trading days: MAE $6.18, RMSE $7.03, MAPE 1.91%, directional accuracy 50%. The naive baseline gets MAE $3.33, so **the model is worse than the baseline.** Likely causes: prices above the scaler's training range ($54–$340), unknown training data, and a single input feature. The system design works regardless; the model is the weak component and is clearly labelled as such.

**Q: Then why keep the LSTM?**
The project is about the cloud ML pipeline (deployment, scheduling, persistence, monitoring, evaluation). The pipeline measures and publishes the model's real error, which is how you'd detect a weak model in production. Retraining is the documented next step.

**Q: Limitations?**
Alpha Vantage free tier: unadjusted prices, 100 trading days, 25 requests per day (5 used per run). Predictions for AAPL only, and the model does not beat the naive baseline. Splits are detected, not corrected. US holidays aren't modelled (runs are harmless no-ops). Step Functions execution logging and state-machine tracing are not set up (missing permissions). CloudFront is pending. Evaluation samples are small (40 backtest points; 15 live scored days as of 2026-10-26, model MAE $4.56 vs naive $2.27, no verdict below 20). CI exists but has never run on GitHub (no remote yet).

**Q: What does it cost?**
Expected $0.00/month inside free tiers; worst case without free tiers is well under $0.50/month at this usage. A $1 zero-spend budget alert exists.

**Q: What happens if Alpha Vantage is down or rate-limited?**
The ingest Lambda raises a sanitized `IngestError` or `RateLimitError`; Step Functions retries once after 60 s. If it still fails, only that ticker is marked failed and the digest email says so (a daily-quota error is not retried). Existing data is untouched; the next scheduled run catches up because each call returns the last 100 days.

**Q: What if the scheduler itself cannot start the pipeline?**
EventBridge Scheduler retries twice within an hour, then puts the event into the SQS dead-letter queue `stock-pipeline-dlq`; two CloudWatch alarms email on it. This was tested with a one-time schedule pointing at a non-existent state machine.
