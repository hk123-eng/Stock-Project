#!/usr/bin/env bash
# Upload dashboard/ to the PRIVATE dashboard bucket (no ACLs; Block Public Access stays on).
set -euo pipefail
export MSYS_NO_PATHCONV=1
P="--profile stock-project --region ap-south-1"
B=stock-dashboard-542601847637-ap-south-1
cd "$(dirname "$0")/../../dashboard"
for f in index.html app.js auth.js config.js styles.css; do
  case "$f" in
    *.html) t="text/html; charset=utf-8" ;;
    *.js)   t="application/javascript; charset=utf-8" ;;
    *.css)  t="text/css; charset=utf-8" ;;
  esac
  aws s3api put-object $P --bucket "$B" --key "$f" --body "$f" --content-type "$t" \
    --cache-control "no-cache" --server-side-encryption AES256 --query ETag --output text | sed "s|^|$f |"
done
# Verify the bucket is still private: an anonymous request must be refused.
code=$(curl -s -o ../build/anon-check.txt -w "%{http_code}" "https://$B.s3.ap-south-1.amazonaws.com/index.html")
echo "anonymous GET index.html -> HTTP $code (expected 403)"
[ "$code" = "403" ]
