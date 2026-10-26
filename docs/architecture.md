# Architecture — Cloud Stock Price Monitoring and Prediction

Region `ap-south-1` (Mumbai), account `542601847637`. Everything is serverless and pay-per-use.
Verified live on 2026-10-05; watchlist, digest, DLQ and dashboard parts verified 2026-10-15; events, validator, Athena (2026-10-22), parallel/skip definition, X-Ray and the `stock-api:live` alias verified 2026-10-26. Items marked **pending** are not live.

## End-to-end flow (parallel/skip definition, live since 2026-10-26 04:06 UTC)

```mermaid
flowchart LR
    subgraph Schedule
        SCH["EventBridge Scheduler<br/>stock-daily-pipeline<br/>Mon–Fri 18:30 America/New_York<br/>input symbols AAPL MSFT GOOGL AMZN NVDA"]
        DLQ[("SQS stock-pipeline-dlq<br/>failed starts, SSE-SQS, 14 d")]
    end

    subgraph Pipeline["Step Functions: stock-prediction-pipeline (timeout 1800 s)"]
        V{"ValidateInput<br/>symbols: 1–5 items<br/>or legacy symbol"}
        subgraph MAP["ProcessWatchlist (Map, MaxConcurrency 1)"]
            CS{"CheckSymbol<br/>allow-listed?"}
            W["Wait 15 s<br/>(not before the 1st ticker)"]
            ING["IngestPrices<br/>Lambda stock-ingest<br/>+ split/jump check"]
            ND{"CheckNewData<br/>inserted == 0 and<br/>updated == 0?"}
            NN["NoNewData → ScoreNoNewData<br/>(AAPL only) → TickerNoNewData"]
            RM{"RouteModel<br/>AAPL and no new jump?"}
            PRED["Predict<br/>Lambda stock-lstm-inference<br/>(TFLite LSTM, AAPL only)"]
            subgraph PAR["Parallel SignalsAndScore (each branch catches its own errors)"]
                SIG["ComputeSignals<br/>Lambda stock-signals<br/>SMA/RSI/MACD/Bollinger"]
                SCORE["ScorePredictions<br/>Lambda stock-evaluate<br/>(AAPL only)"]
            end
            TF["Ticker…Failed<br/>(per-ticker result,<br/>other tickers continue)"]
            CS -- yes --> W --> ING --> ND
            ND -- yes --> NN
            ND -- no --> RM
            RM -- yes --> PRED --> PAR
            RM -- no --> PAR
            CS -- no --> TF
            ING -. error .-> TF
            PRED -. error .-> TF
            SIG -. error .-> TF
            SCORE -. error .-> TF
        end
        DG["BuildDigest<br/>Lambda stock-alert-digest"]
        DN{"DigestNeeded?<br/>(new alerts, warnings<br/>or failed tickers)"}
        PUBD["PublishDigest<br/>ONE email per run"]
        PUBF["PublishFailure"]
        V -- valid --> MAP --> DG --> DN
        DN -- yes --> PUBD
        V -- invalid --> PUBF
        MAP -. error .-> PUBF
        DG -. error .-> PUBF
    end

    AV[("Alpha Vantage<br/>TIME_SERIES_DAILY<br/>compact, unadjusted<br/>1 call per ticker")]
    SSM[("SSM Parameter Store<br/>/stock-project/alphavantage-api-key<br/>SecureString")]
    S3RAW[("S3 stock-prediction-raw-…<br/>raw/ (API archive)<br/>models/ (LSTM + scaler)<br/>predictions/evaluation/")]
    DDBP[("DynamoDB stock-prices<br/>real rows: source=alphavantage<br/>+ 114 legacy synthetic rows")]
    DDBPR[("DynamoDB stock-predictions")]
    DDBS[("DynamoDB stock-signals<br/>alert_sent_&lt;TYPE&gt; dedup")]
    SNS(["SNS stock-prediction-alerts<br/>(email)"])
    CW["CloudWatch alarms<br/>stock-pipeline-failed-executions<br/>stock-pipeline-dlq-not-empty<br/>stock-pipeline-dlq-new-message"]
    CWD["CloudWatch dashboard<br/>stock-project"]

    SCH --> V
    SCH -. start failed .-> DLQ
    SSM -- key --> ING
    ING -- HTTPS --> AV
    ING -- raw JSON --> S3RAW
    ING -- Numbers, idempotent --> DDBP
    S3RAW -- model, scaler --> PRED
    DDBP -- 60 real closes --> PRED
    PRED --> DDBPR
    DDBP -- next real close --> SCORE
    SCORE -- actual, model + naive error --> DDBPR
    SCORE -- StockProject/ModelHealth --> CWD
    DG -- StockProject/Pipeline --> CWD
    DDBP -- real closes --> SIG
    SIG --> DDBS
    PUBD --> SNS
    PUBF --> SNS
    Pipeline -. execution metrics .-> CW
    DLQ -. queue metrics .-> CW
    CW --> SNS

    subgraph Web["Dashboard and API"]
        USER(["User browser"])
        CF["CloudFront + OAC<br/>(pending: account verification)"]
        S3WEB[("S3 stock-dashboard-…<br/>private, Block Public Access")]
        COG["Cognito user pool<br/>stock-dashboard-users<br/>hosted UI, code + PKCE"]
        APIGW["API Gateway HTTP API<br/>stock-dashboard-api<br/>JWT authorizer on every route"]
        API["Lambda stock-api<br/>(read-only; 5-ticker allow-list;<br/>model routes AAPL only)"]
    end

    USER -- HTTPS --> CF --> S3WEB
    USER -- sign in --> COG
    USER -- "Bearer ID token" --> APIGW --> API
    COG -. issuer/audience .-> APIGW
    API --> DDBP
    API --> DDBPR
    API --> DDBS
    API -- evaluation report --> S3RAW
```

