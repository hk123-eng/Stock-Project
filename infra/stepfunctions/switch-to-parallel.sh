#!/usr/bin/env bash
# Final run item 3: deploy the parallel/skip definition. The schedule is NOT changed.
# Snapshots the live definition first (rollback: rollback-parallel.sh). Refuses to run in protected windows.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python
P="--profile stock-project --region ap-south-1"
SM=arn:aws:states:ap-south-1:542601847637:stateMachine:stock-prediction-pipeline
$PY infra/time_guard.py --strict
aws stepfunctions describe-state-machine $P --state-machine-arn $SM --query definition --output text > infra/stepfunctions/stock-prediction-pipeline.pre-parallel.asl.json
echo "saved rollback snapshot"
$PY infra/stepfunctions/build_definition.py --parallel
aws stepfunctions validate-state-machine-definition $P --definition file://infra/stepfunctions/stock-prediction-pipeline.parallel.asl.json --query result --output text
aws stepfunctions update-state-machine $P --state-machine-arn $SM \
  --definition file://infra/stepfunctions/stock-prediction-pipeline.parallel.asl.json --query updateDate --output text
echo "switched to parallel definition"
