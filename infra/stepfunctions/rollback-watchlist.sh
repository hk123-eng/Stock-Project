#!/usr/bin/env bash
# Restore the pre-watchlist state machine definition and schedule (saved by switch-to-watchlist.sh).
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
P="--profile stock-project --region ap-south-1"
SM=arn:aws:states:ap-south-1:542601847637:stateMachine:stock-prediction-pipeline
.venv/Scripts/python infra/time_guard.py
aws stepfunctions update-state-machine $P --state-machine-arn $SM \
  --definition file://infra/stepfunctions/stock-prediction-pipeline.pre-watchlist.asl.json --query updateDate --output text
cat > build/schedule-target.json <<JSON
{"Arn":"$SM","RoleArn":"arn:aws:iam::542601847637:role/stock-scheduler-role","Input":"{\"symbol\":\"AAPL\"}",
 "RetryPolicy":{"MaximumEventAgeInSeconds":3600,"MaximumRetryAttempts":2},
 "DeadLetterConfig":{"Arn":"arn:aws:sqs:ap-south-1:542601847637:stock-pipeline-dlq"}}
JSON
DESC="Mon-Fri 18:30 America/New_York (2.5 h after the 16:00 US close): run stock-prediction-pipeline for AAPL; failed starts go to SQS stock-pipeline-dlq"
aws scheduler update-schedule $P --name stock-daily-pipeline --schedule-expression "cron(30 18 ? * MON-FRI *)" \
  --schedule-expression-timezone America/New_York --flexible-time-window Mode=OFF --state ENABLED \
  --action-after-completion NONE --description "$DESC" \
  --target file://build/schedule-target.json --query ScheduleArn --output text
echo "rolled back (DLQ kept on the schedule)"
