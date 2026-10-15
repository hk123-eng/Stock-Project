# AWS resource inventory

Account `542601847637`, region `ap-south-1` (CloudFront and IAM are global). Verified with the AWS CLI (`--profile stock-project`) on 2026-10-05; Phase 8 rows re-verified 2026-10-15.
**Status key:** *existing* = there before 2026-10-05; *created* = created 2026-10-05; *modified* = existing resource changed 2026-10-05. Later changes are dated.

## Compute
| Resource | Status | Details |
|---|---|---|
| Lambda `stock-ingest` | created; code updated 2026-10-15 | python3.12 arm64, 256 MB, 60 s. Alpha Vantage → S3 raw + DynamoDB. Daily-quota vs burst throttle errors; suspicious-jump (split) check in `data_quality`. Role `stock-ingest-role`. **Version 1 = code before 2026-10-15 (rollback).** |
| Lambda `stock-lstm-inference` | modified (code) | python3.10 x86_64, 512 MB, 30 s, layer `tflite-runtime-py310:2`. Real rows only, persists predictions, `evaluate` mode. **Version 1 = original code (rollback).** |
| Lambda `stock-signals` | created; code updated 2026-10-15 | python3.12 arm64, 256 MB, 30 s. Env `PRED_MOVE_PCT=2`. SMA/RSI/volatility + MACD(12,26,9) + Bollinger(20, 2σ); per-(symbol, day, type) alert dedup. Role `stock-signals-role`. **Version 1 = code before 2026-10-15 (rollback).** |
| Lambda `stock-evaluate` | created 2026-10-06 | python3.12 arm64, 128 MB, 60 s. Scores predictions vs next real close (model + naive), publishes `StockProject/ModelHealth` metrics. Role `stock-evaluate-role`. |
| Lambda `stock-api` | created; code updated 2026-10-15 | python3.12 arm64, 256 MB, 15 s. Read-only. Allow-list AAPL MSFT GOOGL AMZN NVDA; model routes 404 "no validated model" except AAPL. Role `stock-api-role`. Resource policy: API Gateway `sjdmkf8iag` GET routes only. **Version 1 = code before 2026-10-15 (rollback).** |
| Lambda `stock-alert-digest` | created 2026-10-15 | python3.12 arm64, 128 MB, 30 s, env `MODEL_SYMBOLS=AAPL`. Builds the one combined email per run; publishes `StockProject/Pipeline` metrics. Role `stock-alert-digest-role`. |
| Lambda `stock-db-seeder` | existing (unused) | Synthetic data generator. Deletion pending approval. |
| Lambda layer `tflite-runtime-py310` v1, v2 | existing | v2 in use; v1 unused (deletion pending approval). |

## Orchestration and scheduling
| Resource | Status | Details |
|---|---|---|
| Step Functions `stock-prediction-pipeline` (Standard) | modified (definition; again 2026-10-06) | ValidateInput → IngestPrices → Predict → ComputeSignals → alert SNS → ScorePredictions; failures → SNS. Pre-Phase-8 definition in `infra/stepfunctions/stock-prediction-pipeline.pre-phase8.asl.json`. 900 s timeout. Logging **OFF** (missing permission). Previous definition saved in `infra/stepfunctions/stock-prediction-pipeline.original.asl.json`. |
| EventBridge Scheduler `stock-daily-pipeline` | created | `cron(30 18 ? * MON-FRI *)` America/New_York, input `{"symbol":"AAPL"}`, 2 retries. |
| EventBridge Scheduler `stock-test-once-20261005` | created (test) | One-time `at()` schedule; fired once (execution SUCCEEDED); inert. Delete when convenient (needs approval + permission). |
| EventBridge Scheduler `stock-test-dlq-20261015` | created 2026-10-15 (test) | One-time `at(2026-10-15T13:55:00)` UTC, target a non-existent state machine, 0 retries, DLQ `stock-pipeline-dlq`; fired once; inert. Delete when convenient. |

## Storage
| Resource | Status | Details |
|---|---|---|
| DynamoDB `stock-prices` | existing, data added | `symbol`/`timestamp`. 114 synthetic rows (unchanged) + 100 real rows (`source=alphavantage`, Numbers). |
| DynamoDB `stock-predictions` | created | `symbol`/`as_of_date`, on-demand. |
| DynamoDB `stock-signals` | created | `symbol`/`trade_date`, on-demand. Indicators, alerts, `alert_sent_at` (dedup). |
| S3 `stock-prediction-raw-542601847637-ap-south-1-an` | existing, objects added | Private, SSE-S3. New prefixes `raw/alphavantage/…`, `predictions/evaluation/AAPL-latest.json`. `models/` untouched. |
| S3 `stock-dashboard-542601847637-ap-south-1` | created | Private: Block Public Access ×4, BucketOwnerEnforced, SSE-S3. Holds the dashboard files. No bucket policy yet (added with CloudFront). Anonymous GET verified 403. |
| SSM `/stock-project/alphavantage-api-key` | existing (user-created) | SecureString, `alias/aws/ssm`. Readable only by `stock-ingest-role`. |