`APIGW → API` goes through alias `stock-api:live` (version 3 since 2026-10-26). X-Ray active tracing is on for the 8 project Lambdas (not `stock-lstm-inference`); HTTP APIs and (for now) the state machine are not traced.

## Event-driven side paths (added 2026-10-22)

```mermaid
flowchart LR
    DDBP[("DynamoDB stock-prices")] -- "stream NEW_IMAGE<br/>filter INSERT, source=alphavantage" --> SH["Lambda stock-stream-handler"]
    SH -- PriceIngested --> BUS(["EventBridge bus stock-events"]) -- rule stock-events-log-all --> EL["Lambda stock-event-logger<br/>(CloudWatch Logs)"]
    S3R[("S3 raw/ archive")] -- ObjectCreated --> AVAL["Lambda stock-archive-validator<br/>no key/URL, schema checks"] --> MAN[("S3 manifests/")]
    MAN --> ATH["Athena stock-workgroup<br/>Glue stock_project.archive_manifests / daily_prices"]
```
Verified live: real INSERTs from the scheduled runs of 2026-10-22 and 10-23 produced 10 `PriceIngested` events in the logger log; every new archive got an `ok` manifest.

Legacy input `{"symbol":"AAPL"}` is still accepted (wrapped into a one-item list by `LegacyInput`), so older manual tests keep working.

## Failure handling

