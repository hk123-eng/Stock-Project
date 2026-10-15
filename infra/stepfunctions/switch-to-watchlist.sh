#!/usr/bin/env bash
# Phase 8 item 3/5c switch-over: watchlist state machine + schedule input {"symbols":[...]} + scheduler DLQ.
# Saves the live definition and schedule first (rollback: rollback-watchlist.sh). Refuses to run in protected windows.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python
P="--profile stock-project --region ap-south-1"
SM=arn:aws:states:ap-south-1:542601847637:stateMachine:stock-prediction-pipeline
$PY infra/time_guard.py

# 1. snapshot what is live now
aws stepfunctions describe-state-machine $P --state-machine-arn $SM --query definition --output text > infra/stepfunctions/stock-prediction-pipeline.pre-watchlist.asl.json
aws scheduler get-schedule $P --name stock-daily-pipeline --output json > infra/scheduler/stock-daily-pipeline.pre-watchlist.json
echo "saved rollback snapshots"

# 2. state machine
$PY infra/stepfunctions/build_definition.py --watchlist
aws stepfunctions validate-state-machine-definition $P --definition file://infra/stepfunctions/stock-prediction-pipeline.watchlist.asl.json --query result --output text
aws stepfunctions update-state-machine $P --state-machine-arn $SM \
  --definition file://infra/stepfunctions/stock-prediction-pipeline.watchlist.asl.json --query updateDate --output text

# 3. schedule: same cron/timezone/role, new input, DLQ, unchanged retry policy
cat > build/schedule-target.json <<JSON
{"Arn":"$SM","RoleArn":"arn:aws:iam::542601847637:role/stock-scheduler-role",
 "Input":"{\"symbols\":[\"AAPL\",\"MSFT\",\"GOOGL\",\"AMZN\",\"NVDA\"]}",
 "RetryPolicy":{"MaximumEventAgeInSeconds":3600,"MaximumRetryAttempts":2},
 "DeadLetterConfig":{"Arn":"arn:aws:sqs:ap-south-1:542601847637:stock-pipeline-dlq"}}
JSON
DESC="Mon-Fri 18:30 America/New_York (2.5 h after the 16:00 US close): run stock-prediction-pipeline for the watchlist AAPL MSFT GOOGL AMZN NVDA; failed starts go to SQS stock-pipeline-dlq"
aws scheduler update-schedule $P --name stock-daily-pipeline --schedule-expression "cron(30 18 ? * MON-FRI *)" \
  --schedule-expression-timezone America/New_York --flexible-time-window Mode=OFF --state ENABLED \
  --action-after-completion NONE --description "$DESC" \
  --target file://build/schedule-target.json --query ScheduleArn --output text
aws scheduler get-schedule $P --name stock-daily-pipeline --output json > infra/scheduler/stock-daily-pipeline.json
echo "switched"
