# Cloud Stock Price Monitoring and Prediction (AWS, ap-south-1)

College Cloud Computing + ML project. Every weekday it ingests real daily prices for a five-ticker watchlist (AAPL, MSFT, GOOGL, AMZN, NVDA) from Alpha Vantage, computes signals (SMA, RSI, volatility, MACD, Bollinger bands), runs a TFLite LSTM prediction for AAPL only (experimental: it does not beat a naive baseline), persists everything, sends one combined, deduplicated email per run, and serves a Cognito-protected API and dashboard. Everything is serverless.

- Status, decisions, limitations: [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)
- Task list: [`TODO.md`](TODO.md)
- Architecture diagram: [`docs/architecture.md`](docs/architecture.md)
- AWS resource inventory: [`docs/aws-inventory.md`](docs/aws-inventory.md)
- Model evaluation (honest: the LSTM does not beat a naive baseline): [`docs/model-evaluation.md`](docs/model-evaluation.md)
- Demo script and viva Q&A: [`docs/demo-and-viva.md`](docs/demo-and-viva.md)
- Retraining plan (not executed): [`docs/retraining-plan.md`](docs/retraining-plan.md)
- Phase 9 notes: [`docs/phase9-notes.md`](docs/phase9-notes.md)
- Run log, parked permissions, manual steps: [`docs/RUN-REPORT.md`](docs/RUN-REPORT.md)

## Layout
```
src/ingest      Lambda stock-ingest         (Alpha Vantage → S3 raw + DynamoDB)
src/inference   Lambda stock-lstm-inference (predict / evaluate)
src/signals     Lambda stock-signals        (SMA/RSI/volatility/MACD/Bollinger + alert decision)
src/digest      Lambda stock-alert-digest   (one combined email per run)
src/evaluate    Lambda stock-evaluate       (score predictions vs actual + naive baseline)
src/api         Lambda stock-api            (read-only HTTP API, 5-ticker allow-list)
dashboard/      Static SPA (Chart.js, Cognito PKCE)
infra/          IAM policies, Step Functions generator + switch/rollback scripts, scheduler, SQS, alarms,
                CloudWatch dashboard, CloudFront, Cognito IDs, time_guard.py
tests/          python tests/run_all.py (needs boto3)   and   node tests/dashboard.test.js
.github/        CI workflow (tests + secret scan, no AWS credentials)
```

## Run the dashboard locally
```
cd dashboard && python -m http.server 8080
```
Open http://localhost:8080/ and sign in with the Cognito user you created.

Prices are unadjusted and limited to the latest 100 trading days (Alpha Vantage free tier); a ≥ 25% day-over-day jump is flagged as a possible split. The legacy synthetic rows from the prototype are kept but excluded from everything, and are labelled SYNTHETIC wherever they can be shown.
