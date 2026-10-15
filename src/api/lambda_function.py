"""stock-api: read-only JSON API behind API Gateway (HTTP API, Cognito JWT authorizer).

GET /prices              real daily prices (source=alphavantage), oldest first
GET /prices/latest       latest real price
GET /prices/synthetic    legacy SYNTHETIC rows, explicitly labelled (never mixed into /prices)
GET /predictions         prediction history, joined with the actual next real close when known
GET /predictions/latest  latest persisted prediction
GET /signals             signal history (latest last)
GET /alerts              trading days on which an alert was raised
GET /evaluation          latest model evaluation report (S3 predictions/evaluation/<SYMBOL>-latest.json)
GET /model-health        live scored predictions (stored by stock-evaluate) vs the naive baseline;
                         verdict is "insufficient data" until 20 days are scored

Query parameters: symbol (default AAPL, allow-listed), limit (1-500).
"""
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

PRICES_TABLE = os.environ.get("PRICES_TABLE", "stock-prices")
PREDICTIONS_TABLE = os.environ.get("PREDICTIONS_TABLE", "stock-predictions")
SIGNALS_TABLE = os.environ.get("SIGNALS_TABLE", "stock-signals")
BUCKET = os.environ.get("BUCKET", "stock-prediction-raw-542601847637-ap-south-1-an")
SYMBOLS = {"AAPL"}
MIN_SCORED_DAYS = 20  # no beats/does-not-beat verdict below this many live scored days
REAL_SOURCE = "alphavantage"
DATA_NOTE = ("Real daily prices from Alpha Vantage TIME_SERIES_DAILY (compact: latest 100 trading days). "
             "Prices are NOT adjusted for splits/dividends.")

_ddb = boto3.resource("dynamodb")


