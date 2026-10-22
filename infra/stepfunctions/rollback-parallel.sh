#!/usr/bin/env bash
# Restore the definition saved by switch-to-parallel.sh (the watchlist definition live since 2026-10-15).
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
P="--profile stock-project --region ap-south-1"
SM=arn:aws:states:ap-south-1:542601847637:stateMachine:stock-prediction-pipeline
.venv/Scripts/python infra/time_guard.py --strict
aws stepfunctions update-state-machine $P --state-machine-arn $SM \
  --definition file://infra/stepfunctions/stock-prediction-pipeline.pre-parallel.asl.json --query updateDate --output text
echo "rolled back to the pre-parallel definition"
