#!/usr/bin/env bash
# Rollback for stock-api-alias.sh: point the integration back at the unqualified function ($LATEST).
# The alias, the published version and the alias permission stay (deleting them needs owner approval).
set -euo pipefail
export MSYS_NO_PATHCONV=1
P="--profile stock-project --region ap-south-1"
aws apigatewayv2 update-integration --api-id sjdmkf8iag --integration-id bp6k0pq \
  --integration-uri arn:aws:lambda:ap-south-1:542601847637:function:stock-api $P --query IntegrationUri --output text
# To roll back the CODE instead: aws lambda update-alias --function-name stock-api --name live --function-version 2
