"""stock-signals: technical signals + deduplicated alert decision.

Computes indicators from REAL rows only (source=alphavantage), stores them in
DynamoDB `stock-signals` (symbol / trade_date) and decides which alerts are new.
The pipeline combines the new alerts of all tickers into one SNS email.

Alert rules (thresholds via environment variables):
  BIG_MOVE        |daily change| >= BIG_MOVE_PCT (default 3%)
  SMA_CROSS       SMA20 crossed SMA50 since the previous trading day
  RSI_ZONE        RSI14 entered >= RSI_HIGH (70) or <= RSI_LOW (30) today
  PREDICTED_MOVE  |model predicted change| >= PRED_MOVE_PCT (default 2%)
  MACD_CROSS      MACD(12,26,9) line crossed its signal line since the previous trading day
  BOLLINGER_BREAK close is outside Bollinger(20, 2 sigma) today but was inside yesterday
                  (population sigma, as defined by John Bollinger)
Each rule can be switched off with ENABLE_<TYPE>=false.

Anti-spam: crossing/zone/break rules fire only on the day of the transition.
Dedup is per (symbol, trade_date, alert type): a conditional write on the item
attribute `alert_sent_<TYPE>` lets each type through once, so a second rule that
fires later on the same day is still reported and a repeat is never sent.
`alert_sent_at` keeps the time of the first alert of the day (history/API).
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
ALERT_TYPES = ("BIG_MOVE", "SMA_CROSS", "RSI_ZONE", "PREDICTED_MOVE", "MACD_CROSS", "BOLLINGER_BREAK")


def _enabled(alert_type):
    return os.environ.get(f"ENABLE_{alert_type}", "true").strip().lower() not in ("false", "0", "no", "off")


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


def ema_series(values, n):
    """EMA seeded with the SMA of the first n values (alpha = 2/(n+1)); None before the seed."""
    out = [None] * len(values)
    if len(values) < n:
        return out
    alpha = 2 / (n + 1)
    e = sum(values[:n]) / n
    out[n - 1] = e
    for i in range(n, len(values)):
        e = alpha * values[i] + (1 - alpha) * e
        out[i] = e
    return out


def macd(closes, fast=12, slow=26, signal=9):
    """(MACD line, signal line, histogram) at the last close, or (None, None, None)."""
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    line = [f - s for f, s in zip(ef, es) if f is not None and s is not None]
    if len(line) < signal:
        return None, None, None
    sig = ema_series(line, signal)[-1]
    return line[-1], sig, line[-1] - sig


def bollinger(closes, n=20, k=2):
    """(middle, upper, lower, %B) over the last n closes, population sigma."""
    if len(closes) < n:
        return None, None, None, None
    w = closes[-n:]
    mid = sum(w) / n
    sd = math.sqrt(sum((x - mid) ** 2 for x in w) / n)
    upper, lower = mid + k * sd, mid - k * sd
    pct_b = (closes[-1] - lower) / (upper - lower) if upper > lower else None
    return mid, upper, lower, pct_b


def indicators(closes):
    m_line, m_sig, m_hist = macd(closes)
    bb_mid, bb_up, bb_lo, bb_pb = bollinger(closes)
    return {
        "close": closes[-1],
        "prev_close": closes[-2] if len(closes) > 1 else None,
        "change_pct": (closes[-1] / closes[-2] - 1) * 100 if len(closes) > 1 else None,
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "rsi_14": rsi(closes),
        "volatility_20d_pct": volatility(closes),
        "macd": m_line, "macd_signal": m_sig, "macd_hist": m_hist,
        "bb_middle": bb_mid, "bb_upper": bb_up, "bb_lower": bb_lo, "bb_pct_b": bb_pb,
    }


def _present(d, *keys):
    return all(d.get(k) is not None for k in keys)


def evaluate_rules(today, yesterday, prediction):
    alerts = []
    if today.get("change_pct") is not None and abs(today["change_pct"]) >= BIG_MOVE_PCT:
        alerts.append({"type": "BIG_MOVE", "detail": f"Close moved {today['change_pct']:+.2f}% (threshold ±{BIG_MOVE_PCT:g}%)"})
    if _present(today, "sma_20", "sma_50") and _present(yesterday, "sma_20", "sma_50"):
        now_above = today["sma_20"] > today["sma_50"]
        was_above = yesterday["sma_20"] > yesterday["sma_50"]
        if now_above != was_above:
            kind = "golden cross (SMA20 above SMA50)" if now_above else "death cross (SMA20 below SMA50)"
            alerts.append({"type": "SMA_CROSS", "detail": f"{kind}: SMA20 {today['sma_20']:.2f} vs SMA50 {today['sma_50']:.2f}"})
    if today.get("rsi_14") is not None and yesterday.get("rsi_14") is not None:
        if today["rsi_14"] >= RSI_HIGH > yesterday["rsi_14"]:
            alerts.append({"type": "RSI_ZONE", "detail": f"RSI14 entered overbought zone: {today['rsi_14']:.1f} (≥{RSI_HIGH:g})"})
        elif today["rsi_14"] <= RSI_LOW < yesterday["rsi_14"]:
            alerts.append({"type": "RSI_ZONE", "detail": f"RSI14 entered oversold zone: {today['rsi_14']:.1f} (≤{RSI_LOW:g})"})
    pc = (prediction or {}).get("predicted_change_pct")
    if isinstance(pc, (int, float)) and abs(pc) >= PRED_MOVE_PCT:
        caveat = " Model inputs are outside its training range; treat as low confidence." if prediction.get("inputs_outside_scaler_range") else ""
        alerts.append({"type": "PREDICTED_MOVE", "detail": f"LSTM predicts {pc:+.2f}% next close ({prediction.get('prediction')}) (threshold ±{PRED_MOVE_PCT:g}%; experimental, does not beat baseline).{caveat}"})
    if _present(today, "macd", "macd_signal") and _present(yesterday, "macd", "macd_signal"):
        now_above = today["macd"] > today["macd_signal"]
        was_above = yesterday["macd"] > yesterday["macd_signal"]
        if now_above != was_above:
            kind = "bullish (MACD above signal)" if now_above else "bearish (MACD below signal)"
            alerts.append({"type": "MACD_CROSS", "detail": f"{kind}: MACD {today['macd']:.3f} vs signal {today['macd_signal']:.3f}"})
    if _present(today, "close", "bb_upper", "bb_lower") and _present(yesterday, "close", "bb_upper", "bb_lower"):
        was_inside = yesterday["bb_lower"] <= yesterday["close"] <= yesterday["bb_upper"]
        if was_inside and today["close"] > today["bb_upper"]:
            alerts.append({"type": "BOLLINGER_BREAK", "detail": f"close {today['close']:.2f} broke above the upper Bollinger band {today['bb_upper']:.2f}"})
        elif was_inside and today["close"] < today["bb_lower"]:
            alerts.append({"type": "BOLLINGER_BREAK", "detail": f"close {today['close']:.2f} broke below the lower Bollinger band {today['bb_lower']:.2f}"})
    return [a for a in alerts if _enabled(a["type"])]


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


def mark_sent(table, symbol, trade_date, alert_type, now, execution):
    """True if (symbol, trade_date, type) was not sent before; marks it sent atomically."""
    if alert_type not in ALERT_TYPES:
        raise ValueError(f"unknown alert type {alert_type}")
    try:
        table.update_item(
            Key={"symbol": symbol, "trade_date": trade_date},
            UpdateExpression="SET #m = :now, alert_sent_at = if_not_exists(alert_sent_at, :now), "
                             "alert_execution = if_not_exists(alert_execution, :ex)",
            ConditionExpression="attribute_not_exists(#m)",
            ExpressionAttributeNames={"#m": f"alert_sent_{alert_type}"},
            ExpressionAttributeValues={":now": now, ":ex": execution},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def format_message(symbol, trade_date, alerts, ind, prediction):
    lines = [f"{symbol} signals for trading day {trade_date} (real Alpha Vantage data, unadjusted):", ""]
    lines += [f"- {a['type']}: {a['detail']}" for a in alerts]
    if _present(ind, "sma_20", "sma_50", "rsi_14", "change_pct"):
        lines += ["", f"Close {ind['close']:.2f} ({ind['change_pct']:+.2f}%), SMA20 {ind['sma_20']:.2f}, "
                      f"SMA50 {ind['sma_50']:.2f}, RSI14 {ind['rsi_14']:.1f}"]
    if _present(ind, "macd", "macd_signal", "bb_lower", "bb_upper"):
        lines.append(f"MACD {ind['macd']:.3f} / signal {ind['macd_signal']:.3f}; "
                     f"Bollinger {ind['bb_lower']:.2f} - {ind['bb_upper']:.2f}")
    if prediction.get("prediction") is not None:
        lines.append(f"LSTM next-close prediction: {prediction.get('prediction')} (experimental, does not beat baseline)")
    return lines


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
        "alerts": [], "already_sent": [], "deduplicated": False,
        "indicators": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in today.items()},
    }
    execution = str(event.get("execution_id", "manual"))
    new = [a for a in alerts if mark_sent(table, symbol, trade_date, a["type"], now, execution)]
    result["already_sent"] = sorted({a["type"] for a in alerts} - {a["type"] for a in new})
    result["deduplicated"] = bool(result["already_sent"])
    result["alerts"] = new  # only alerts not sent before for this (symbol, trade_date, type)
    if new:
        lines = format_message(symbol, trade_date, new, today, prediction) + ["Not financial advice. College project."]
        result.update(alert=True, subject=f"{symbol} alert {trade_date}: " + ", ".join(sorted({a['type'] for a in new})),
                      message="\n".join(lines))
    return result
