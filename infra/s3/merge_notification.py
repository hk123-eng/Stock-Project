"""Merge the stock-archive-validator rule into an existing bucket notification configuration.
put-bucket-notification-configuration REPLACES everything, so every existing entry is kept.
Usage: python infra/s3/merge_notification.py <before.json> <after.json>"""
import json
import sys

RULE = {
    "Id": "stock-archive-validator-raw",
    "LambdaFunctionArn": "arn:aws:lambda:ap-south-1:542601847637:function:stock-archive-validator",
    "Events": ["s3:ObjectCreated:*"],
    "Filter": {"Key": {"FilterRules": [{"Name": "Prefix", "Value": "raw/"}]}},
}
before = json.load(open(sys.argv[1]))
after = json.loads(json.dumps(before))
after.pop("ResponseMetadata", None)
lam = [c for c in after.get("LambdaFunctionConfigurations", []) if c.get("Id") != RULE["Id"]]
after["LambdaFunctionConfigurations"] = lam + [RULE]
for k in ("TopicConfigurations", "QueueConfigurations", "EventBridgeConfiguration"):
    assert after.get(k) == before.get(k), k  # untouched
json.dump(after, open(sys.argv[2], "w"), indent=2)
print(json.dumps(after))