def _json(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() and "." not in str(o) else float(o)
    raise TypeError(type(o).__name__)


def _resp(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "body": json.dumps(body, default=_json)}


def _query_all(table, symbol, **extra):
    kwargs = {"KeyConditionExpression": Key("symbol").eq(symbol), **extra}
    items = []
    while True:
        r = _ddb.Table(table).query(**kwargs)
        items.extend(r.get("Items", []))
        if "LastEvaluatedKey" not in r:
            return items
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def _real_prices(symbol):
    items = _query_all(PRICES_TABLE, symbol, FilterExpression=Attr("source").eq(REAL_SOURCE))
    items.sort(key=lambda i: i["timestamp"])
    return [{k: i.get(k) for k in ("trade_date", "timestamp", "open", "high", "low", "close", "volume", "source", "data_type")}
            for i in items]


def prices(symbol, limit):
    rows = _real_prices(symbol)
    return {"symbol": symbol, "data_type": "real", "note": DATA_NOTE, "count": len(rows[-limit:]),
            "synthetic_rows_excluded": _count_synthetic(symbol), "prices": rows[-limit:]}


def _count_synthetic(symbol):
    kwargs = {"KeyConditionExpression": Key("symbol").eq(symbol),
              "FilterExpression": Attr("source").not_exists(), "Select": "COUNT"}
    n = 0
    while True:
        r = _ddb.Table(PRICES_TABLE).query(**kwargs)
        n += r["Count"]
        if "LastEvaluatedKey" not in r:
            return n
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def latest_price(symbol, _):
    rows = _real_prices(symbol)
    if not rows:
        return None
    return {"symbol": symbol, "data_type": "real", "note": DATA_NOTE, "latest": rows[-1],
            "previous": rows[-2] if len(rows) > 1 else None}


def synthetic_prices(symbol, limit):
    items = _query_all(PRICES_TABLE, symbol, FilterExpression=Attr("source").not_exists())
    items.sort(key=lambda i: i["timestamp"])
    rows = [{"timestamp": i["timestamp"], "close": float(i["close"]), "data_type": "synthetic"} for i in items]
    return {"symbol": symbol, "data_type": "synthetic",
            "warning": "SYNTHETIC test data generated during the prototype phase. NOT real market data. Not used by the model or signals.",
            "count": len(rows[-limit:]), "prices": rows[-limit:]}


def predictions(symbol, limit):
    preds = _query_all(PREDICTIONS_TABLE, symbol)
    preds.sort(key=lambda p: p["as_of_date"])
    real = _real_prices(symbol)
    dates = [r["trade_date"] for r in real]
    out = []
    for p in preds[-limit:]:
        item = {k: p.get(k) for k in ("as_of_date", "target_date_estimate", "predicted_close", "last_close",
                                       "predicted_change_pct", "inputs_outside_scaler_range", "model_version", "created_at")}
        later = [r for r in real if r["trade_date"] > p["as_of_date"]]
        if "scored_at" in p:  # stored by stock-evaluate
            item.update({k: p.get(k) for k in ("actual_date", "actual_close", "error", "abs_pct_error", "naive_error", "scored_at")})
        elif later:  # not scored yet: the actual next real trading day after as_of_date
            actual = later[0]
            err = float(p["predicted_close"]) - float(actual["close"])
            item.update(actual_date=actual["trade_date"], actual_close=actual["close"],
                        error=round(err, 4), abs_pct_error=round(abs(err) / float(actual["close"]) * 100, 4))
        else:
            item.update(actual_date=None, actual_close=None, error=None, abs_pct_error=None)
        out.append(item)
    scored = [o for o in out if o["error"] is not None]
    summary = {"predictions": len(out), "scored": len(scored),
               "mae": round(sum(abs(o["error"]) for o in scored) / len(scored), 4) if scored else None}
    return {"symbol": symbol, "target": "next trading day close", "latest_real_date": dates[-1] if dates else None,
            "summary": summary, "predictions": out}


def latest_prediction(symbol, _):
    p = predictions(symbol, 1)
    return {"symbol": symbol, "prediction": p["predictions"][-1]} if p["predictions"] else None


def signals(symbol, limit):
    items = _query_all(SIGNALS_TABLE, symbol)
    items.sort(key=lambda i: i["trade_date"])
    return {"symbol": symbol, "data_type": "real", "count": len(items[-limit:]), "signals": items[-limit:]}


def alerts(symbol, limit):
    items = [i for i in _query_all(SIGNALS_TABLE, symbol) if i.get("alerts")]
    items.sort(key=lambda i: i["trade_date"])
    return {"symbol": symbol, "alerts": [
        {"trade_date": i["trade_date"], "alerts": i["alerts"], "alert_sent_at": i.get("alert_sent_at"),
         "notified": "alert_sent_at" in i,
         # test runs are labelled with an execution id starting "test-"; a direct test invocation sends no email
         "test_alert": str(i.get("alert_execution", "")).split(":")[-1].startswith("test-"),
         # per-type markers written by stock-signals since Phase 8 item 2 (older items only have alert_sent_at)
         "notified_types": sorted(k[len("alert_sent_"):] for k in i if k.startswith("alert_sent_") and k != "alert_sent_at")}
        for i in items[-limit:]]}


def _mae(xs):
    return round(sum(abs(x) for x in xs) / len(xs), 4) if xs else None


def health_summary(days, min_days=MIN_SCORED_DAYS):
    """Live model health from scored days (oldest first). No verdict below min_days."""
    n = len(days)
    model_all = _mae([d["error"] for d in days])
    naive_all = _mae([d["naive_error"] for d in days])
    last = days[-min_days:]
    if n < min_days:
        verdict, beats = f"insufficient data ({n} of {min_days} scored days)", None
    else:
        beats = model_all < naive_all
        verdict = "beats baseline" if beats else "does not beat baseline"
    return {
        "scored_days": n, "min_days_for_verdict": min_days, "verdict": verdict, "beats_baseline": beats,
        "all": {"model_mae": model_all, "naive_mae": naive_all, "days": n},
        "rolling": {"model_mae": _mae([d["error"] for d in last]), "naive_mae": _mae([d["naive_error"] for d in last]),
                    "days": len(last)},
        "first_actual_date": days[0]["actual_date"] if days else None,
        "last_actual_date": days[-1]["actual_date"] if days else None,
    }


def model_health(symbol, limit):
    items = [i for i in _query_all(PREDICTIONS_TABLE, symbol) if "scored_at" in i]
    items.sort(key=lambda i: i["as_of_date"])
    days = [{"as_of_date": i["as_of_date"], "actual_date": i["actual_date"],
             "predicted_close": float(i["predicted_close"]), "last_close": float(i["last_close"]),
             "actual_close": float(i["actual_close"]), "error": float(i["error"]),
             "naive_error": float(i["naive_error"]), "model_version": i.get("model_version")} for i in items]
    ev = evaluation(symbol, None)
    backtest = None
    if ev and ev.get("model"):
        backtest = {"source": "walk-forward backtest (not live)", "n_predictions": ev.get("n_predictions"),
                    "first_target_date": ev.get("first_target_date"), "last_target_date": ev.get("last_target_date"),
                    "model_mae": ev["model"].get("mae"), "naive_mae": ev["naive_last_close_baseline"].get("mae")}
    return {"symbol": symbol, "target": "next trading day close", "baseline": "naive: tomorrow's close = today's close",
            "live": health_summary(days), "days": days[-limit:], "backtest": backtest}


def evaluation(symbol, _):
    try:
        obj = boto3.client("s3").get_object(Bucket=BUCKET, Key=f"predictions/evaluation/{symbol}-latest.json")
    except ClientError as e:
        # Without s3:ListBucket, S3 reports a missing object as AccessDenied.
        if e.response["Error"]["Code"] in ("NoSuchKey", "404", "AccessDenied"):
            return None
        raise
    return json.loads(obj["Body"].read())


ROUTES = {
    "/prices": prices, "/prices/latest": latest_price, "/prices/synthetic": synthetic_prices,
    "/predictions": predictions, "/predictions/latest": latest_prediction,
    "/signals": signals, "/alerts": alerts, "/evaluation": evaluation, "/model-health": model_health,
}


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    if path.startswith("/prod/"):
        path = path[len("/prod"):]
    if method != "GET":
        return _resp(405, {"error": "method not allowed"})
    handler = ROUTES.get(path.rstrip("/") or "/")
    if not handler:
        return _resp(404, {"error": "not found", "routes": sorted(ROUTES)})
    qs = event.get("queryStringParameters") or {}
    symbol = (qs.get("symbol") or "AAPL").upper()
    if symbol not in SYMBOLS:
        return _resp(400, {"error": f"unsupported symbol; supported: {sorted(SYMBOLS)}"})
    try:
        limit = int(qs.get("limit", "100"))
    except ValueError:
        return _resp(400, {"error": "limit must be an integer"})
    if not 1 <= limit <= 500:
        return _resp(400, {"error": "limit must be 1-500"})
    body = handler(symbol, limit)
    if body is None:
        return _resp(404, {"error": "no data yet", "symbol": symbol})
    return _resp(200, body)