## Web, API and auth
| Resource | Status | Details |
|---|---|---|
| API Gateway HTTP API `stock-dashboard-api` (`sjdmkf8iag`) | created | `https://sjdmkf8iag.execute-api.ap-south-1.amazonaws.com`, `$default` stage, auto-deploy, throttle 10 rps / burst 20. 9 GET routes (incl. `/model-health`, added 2026-10-06), all with JWT authorizer `cognito-jwt`. CORS: `http://localhost:8080`. |
| Cognito user pool `stock-dashboard-users` (`ap-south-1_OsBj5ZbkR`) | created | Lite tier, admin-only sign-up, email username, 12-character complex passwords, deletion protection ON, MFA OFF. 2 users on 2026-10-15 (created by the owner, not by the deploy user). |
| Cognito domain `stock-dashboard-542601847637` | created | Classic hosted UI. |
| Cognito app client `stock-dashboard-spa` (`7us8ffcbqlv94uoscmh57e5chu`) | created | Public (no secret), code flow with PKCE, scopes `openid email`, callback `http://localhost:8080/`. |
| CloudFront OAC `stock-dashboard-oac` (`E1BHMZIJ62GXYK`) | created | sigv4, always sign, S3. |
| CloudFront distribution | **pending** | Blocked: the account must be verified by AWS Support. Then run `infra/cloudfront/finish-cloudfront.sh`. |

## Messaging and monitoring
| Resource | Status | Details |
|---|---|---|
| SNS `stock-prediction-alerts` | existing | 1 confirmed email subscription. Receives failure alerts, signal alerts, alarm notifications. |
| SQS `stock-pipeline-dlq` | created 2026-10-15 | Scheduler dead-letter queue. SSE-SQS, 14-day retention, queue policy: SendMessage only from `stock-scheduler-role`, deny non-TLS. Holds 1 test message from 2026-10-15 (expires ~2026-10-29). |
| CloudWatch alarm `stock-pipeline-dlq-not-empty` | created 2026-10-15 | ApproximateNumberOfMessagesVisible ≥ 1 (5 min, max) → SNS. In ALARM until the test message expires or is purged. |
| CloudWatch alarm `stock-pipeline-dlq-new-message` | created 2026-10-15 | NumberOfMessagesSent ≥ 1 in 5 min → SNS; returns to OK on its own. |
| CloudWatch dashboard `stock-project` | created 2026-10-15 | 36 metrics: executions, tickers processed/failed, DLQ depth, Lambda errors/duration/throttles, API count/4xx/5xx/latency, DynamoDB throttles, AAPL model vs naive error. `infra/cloudwatch/dashboard-stock-project.json`. |
| CloudWatch alarm `stock-pipeline-failed-executions` | created | Metric math: ExecutionsFailed + ExecutionsTimedOut + ExecutionsAborted ≥ 1 in 5 min → SNS. Missing data = not breaching. |
| Log groups `/aws/lambda/stock-*` | modified | 30-day retention on all seven (`stock-ingest`, `stock-lstm-inference`, `stock-signals`, `stock-api`, `stock-evaluate`, `stock-alert-digest`, `stock-db-seeder`). |
| Custom metrics `StockProject/ModelHealth` | created 2026-10-06 | `ModelAbsError`, `NaiveAbsError` (dimension `Symbol`), one sample per newly scored day. |
| Custom metrics `StockProject/Pipeline` | created 2026-10-15 | `TickersProcessed`, `TickerFailures`, one sample per run (first sample `TickerFailures=1` was a direct test invocation). |

## IAM roles (no role is tagged: `iam:TagRole` is not granted)
| Role | Status | Boundary | Permissions |
|---|---|---|---|
| `stock-ingest-role` | created | StockRoleBoundary | own log group; `ssm:GetParameter` on the key; `dynamodb:Query`,`PutItem` on `stock-prices`; `s3:PutObject` on `raw/*` |
| `stock-signals-role` | created | StockRoleBoundary | own log group; `dynamodb:Query` on `stock-prices`; `dynamodb:UpdateItem` on `stock-signals` |
| `stock-evaluate-role` | created 2026-10-06 | StockRoleBoundary | own log group; `dynamodb:Query` on prices/predictions; `dynamodb:UpdateItem` on `stock-predictions`; `cloudwatch:PutMetricData` only for namespace `StockProject/ModelHealth` |
| `stock-api-role` | created | StockRoleBoundary | own log group; `dynamodb:Query` on prices/predictions/signals; `s3:GetObject` on `predictions/evaluation/*` |
| `stock-scheduler-role` | created; policy extended 2026-10-15 | StockRoleBoundary | `states:StartExecution` on `stock-prediction-pipeline` only; `sqs:SendMessage` on `stock-pipeline-dlq` only; trust `scheduler.amazonaws.com` + `aws:SourceAccount` |
| `stock-alert-digest-role` | created 2026-10-15 | StockRoleBoundary | own log group; `cloudwatch:PutMetricData` only for namespace `StockProject/Pipeline`; no data access |
| `stock-lstm-inference-role` | existing (user-managed) | none | S3 `models/*` read; DynamoDB GetItem/Query on `stock-prices`; PutItem on `stock-*` |
| `stock-prediction-sfn-role` | existing (user-managed) | none | Lambda invoke `stock-*`; SNS publish; DynamoDB `stock-*` (unused); log-delivery actions |
| `stock-db-seeder-role` | existing (unused) | none | PutItem on `stock-prices` |

## Not used (confirmed absent)
EC2, NAT gateway, RDS, EKS, ECR, Secrets Manager, Athena (only the default workgroup exists), Glue, custom EventBridge buses, X-Ray tracing, CloudFront distributions (blocked).
