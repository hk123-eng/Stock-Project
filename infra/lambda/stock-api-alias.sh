#!/usr/bin/env bash
# Final run item 2c: alias "live" for stock-api and repoint the HTTP API integration to it.
# Saves the integration first. Rollback: bash infra/lambda/stock-api-alias-rollback.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1
P="--profile stock-project --region ap-south-1"
cd "$(dirname "$0")/../.."
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=python
$PY infra/time_guard.py --strict
A=542601847637; API=sjdmkf8iag; INT=bp6k0pq; FN=arn:aws:lambda:ap-south-1:$A:function:stock-api
RB=infra/rollback/api-alias-$(date -u +%Y%m%dT%H%M%SZ); mkdir -p "$RB"
aws apigatewayv2 get-integration --api-id $API --integration-id $INT $P > "$RB/integration-before.json"
aws lambda get-policy --function-name stock-api $P > "$RB/stock-api-policy-before.json" 2>/dev/null || echo '{}' > "$RB/stock-api-policy-before.json"
V=$(aws lambda publish-version --function-name stock-api --description "live alias target $(date -u +%F) (GET /me code)" $P --query Version --output text)
echo "published stock-api:$V"
if aws lambda get-alias --function-name stock-api --name live $P >/dev/null 2>&1; then
  aws lambda update-alias --function-name stock-api --name live --function-version "$V" $P --query AliasArn --output text
else
  aws lambda create-alias --function-name stock-api --name live --function-version "$V" --description "Version served by stock-dashboard-api" $P --query AliasArn --output text
fi
aws lambda add-permission --function-name stock-api --qualifier live --statement-id apigw-stock-dashboard-api-live \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:ap-south-1:$A:$API/*/GET/*" --source-account $A $P --query Statement --output text
aws apigatewayv2 update-integration --api-id $API --integration-id $INT --integration-uri "$FN:live" $P --query IntegrationUri --output text
