# Architecture — Cloud Stock Price Monitoring and Prediction

Region `ap-south-1` (Mumbai), account `542601847637`. Everything is serverless and pay-per-use.
Verified live on 2026-10-05 unless marked **pending**.

## End-to-end flow

```mermaid
flowchart LR
    subgraph Schedule
        SCH["EventBridge Scheduler<br/>stock-daily-pipeline<br/>Mon–Fri 18:30 America/New_York<br/>input {&quot;symbol&quot;:&quot;AAPL&quot;}"]
    end

    subgraph Pipeline["Step Functions: stock-prediction-pipeline"]
        V{"ValidateInput<br/>symbol present,<br/>string, allow-listed"}
        ING["IngestPrices<br/>Lambda stock-ingest"]
        PRED["Predict<br/>Lambda stock-lstm-inference<br/>(TFLite LSTM)"]
        SIG["ComputeSignals<br/>Lambda stock-signals"]
        AL{"Alert needed?<br/>(deduplicated)"}
        PUBA["PublishAlert"]
        PUBF["PublishFailure"]
        SCORE["ScorePredictions<br/>Lambda stock-evaluate"]
        V -- valid --> ING --> PRED --> SIG --> AL
        AL -- yes --> PUBA --> SCORE
        AL -- no --> SCORE
        SCORE -. error .-> PUBF
        V -- invalid --> PUBF
        ING -. error .-> PUBF
        PRED -. error .-> PUBF
        SIG -. error .-> PUBF
    end

    AV[("Alpha Vantage<br/>TIME_SERIES_DAILY<br/>compact, unadjusted")]
    SSM[("SSM Parameter Store<br/>/stock-project/alphavantage-api-key<br/>SecureString")]
    S3RAW[("S3 stock-prediction-raw-…<br/>raw/ (API archive)<br/>models/ (LSTM + scaler)<br/>predictions/evaluation/")]
    DDBP[("DynamoDB stock-prices<br/>real rows: source=alphavantage<br/>+ 114 legacy synthetic rows")]
    DDBPR[("DynamoDB stock-predictions")]
    DDBS[("DynamoDB stock-signals")]
    SNS(["SNS stock-prediction-alerts<br/>(email)"])
    CW["CloudWatch alarm<br/>stock-pipeline-failed-executions<br/>(Failed + TimedOut + Aborted)"]

    SCH --> V
    SSM -- key --> ING
    ING -- HTTPS --> AV
    ING -- raw JSON --> S3RAW
    ING -- Numbers, idempotent --> DDBP
    S3RAW -- model, scaler --> PRED
    DDBP -- 60 real closes --> PRED
    PRED --> DDBPR
    DDBP -- next real close --> SCORE
    SCORE -- actual, model + naive error --> DDBPR
    SCORE -- custom metrics --> CWM[("CloudWatch metrics<br/>StockProject/ModelHealth")]
    DDBP -- real closes --> SIG
    SIG --> DDBS
    PUBA --> SNS
    PUBF --> SNS
    Pipeline -. execution metrics .-> CW --> SNS

    subgraph Web["Dashboard and API"]
        USER(["User browser"])
        CF["CloudFront + OAC<br/>(pending: account verification)"]
        S3WEB[("S3 stock-dashboard-…<br/>private, Block Public Access")]
        COG["Cognito user pool<br/>stock-dashboard-users<br/>hosted UI, code + PKCE"]
        APIGW["API Gateway HTTP API<br/>stock-dashboard-api<br/>JWT authorizer on every route"]
        API["Lambda stock-api<br/>(read-only)"]
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

## Failure handling

```mermaid
flowchart TD
    E1["Bad input ({}, wrong type, unsupported symbol)"] --> VI["ValidateInput → InvalidInput (Pass)"] --> PF["PublishFailure → SNS"] --> F["Fail state"]
    E2["Lambda error / timeout"] --> R["Retry (service errors ×2; IngestError ×1 after 60 s)"] --> C["Catch States.ALL → $.error"] --> PF
    E3["Lambda returns statusCode ≠ 200"] --> CH["Check* Choice (IsPresent → IsNumeric → = 200)"] --> PF
    F --> M["ExecutionsFailed metric"]
    E4["Anything that escapes Catch<br/>(States.Runtime, execution timeout 900 s, abort)"] --> M
    M --> A["Alarm stock-pipeline-failed-executions"] --> SNS["SNS email"]
```

## Design decisions
| Decision | Why |
|---|---|
| Real and synthetic rows share `stock-prices`; real rows carry `source=alphavantage`, `data_type=real`, and every reader filters on `source` | The user ruled out deleting anything. Real sort keys are the US close time in UTC (20:00Z/21:00Z), which never collide with the synthetic keys (00:00Z, 10:19Z, 10:24Z); writes are conditional so a non-Alpha-Vantage row can never be overwritten. |
| Prices stored as DynamoDB Numbers (Python `Decimal`) | The audit found `close` stored as String in 104 legacy rows. |
| Idempotent ingestion | Rows are keyed by (symbol, close time); unchanged rows are skipped; re-runs give `inserted 0, unchanged 100`. |
| One prediction per (symbol, as_of_date) | Re-running the pipeline on the same data overwrites rather than duplicates. |
| Alert at most once per trading day, only on transitions | Prevents email spam; no daily "success" email. |
| Scoring runs last in the pipeline and writes each score once | A scoring failure can't block the prediction or the alert; `attribute_not_exists(scored_at)` makes re-runs harmless. |
| No model-health verdict below 20 scored days | One or two days of errors say nothing about accuracy; the API and dashboard show "insufficient data" instead. |
| Schedule 18:30 New York time, Mon–Fri | 2.5 h after the 16:00 close, so Alpha Vantage has the day's bar; `America/New_York` handles DST. On US holidays the run is a harmless no-op (no new row, same prediction key, alert deduplicated). |
| HTTP API + Cognito JWT authorizer | Cheapest API Gateway type; no route is reachable without a valid Cognito token. |
| Private S3 + CloudFront OAC (no public website) | The user's requirement; the bucket keeps all four Block Public Access settings on. |
