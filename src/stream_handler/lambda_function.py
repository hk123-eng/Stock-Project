"""stock-stream-handler: DynamoDB Streams (stock-prices, NEW_IMAGE) -> EventBridge bus stock-events.

For every INSERT of a real Alpha Vantage row (source = alphavantage) it publishes one
PriceIngested event (source stock.pipeline). The event source mapping already filters on
INSERT + source alphavantage; the handler checks again so nothing else can slip through.
It only reads the stream and calls events:PutEvents: it never writes to stock-prices and
never sends email (its role has no DynamoDB write and no SNS permission).
"""
import json
import os

import boto3

BUS = os.environ.get("EVENT_BUS", "stock-events")
SOURCE = "stock.pipeline"
DETAIL_TYPE = "PriceIngested"
FIELDS = ("symbol", "timestamp", "trade_date", "open", "high", "low", "close", "volume",
          "data_type", "adjusted", "ingested_at")
_events = None


def _client():
    global _events
    if _events is None:
        _events = boto3.client("events")
    return _events


def _plain(av):
    """One DynamoDB attribute value ({'S': ..} / {'N': ..} / {'BOOL': ..}) as a JSON value."""
    if "S" in av:
        return av["S"]
    if "N" in av:
        n = av["N"]
        return int(n) if n.lstrip("-").isdigit() else float(n)
    if "BOOL" in av:
        return av["BOOL"]
    return None


def price_events(records):
    """PutEvents entries for the INSERTs of real Alpha Vantage rows; everything else is skipped."""
    entries = []
    for r in records:
        img = (r.get("dynamodb") or {}).get("NewImage") or {}
        if r.get("eventName") != "INSERT" or _plain(img.get("source", {})) != "alphavantage":
            continue
        detail = {k: _plain(img[k]) for k in FIELDS if k in img}
        detail["stream_event_id"] = r.get("eventID")
        entries.append({"EventBusName": BUS, "Source": SOURCE, "DetailType": DETAIL_TYPE,
                        "Detail": json.dumps(detail, sort_keys=True)})
    return entries


def lambda_handler(event, context):
    records = event.get("Records", [])
    entries = price_events(records)
    sent = 0
    for i in range(0, len(entries), 10):  # PutEvents takes at most 10 entries
        chunk = entries[i:i + 10]
        resp = _client().put_events(Entries=chunk)
        if resp.get("FailedEntryCount"):
            # Raise so Lambda retries the batch (events are informational; duplicates are harmless)
            raise RuntimeError(f"PutEvents failed for {resp['FailedEntryCount']} of {len(chunk)} entries")
        sent += len(chunk)
    print(json.dumps({"records": len(records), "published": sent}))
    return {"records": len(records), "published": sent}
