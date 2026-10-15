# Cloud Stock Price Monitoring and Prediction (AWS, ap-south-1)

College Cloud Computing + ML project. It ingests real daily AAPL prices from Alpha Vantage every weekday, computes signals, runs a TFLite LSTM prediction, persists everything, sends deduplicated email alerts, and serves a Cognito-protected API and dashboard. Everything is serverless.

- Status, decisions, limitations: [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md)
- Task list: [`TODO.md`](TODO.md)
- Architecture diagram: [`docs/architecture.md`](docs/architecture.md)
- AWS resource inventory: [`docs/aws-inventory.md`](docs/aws-inventory.md)
- Model evaluation (honest: the LSTM does not beat a naive baseline): [`docs/model-evaluation.md`](docs/model-evaluation.md)
- Demo script and viva Q&A: [`docs/demo-and-viva.md`](docs/demo-and-viva.md)

## Layout
```
src/ingest      Lambda stock-ingest         (Alpha Vantage → S3 raw + DynamoDB)
src/inference   Lambda stock-lstm-inference (predict / evaluate)
src/signals     Lambda stock-signals        (SMA/RSI/volatility + alert decision)
src/evaluate    Lambda stock-evaluate       (score predictions vs actual + naive baseline)
src/api         Lambda stock-api            (read-only HTTP API)
dashboard/      Static SPA (Chart.js, Cognito PKCE)
infra/          IAM policies, Step Functions generator, scheduler, alarm, CloudFront, Cognito IDs
tests/          python tests/run_all.py (needs boto3)   and   node tests/dashboard.test.js
```

## Run the dashboard locally
```
cd dashboard && python -m http.server 8080
```
Open http://localhost:8080/ and sign in with the Cognito user you created.

Prices are unadjusted and limited to the latest 100 trading days (Alpha Vantage free tier). The legacy synthetic rows from the prototype are kept but excluded from everything, and are labelled SYNTHETIC wherever they can be shown.