```mermaid
flowchart TD
    E0["Scheduler cannot start the execution"] --> Q["Retry ×2 within 1 h → SQS stock-pipeline-dlq"] --> QA["DLQ alarms → SNS"]
    E1["Bad run input ({}, not a list, 0 or >5 items)"] --> VI["ValidateInput → InvalidInput (Pass)"] --> PF["PublishFailure → SNS"] --> F["Fail state → execution FAILED"]
    E5["One ticker fails (not allow-listed, Lambda error, statusCode ≠ 200,<br/>Alpha Vantage throttle after 1 retry)"] --> TF["Per-ticker Catch → Ticker…Failed result"] --> CONT["Other tickers continue"] --> DG["Digest email lists the failed ticker<br/>(subject: N FAILED); execution SUCCEEDS;<br/>metric StockProject/Pipeline TickerFailures"]
    E2["Lambda error / timeout"] --> R["Retry (service errors ×2; IngestError/RateLimitError ×1 after 60 s;<br/>DailyLimitError never retried)"] --> TF
    E6["Map, digest or SNS error"] --> PF
    F --> M["ExecutionsFailed metric"]
    E4["Anything that escapes Catch<br/>(States.Runtime, execution timeout 1800 s, abort)"] --> M
    M --> A["Alarm stock-pipeline-failed-executions"] --> SNS["SNS email"]
```

## Design decisions
| Decision | Why |
|---|---|
| Real and synthetic rows share `stock-prices`; real rows carry `source=alphavantage`, `data_type=real`, and every reader filters on `source` | The user ruled out deleting anything. Real sort keys are the US close time in UTC (20:00Z/21:00Z), which never collide with the synthetic keys (00:00Z, 10:19Z, 10:24Z); writes are conditional so a non-Alpha-Vantage row can never be overwritten. |
| Prices stored as DynamoDB Numbers (Python `Decimal`) | The audit found `close` stored as String in 104 legacy rows. |
| Idempotent ingestion | Rows are keyed by (symbol, close time); unchanged rows are skipped; re-runs give `inserted 0, unchanged 100`. |
| One prediction per (symbol, as_of_date) | Re-running the pipeline on the same data overwrites rather than duplicates. |
| Alerts only on transitions, deduplicated per (symbol, trading day, alert type); ONE combined email per run | Prevents spam and never drops a second rule that fires for the same ticker and day; no daily "success" email. |
| Watchlist as a Map with MaxConcurrency 1 and a 15 s wait | Alpha Vantage free tier allows 25 calls/day and throttles bursts; 5 tickers = 5 calls per run. Sequential processing keeps calls spaced. |
| A failed ticker does not fail the run | Each ticker is isolated by its own Catch; the single digest email reports the failure, so there is one email instead of an email plus an alarm (decision D5 in `docs/RUN-REPORT.md`). |
| Predictions only for AAPL | The LSTM was trained on AAPL only and does not beat a naive baseline; other tickers get prices and signals only, and the API returns 404 "no validated model" for them. |
| Skip the AAPL prediction when new data contains a ≥ 25% day-over-day jump | Prices are unadjusted, so a stock split looks like a crash; feeding it to the model would produce a meaningless prediction. |
| Separate digest Lambda | Its role can only write its logs and `StockProject/Pipeline` metrics; it reads no data. |
| Scoring runs in parallel with signals and writes each score once | Neither branch can cancel the other (each catches its own errors); `attribute_not_exists(scored_at)` makes re-runs harmless. |
| Skip Predict and Signals only when `inserted == 0 and updated == 0` | Owner decision B (2026-10-22). Nothing new means the prediction and signals would be identical; score still runs for AAPL. Alpha Vantage often revises the last bar's volume, so `updated` is usually 1 after a trading day. |
| API served through a Lambda alias | The integration points at `stock-api:live`; a bad deploy is rolled back by moving the alias, without touching API Gateway. |
| No model-health verdict below 20 scored days | One or two days of errors say nothing about accuracy; the API and dashboard show "insufficient data" instead. |
| Schedule 18:30 New York time, Mon–Fri | 2.5 h after the 16:00 close, so Alpha Vantage has the day's bar; `America/New_York` handles DST. On US holidays the run is a harmless no-op (no new row, same prediction key, alert deduplicated). |
| HTTP API + Cognito JWT authorizer | Cheapest API Gateway type; no route is reachable without a valid Cognito token. |
| Private S3 + CloudFront OAC (no public website) | The user's requirement; the bucket keeps all four Block Public Access settings on. |
