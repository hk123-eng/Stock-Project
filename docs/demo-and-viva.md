# Demo script and viva Q&A

## Before the demo (one-time)
1. **Create your login** (Cognito console → user pool `stock-dashboard-users` → Create user, with your email and a temporary password). Sign-up is admin-only by design.
2. **Dashboard URL:** after CloudFront is unblocked and `infra/cloudfront/finish-cloudfront.sh` has run, use `https://<distribution>.cloudfront.net/`. Until then, run it locally:
   `cd dashboard && python -m http.server 8080`, then open `http://localhost:8080/` (registered as a Cognito callback).
3. Confirm the SNS email subscription still works (you should have received test alerts on 2026-10-05).

## 10-minute demo flow
| # | Show | Say |
|---|---|---|
| 1 | `docs/architecture.md` diagram | "Serverless pipeline in Mumbai: Scheduler → Step Functions → three Lambdas → DynamoDB/S3 → SNS, plus a Cognito-protected API and dashboard." |
| 2 | EventBridge Scheduler → `stock-daily-pipeline` | "Runs Mon–Fri 18:30 New York time, after the US close, with an explicit `{"symbol":"AAPL"}`." |
| 3 | Step Functions → start execution `{"symbol":"AAPL"}` → graph view | Each step turns green. Open the IngestPrices output: `rows_received 100, unchanged 100`, which shows idempotency. |
| 4 | Start an execution with `{}` | Goes ValidateInput → InvalidInput → PublishFailure; show the failure email. "Before, this was an unhandled `States.Runtime` error with no alert." |
| 5 | CloudWatch → Alarms → `stock-pipeline-failed-executions` | "Safety net: any failed, timed-out or aborted run alerts by email, even errors the workflow can't catch." |
| 6 | DynamoDB → `stock-prices` → query AAPL | Point out `source=alphavantage`, `data_type=real`, Number types, and the legacy synthetic rows with no `source` that are ignored everywhere. |
| 7 | S3 `raw/alphavantage/…` | "Raw API responses archived for audit; the API key is never stored or logged." |
| 8 | Dashboard → sign in (Cognito hosted UI) | Latest close, prediction (with out-of-range warning), signals, alerts, prediction history. |
| 9 | Toggle "Show legacy synthetic rows" | The dashed grey series is labelled SYNTHETIC; it's off by default. |
| 10 | Model evaluation card / `docs/model-evaluation.md` | "Honest result: the LSTM's MAE is $6.18 vs $3.33 for the naive baseline. It does not beat 'tomorrow = today'." |
| 11 | `curl` the API with no token → 401 | "Every route needs a Cognito JWT." |

## Viva Q&A

**Q: Why serverless?**
The workload runs once a day for seconds. Lambda, Step Functions, DynamoDB on-demand, Scheduler and HTTP API all bill per use, and the expected cost is $0/month inside free tiers. EC2, RDS or a NAT gateway would cost money 24/7.

**Q: Why Step Functions instead of one big Lambda?**
Visible per-step state, built-in retries and catches, a failure path that always alerts, an execution history for auditing, and each Lambda keeps its own least-privilege role.

**Q: How do you stop duplicate data?**
Rows are keyed by (symbol, US close time in UTC); ingestion skips identical rows and uses a conditional put. Predictions are keyed by (symbol, as_of_date). Alerts use a conditional write on `alert_sent_at`, so at most one email per trading day.

**Q: What about the synthetic data from the prototype?**
It was kept (nothing is deleted) but isolated. Real rows are tagged `source=alphavantage`; every reader (inference, signals, API) filters on that tag. The real sort-key times (20:00Z/21:00Z) can't collide with the synthetic ones, and writes refuse to overwrite a non-Alpha-Vantage row. The dashboard only shows synthetic rows on request, labelled SYNTHETIC.

**Q: How is the API key protected?**
It's an SSM SecureString encrypted with KMS. Only `stock-ingest-role` can read it. It's never logged, returned or archived. Alpha Vantage requires the key in the URL, so the code never logs URLs and re-raises network errors without them. Logs and archives were searched to confirm the key isn't present.

**Q: How does authentication work?**
Cognito hosted UI with the OAuth authorization-code flow and PKCE (a public SPA client, no secret). The browser sends the ID token to API Gateway, whose JWT authorizer checks signature, issuer, audience and expiry before the Lambda runs. Forged and unsigned tokens get 401. Self sign-up is disabled.

**Q: How is the dashboard hosted without a public bucket?**
A private S3 bucket (Block Public Access on) behind CloudFront with Origin Access Control: the bucket policy allows `s3:GetObject` only to that one distribution. (Distribution pending AWS account verification.)

**Q: What is least privilege here?**
Each Lambda has its own role scoped to exact tables, prefixes and the one SSM parameter. All new roles carry the `StockRoleBoundary` permissions boundary. The scheduler role can only start this one state machine.

**Q: How accurate is the model?**
Measured on 40 real trading days: MAE $6.18, RMSE $7.03, MAPE 1.91%, directional accuracy 50%. The naive baseline gets MAE $3.33, so **the model is worse than the baseline.** Likely causes: prices above the scaler's training range ($54–$340), unknown training data, and a single input feature. The system design works regardless; the model is the weak component and is clearly labelled as such.

**Q: Then why keep the LSTM?**
The project is about the cloud ML pipeline (deployment, scheduling, persistence, monitoring, evaluation). The pipeline measures and publishes the model's real error, which is how you'd detect a weak model in production. Retraining is the documented next step.

**Q: Limitations?**
Alpha Vantage free tier: unadjusted prices, 100 trading days, 25 requests per day. Single symbol (AAPL). US holidays aren't modelled (runs are harmless no-ops). Step Functions execution logging is off (missing permission). CloudFront is pending. Evaluation sample is small (40 points).

**Q: What does it cost?**
Expected $0.00/month inside free tiers; worst case without free tiers is well under $0.50/month at this usage. A $1 zero-spend budget alert exists.

**Q: What happens if Alpha Vantage is down or rate-limited?**
The ingest Lambda raises a sanitized `IngestError`. Step Functions retries once after 60 s, then publishes a failure alert, and the CloudWatch alarm also fires. Existing data is untouched; the next scheduled run catches up because each call returns the last 100 days.
