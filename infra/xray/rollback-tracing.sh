#!/usr/bin/env bash
# Rollback for enable-tracing.sh: tracing back to PassThrough. The inline policy stock-xray-write is left in place
# (removing it is a deletion -> owner approval: aws iam delete-role-policy --role-name <role> --policy-name stock-xray-write).
set -euo pipefail
export MSYS_NO_PATHCONV=1
P="--profile stock-project --region ap-south-1"
for f in stock-ingest stock-signals stock-evaluate stock-alert-digest stock-api stock-event-logger stock-stream-handler stock-archive-validator; do
  aws lambda update-function-configuration --function-name "$f" --tracing-config Mode=PassThrough $P --query '[FunctionName,TracingConfig.Mode]' --output text
  aws lambda wait function-updated-v2 --function-name "$f" $P
done
