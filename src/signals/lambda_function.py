"""stock-signals: technical signals + deduplicated alert decision.

Computes indicators from REAL rows only (source=alphavantage), stores them in
DynamoDB `stock-signals` (symbol / trade_date) and decides whether an alert
should be sent. The Step Function publishes the alert to SNS.

Alert rules (thresholds via environment variables):
  BIG_MOVE        |daily change| >= BIG_MOVE_PCT (default 3%)
  SMA_CROSS       SMA20 crossed SMA50 since the previous trading day
  RSI_ZONE        RSI14 entered >= RSI_HIGH (70) or <= RSI_LOW (30) today
  PREDICTED_MOVE  |model predicted change| >= PRED_MOVE_PCT (default 2%)
Anti-spam: crossing/zone rules fire only on the day of the transition, and at
most one alert email per (symbol, trade_date) is allowed, enforced by a
conditional write on `alert_sent_at`. Re-runs on the same data never re-alert.
"""
import datetime as dt
import math
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

PRICES_TABLE = os.environ.get("PRICES_TABLE", "stock-prices")
SIGNALS_TABLE = os.environ.get("SIGNALS_TABLE", "stock-signals")
BIG_MOVE_PCT = float(os.environ.get("BIG_MOVE_PCT", "3"))
PRED_MOVE_PCT = float(os.environ.get("PRED_MOVE_PCT", "2"))
RSI_HIGH = float(os.environ.get("RSI_HIGH", "70"))
RSI_LOW = float(os.environ.get("RSI_LOW", "30"))
REAL_SOURCE = "alphavantage"


def sma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def rsi(closes, n=14):
    """Wilder's RSI over the full series."""
    if len(closes) <= n:
        return None
    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(d, 0) for d in deltas[:n]) / n
    loss = sum(max(-d, 0) for d in deltas[:n]) / n
    for d in deltas[n:]:
        gain = (gain * (n - 1) + max(d, 0)) / n
        loss = (loss * (n - 1) + max(-d, 0)) / n
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def volatility(closes, n=20):
    if len(closes) <= n:
        return None
    rets = [(b / a - 1) * 100 for a, b in zip(closes[-n - 1:], closes[-n:])]
    mean = sum(rets) / n
    return math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))


def indicators(closes):
    return {
        "close": closes[-1],
        "prev_close": closes[-2] if len(closes) > 1 else None,
        "change_pct": (closes[-1] / closes[-2] - 1) * 100 if len(closes) > 1 else None,
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "rsi_14": rsi(closes),
        "volatility_20d_pct": volatility(closes),
    }


def evaluate_rules(today, yesterday, prediction):
    alerts = []
    if today["change_pct"] is not None and abs(today["change_pct"]) >= BIG_MOVE_PCT:
        alerts.append({"type": "BIG_MOVE", "detail": f"Close moved {today['change_pct']:+.2f}% (threshold ±{BIG_MOVE_PCT:g}%)"})
    if None not in (today["sma_20"], today["sma_50"], yesterday["sma_20"], yesterday["sma_50"]):
        now_above = today["sma_20"] > today["sma_50"]
        was_above = yesterday["sma_20"] > yesterday["sma_50"]
        if now_above != was_above:
            kind = "golden cross (SMA20 above SMA50)" if now_above else "death cross (SMA20 below SMA50)"
            alerts.append({"type": "SMA_CROSS", "detail": f"{kind}: SMA20 {today['sma_20']:.2f} vs SMA50 {today['sma_50']:.2f}"})
    if today["rsi_14"] is not None and yesterday["rsi_14"] is not None:
        if today["rsi_14"] >= RSI_HIGH > yesterday["rsi_14"]:
            alerts.append({"type": "RSI_ZONE", "detail": f"RSI14 entered overbought zone: {today['rsi_14']:.1f} (≥{RSI_HIGH:g})"})
        elif today["rsi_14"] <= RSI_LOW < yesterday["rsi_14"]:
            alerts.append({"type": "RSI_ZONE", "detail": f"RSI14 entered oversold zone: {today['rsi_14']:.1f} (≤{RSI_LOW:g})"})
    pc = (prediction or {}).get("predicted_change_pct")
    if isinstance(pc, (int, float)) and abs(pc) >= PRED_MOVE_PCT:
        caveat = " Model inputs are outside its training range; treat as low confidence." if prediction.get("inputs_outside_scaler_range") else ""
        alerts.append({"type": "PREDICTED_MOVE", "detail": f"LSTM predicts {pc:+.2f}% next close ({prediction.get('prediction')}) (threshold ±{PRED_MOVE_PCT:g}%).{caveat}"})
    return alerts


