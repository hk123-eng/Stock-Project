# AWS resource inventory

Account `542601847637`, region `ap-south-1` (CloudFront and IAM are global). Verified with the AWS CLI (`--profile stock-project`) on 2026-10-05.
**Status key:** *existing* = there before 2026-10-05; *created* = created 2026-10-05; *modified* = existing resource changed 2026-10-05.

## Compute
| Resource | Status | Details |
|---|---|---|
| Lambda `stock-ingest` | created | python3.12 arm64, 256 MB, 60 s. Alpha Vantage → S3 raw + DynamoDB. Role `stock-ingest-role`. |
| Lambda `stock-lstm-inference` | modified (code) | python3.10 x86_64, 512 MB, 30 s, layer `tflite-runtime-py310:2`. Real rows only, persists predictions, `evaluate` mode. **Version 1 = original code (rollback).** |
| Lambda `stock-signals` | created | python3.12 arm64, 256 MB, 30 s. Env `PRED_MOVE_PCT=2`. Role `stock-signals-role`. |
| Lambda `stock-evaluate` | created 2026-10-06 | python3.12 arm64, 128 MB, 60 s. Scores predictions vs next real close (model + naive), publishes `StockProject/ModelHealth` metrics. Role `stock-evaluate-role`. |
| Lambda `stock-api` | created | python3.12 arm64, 256 MB, 15 s. Read-only. Role `stock-api-role`. Resource policy: API Gateway `sjdmkf8iag` GET routes only. |
| Lambda `stock-db-seeder` | existing (unused) | Synthetic data generator. Deletion pending approval. |
| Lambda layer `tflite-runtime-py310` v1, v2 | existing | v2 in use; v1 unused (deletion pending approval). |

## Orchestration and scheduling
| Resource | Status | Details |
|---|---|---|
| Step Functions `stock-prediction-pipeline` (Standard) | modified (definition; again 2026-10-06) | ValidateInput → IngestPrices → Predict → ComputeSignals → alert SNS → ScorePredictions; failures → SNS. Pre-Phase-8 definition in `infra/stepfunctions/stock-prediction-pipeline.pre-phase8.asl.json`. 900 s timeout. Logging **OFF** (missing permission). Previous definition saved in `infra/stepfunctions/stock-prediction-pipeline.original.asl.json`. |
| EventBridge Scheduler `stock-daily-pipeline` | created | `cron(30 18 ? * MON-FRI *)` America/New_York, input `{"symbol":"AAPL"}`, 2 retries. |
| EventBridge Scheduler `stock-test-once-20261005` | created (test) | One-time `at()` schedule; fired once (execution SUCCEEDED); inert. Delete when convenient (needs approval + permission). |

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
| Cognito user pool `stock-dashboard-users` (`ap-south-1_OsBj5ZbkR`) | created | Lite tier, admin-only sign-up, email username, 12-character complex passwords, deletion protection ON, MFA OFF. **0 users** (the user creates their own). |
| Cognito domain `stock-dashboard-542601847637` | created | Classic hosted UI. |
| Cognito app client `stock-dashboard-spa` (`7us8ffcbqlv94uoscmh57e5chu`) | created | Public (no secret), code flow with PKCE, scopes `openid email`, callback `http://localhost:8080/`. |
| CloudFront OAC `stock-dashboard-oac` (`E1BHMZIJ62GXYK`) | created | sigv4, always sign, S3. |
| CloudFront distribution | **pending** | Blocked: the account must be verified by AWS Support. Then run `infra/cloudfront/finish-cloudfront.sh`. |

## Messaging and monitoring
| Resource | Status | Details |
|---|---|---|
| SNS `stock-prediction-alerts` | existing | 1 confirmed email subscription. Receives failure alerts, signal alerts, alarm notifications. |
| CloudWatch alarm `stock-pipeline-failed-executions` | created | Metric math: ExecutionsFailed + ExecutionsTimedOut + ExecutionsAborted ≥ 1 in 5 min → SNS. Missing data = not breaching. |
| Log groups `/aws/lambda/stock-*` | modified | 30-day retention on all six (`stock-ingest`, `stock-lstm-inference`, `stock-signals`, `stock-api`, `stock-evaluate`, `stock-db-seeder`). |
| Custom metrics `StockProject/ModelHealth` | created 2026-10-06 | `ModelAbsError`, `NaiveAbsError` (dimension `Symbol`), one sample per newly scored day. |

## IAM roles (no role is tagged: `iam:TagRole` is not granted)
| Role | Status | Boundary | Permissions |
|---|---|---|---|
| `stock-ingest-role` | created | StockRoleBoundary | own log group; `ssm:GetParameter` on the key; `dynamodb:Query`,`PutItem` on `stock-prices`; `s3:PutObject` on `raw/*` |
| `stock-signals-role` | created | StockRoleBoundary | own log group; `dynamodb:Query` on `stock-prices`; `dynamodb:UpdateItem` on `stock-signals` |
| `stock-evaluate-role` | created 2026-10-06 | StockRoleBoundary | own log group; `dynamodb:Query` on prices/predictions; `dynamodb:UpdateItem` on `stock-predictions`; `cloudwatch:PutMetricData` only for namespace `StockProject/ModelHealth` |
| `stock-api-role` | created | StockRoleBoundary | own log group; `dynamodb:Query` on prices/predictions/signals; `s3:GetObject` on `predictions/evaluation/*` |
| `stock-scheduler-role` | created | StockRoleBoundary | `states:StartExecution` on `stock-prediction-pipeline` only; trust `scheduler.amazonaws.com` + `aws:SourceAccount` |
| `stock-lstm-inference-role` | existing (user-managed) | none | S3 `models/*` read; DynamoDB GetItem/Query on `stock-prices`; PutItem on `stock-*` |
| `stock-prediction-sfn-role` | existing (user-managed) | none | Lambda invoke `stock-*`; SNS publish; DynamoDB `stock-*` (unused); log-delivery actions |
| `stock-db-seeder-role` | existing (unused) | none | PutItem on `stock-prices` |

## Not used (confirmed absent)
EC2, NAT gateway, RDS, EKS, ECR, Secrets Manager, Athena (only the default workgroup exists).
