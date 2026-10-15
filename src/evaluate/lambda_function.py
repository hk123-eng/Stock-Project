"""stock-evaluate: score saved predictions against the next real close.

For every item in `stock-predictions` without `scored_at`, find the first REAL
trading day (source=alphavantage) after `as_of_date`. If it exists, store on the
same item:
  actual_date, actual_close
  error          = predicted_close - actual_close
  abs_pct_error  = |error| / actual_close * 100
  naive_error    = last_close - actual_close   ("tomorrow = today" baseline)
  naive_abs_pct_error
  scored_at
The write is conditional on attribute_not_exists(scored_at), so re-runs never
re-score an item. Predictions whose next trading day has not closed yet stay
pending. Newly scored days are also published as CloudWatch custom metrics
(namespace StockProject/ModelHealth: ModelAbsError, NaiveAbsError, by Symbol).
"""
import datetime as dt
import os
import re
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

PRICES_TABLE = os.environ.get("PRICES_TABLE", "stock-prices")
PREDICTIONS_TABLE = os.environ.get("PREDICTIONS_TABLE", "stock-predictions")
NAMESPACE = os.environ.get("METRIC_NAMESPACE", "StockProject/ModelHealth")
REAL_SOURCE = "alphavantage"
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")


def next_real_day(rows, as_of_date):
    """First (trade_date, close) strictly after as_of_date; rows are sorted oldest first."""
    for d, c in rows:
        if d > as_of_date:
            return d, c
    return None


def score(prediction, actual_date, actual_close):
    predicted = float(prediction["predicted_close"])
    last = float(prediction["last_close"])
    err = predicted - actual_close
    naive = last - actual_close
    return {
        "actual_date": actual_date,
        "actual_close": actual_close,
        "error": err,
        "abs_pct_error": abs(err) / actual_close * 100,
        "naive_error": naive,
        "naive_abs_pct_error": abs(naive) / actual_close * 100,
    }


def _query_all(table, **kwargs):
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _real_rows(symbol):
    table = boto3.resource("dynamodb").Table(PRICES_TABLE)
    items = _query_all(table, KeyConditionExpression=Key("symbol").eq(symbol),
                       FilterExpression=Attr("source").eq(REAL_SOURCE))
    items.sort(key=lambda i: i["timestamp"])
    return [(i["trade_date"], float(i["close"])) for i in items]


def _d(x, places=4):
    return Decimal(str(round(x, places)))


def lambda_handler(event, context):
    event = event or {}
    symbol = event.get("symbol")
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
        return {"statusCode": 400, "error": "invalid or missing symbol"}

    rows = _real_rows(symbol)
    table = boto3.resource("dynamodb").Table(PREDICTIONS_TABLE)
    preds = _query_all(table, KeyConditionExpression=Key("symbol").eq(symbol))
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    now_iso = now.isoformat().replace("+00:00", "Z")

    scored, already, pending, metrics = [], 0, 0, []
    for p in sorted(preds, key=lambda i: i["as_of_date"]):
        if "scored_at" in p:
            already += 1
            continue
        nxt = next_real_day(rows, p["as_of_date"])
        if nxt is None:
            pending += 1
            continue
        s = score(p, *nxt)
        try:
            table.update_item(
                Key={"symbol": symbol, "as_of_date": p["as_of_date"]},
                UpdateExpression="SET actual_date = :ad, actual_close = :ac, #e = :e, abs_pct_error = :ape, "
                                 "naive_error = :ne, naive_abs_pct_error = :nape, scored_at = :now",
                ConditionExpression="attribute_not_exists(scored_at)",
                ExpressionAttributeNames={"#e": "error"},
                ExpressionAttributeValues={
                    ":ad": s["actual_date"], ":ac": _d(s["actual_close"]), ":e": _d(s["error"]),
                    ":ape": _d(s["abs_pct_error"]), ":ne": _d(s["naive_error"]),
                    ":nape": _d(s["naive_abs_pct_error"]), ":now": now_iso,
                },
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                already += 1  # scored concurrently by another run
                continue
            raise
        scored.append({"as_of_date": p["as_of_date"], "actual_date": s["actual_date"],
                       "error": round(s["error"], 4), "naive_error": round(s["naive_error"], 4)})
        dims = [{"Name": "Symbol", "Value": symbol}]
        metrics += [
            {"MetricName": "ModelAbsError", "Dimensions": dims, "Value": abs(s["error"]), "Unit": "None", "Timestamp": now},
            {"MetricName": "NaiveAbsError", "Dimensions": dims, "Value": abs(s["naive_error"]), "Unit": "None", "Timestamp": now},
        ]

    if metrics:
        cw = boto3.client("cloudwatch")
        for i in range(0, len(metrics), 500):
            cw.put_metric_data(Namespace=NAMESPACE, MetricData=metrics[i:i + 500])

    result = {"statusCode": 200, "symbol": symbol, "newly_scored": len(scored), "already_scored": already,
              "pending": pending, "scored": scored}
    print(result)
    return result
