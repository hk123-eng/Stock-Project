# Phase 9 notes (plans only; nothing here is deployed)

_Written 2026-10-15. The Phase 9 items that were checked against the current permissions are recorded in
`docs/RUN-REPORT.md` (Item 7), with the exact IAM JSON that would unblock them._

## Built-in or already present
- **API Gateway throttling:** the HTTP API `$default` stage limits every route to 10 requests/s with a burst of 20 (since Phase 5).

## Parked because a permission is missing (JSON in the run report)
- **Athena over S3:** a Glue database `stock_project` with one manually defined external table over
  `raw/alphavantage/<SYMBOL>/<date>/*.json` (no crawler), queried with Athena's `primary` workgroup and results written to a
  private prefix `athena-results/` in the existing raw bucket. Cost: $5 per TB scanned, and this data set is a few MB, so well under $0.01/month.
- **EventBridge custom bus:** bus `stock-pipeline` receiving one `PipelineRunCompleted` event per run (digest counts),
  plus a rule to a CloudWatch Logs group `/aws/events/stock-pipeline`. Custom events cost $1 per million.
- **X-Ray:** active tracing on the Lambdas and the state machine. It needs `xray:PutTraceSegments` and
  `xray:PutTelemetryRecords` in `StockRoleBoundary` and on each role. The pipeline role `stock-prediction-sfn-role` must not
  be edited by the deploy user. HTTP APIs do not support X-Ray; only REST APIs do.

## Skipped by instruction (short plan only)
- **CloudTrail:** the account's free 90-day management-event history (CloudTrail Event history) already records every
  API call. A trail that delivers to S3 is needed only for retention beyond 90 days. One trail of management events
  is free; S3 storage costs apply. It needs `cloudtrail:CreateTrail` and a bucket policy, so the owner decides.
- **Cognito groups:** an `admins` group could gate future write routes (none exist; the API is read-only), with the
  JWT `cognito:groups` claim checked in `stock-api`. No value until a write route exists.
- **SAM/CloudFormation:** today the infrastructure is reproducible from scripts and JSON under `infra/`. Importing
  the live resources into a CloudFormation stack (resource import) would make drift visible, but a mistaken template
  can *replace* resources, so it needs a supervised session and the owner's approval.
- **Bedrock:** an LLM could write a plain-language daily summary of the signals. That adds cost per call and the
  risk of confident but wrong text in alerts. If it is done, the output must be labelled as generated and must never state a
  forecast.
