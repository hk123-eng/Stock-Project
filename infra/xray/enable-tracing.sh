#!/usr/bin/env bash
# Final run item 2a: X-Ray active tracing on the project Lambdas (NOT stock-lstm-inference, NOT stock-db-seeder).
# Adds a separate inline policy stock-xray-write to each function role (existing policies untouched; allowed by
# StockRoleBoundary v3), then sets TracingConfig Mode=Active. Saves every configuration first.
# Rollback: bash infra/xray/rollback-tracing.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1
P="--profile stock-project --region ap-south-1"
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=python
$PY infra/time_guard.py --strict
FUNCS="stock-ingest stock-signals stock-evaluate stock-alert-digest stock-api stock-event-logger stock-stream-handler stock-archive-validator"
RB=infra/rollback/xray-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$RB"
for f in $FUNCS; do
  aws lambda get-function-configuration --function-name "$f" $P > "$RB/$f-config.json"
done
for f in $FUNCS; do
  role=$(aws lambda get-function-configuration --function-name "$f" $P --query Role --output text); role=${role##*/}
  case "$role" in stock-lstm-inference-role|stock-prediction-sfn-role) echo "refusing protected role $role"; exit 1;; esac
  aws iam put-role-policy --role-name "$role" --policy-name stock-xray-write --policy-document file://infra/xray/stock-xray-write-policy.json $P
  echo "policy on $role"
done
sleep 10  # IAM propagation
for f in $FUNCS; do
  aws lambda update-function-configuration --function-name "$f" --tracing-config Mode=Active $P --query '[FunctionName,TracingConfig.Mode]' --output text
  aws lambda wait function-updated-v2 --function-name "$f" $P
done
echo "saved pre-change configs in $RB"
