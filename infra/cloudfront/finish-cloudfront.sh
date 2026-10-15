#!/usr/bin/env bash
# Run ONLY after AWS Support has verified the account for CloudFront
# (CreateDistribution currently fails with "Your account must be verified").
# Creates the distribution (private S3 origin via OAC E1BHMZIJ62GXYK), grants
# CloudFront-only read on the bucket, and registers the new HTTPS origin with
# Cognito and the API's CORS list. Nothing here makes the bucket public.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
P="--profile stock-project --region ap-south-1"
BK=stock-dashboard-542601847637-ap-south-1
POOL=ap-south-1_OsBj5ZbkR
CID=$(cat infra/cognito/client-id.txt)
API=$(cat infra/apigateway/api-id.txt)

# 1. Distribution (fresh CallerReference each run)
python - <<'EOF'
import json, time
p = "infra/cloudfront/distribution.json"
d = json.load(open(p)); d["DistributionConfig"]["CallerReference"] = f"stock-dashboard-{int(time.time())}"
json.dump(d, open(p, "w"), indent=2)
EOF
read -r DIST_ID DIST_ARN DOMAIN < <(aws cloudfront create-distribution-with-tags \
  --distribution-config-with-tags file://infra/cloudfront/distribution.json --profile stock-project \
  --query "Distribution.[Id,ARN,DomainName]" --output text)
echo "$DIST_ID $DIST_ARN $DOMAIN" | tee infra/cloudfront/distribution.txt

# 2. Bucket policy: only this distribution (via OAC) may read objects
cat > infra/cloudfront/bucket-policy.json <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"AllowCloudFrontOACReadOnly","Effect":"Allow",
 "Principal":{"Service":"cloudfront.amazonaws.com"},"Action":"s3:GetObject",
 "Resource":"arn:aws:s3:::$BK/*","Condition":{"StringEquals":{"AWS:SourceArn":"$DIST_ARN"}}}]}
JSON
aws s3api put-bucket-policy --bucket $BK --policy file://infra/cloudfront/bucket-policy.json $P

# 3. Cognito callback/logout URLs (keep localhost for development)
aws cognito-idp update-user-pool-client --user-pool-id $POOL --client-id $CID --client-name stock-dashboard-spa \
  --explicit-auth-flows ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH --supported-identity-providers COGNITO \
  --callback-urls "https://$DOMAIN/" http://localhost:8080/ --logout-urls "https://$DOMAIN/" http://localhost:8080/ \
  --allowed-o-auth-flows code --allowed-o-auth-scopes openid email --allowed-o-auth-flows-user-pool-client \
  --prevent-user-existence-errors ENABLED --enable-token-revocation \
  --access-token-validity 60 --id-token-validity 60 --refresh-token-validity 1 \
  --token-validity-units AccessToken=minutes,IdToken=minutes,RefreshToken=days $P >/dev/null

# 4. API CORS
aws apigatewayv2 update-api --api-id $API $P \
  --cors-configuration "AllowOrigins=https://$DOMAIN,http://localhost:8080,AllowMethods=GET,OPTIONS,AllowHeaders=authorization,content-type,MaxAge=3600" >/dev/null

aws cloudfront wait distribution-deployed --id $DIST_ID --profile stock-project
echo "Dashboard: https://$DOMAIN/"
echo "Direct S3 (must be 403): $(curl -s -o /dev/null -w '%{http_code}' https://$BK.s3.ap-south-1.amazonaws.com/index.html)"
echo "Via CloudFront (must be 200): $(curl -s -o /dev/null -w '%{http_code}' https://$DOMAIN/)"