def _real_rows(symbol):
    table = boto3.resource("dynamodb").Table(PRICES_TABLE)
    kwargs = {"KeyConditionExpression": Key("symbol").eq(symbol), "FilterExpression": Attr("source").eq(REAL_SOURCE)}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    items.sort(key=lambda i: i["timestamp"])
    return [(i["trade_date"], float(i["close"])) for i in items]


def _dec(x, places=4):
    return None if x is None else Decimal(str(round(x, places)))


def lambda_handler(event, context):
    event = event or {}
    symbol = event.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        return {"statusCode": 400, "error": "missing symbol"}
    prediction = event.get("prediction") if isinstance(event.get("prediction"), dict) else {}
    rows = _real_rows(symbol)
    if len(rows) < 2:
        return {"statusCode": 400, "symbol": symbol, "error": f"need >= 2 real prices, have {len(rows)}"}
    closes = [c for _, c in rows]
    trade_date = rows[-1][0]
    today = indicators(closes)
    yesterday = indicators(closes[:-1])
    alerts = evaluate_rules(today, yesterday, prediction)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    table = boto3.resource("dynamodb").Table(SIGNALS_TABLE)
    values = {f":{k}": _dec(v) for k, v in today.items()}
    values.update({
        ":alerts": [{"type": a["type"], "detail": a["detail"]} for a in alerts],
        ":src": REAL_SOURCE, ":now": now,
        ":pred": _dec(prediction.get("prediction")) if isinstance(prediction.get("prediction"), (int, float)) else None,
        ":predpct": _dec(prediction.get("predicted_change_pct"), 3) if isinstance(prediction.get("predicted_change_pct"), (int, float)) else None,
    })
    extra = {"alerts": ":alerts", "input_source": ":src", "computed_at": ":now",
             "predicted_close": ":pred", "predicted_change_pct": ":predpct"}
    fields = {k: f":{k}" for k in today} | extra
    # Every attribute name goes through a placeholder ("close" is a DynamoDB reserved word).
    names = {f"#a{i}": k for i, k in enumerate(fields)}
    set_expr = ", ".join(f"{n} = {fields[k]}" for n, k in names.items())
    table.update_item(Key={"symbol": symbol, "trade_date": trade_date}, UpdateExpression="SET " + set_expr,
                      ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    result = {
        "statusCode": 200, "symbol": symbol, "trade_date": trade_date, "alert": False,
        "alerts": alerts, "deduplicated": False,
        "indicators": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in today.items()},
    }
    if not alerts:
        return result
    try:
        table.update_item(
            Key={"symbol": symbol, "trade_date": trade_date},
            UpdateExpression="SET alert_sent_at = :now, alert_execution = :ex",
            ConditionExpression="attribute_not_exists(alert_sent_at)",
            ExpressionAttributeValues={":now": now, ":ex": str(event.get("execution_id", "manual"))},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            result["deduplicated"] = True  # already alerted for this trading day
            return result
        raise
    ind = today
    lines = [f"{symbol} signals for trading day {trade_date} (real Alpha Vantage data, unadjusted):", ""]
    lines += [f"- {a['type']}: {a['detail']}" for a in alerts]
    lines += ["", f"Close {ind['close']:.2f} ({ind['change_pct']:+.2f}%), SMA20 {ind['sma_20']:.2f}, "
              f"SMA50 {ind['sma_50']:.2f}, RSI14 {ind['rsi_14']:.1f}" if None not in (ind['sma_20'], ind['sma_50'], ind['rsi_14']) else ""]
    if prediction.get("prediction") is not None:
        lines.append(f"LSTM next-close prediction: {prediction.get('prediction')} (experimental; see project evaluation for measured error)")
    lines.append("Not financial advice. College project.")
    result.update(alert=True, subject=f"{symbol} alert {trade_date}: " + ", ".join(sorted({a['type'] for a in alerts})),
                  message="\n".join(lines))
    return result
