"""stock-lstm-inference: next-trading-day close prediction with the TFLite LSTM.

Modes (event["mode"]):
  "predict" (default)  - uses the latest 60 REAL closes (source=alphavantage);
                         legacy synthetic rows are ignored. The prediction is
                         persisted to DynamoDB `stock-predictions`.
  "evaluate"           - read-only walk-forward backtest over all real rows,
                         compared with a naive "tomorrow = today" baseline.

The model and scaler are unchanged from the original working version
(S3 models/aapl_lstm_model.tflite + models/scaler.pkl, SEQ_LEN 60, 1 feature).
"""
import datetime as dt
import math
import os
import pickle
from decimal import Decimal

import boto3
import numpy as np
from boto3.dynamodb.conditions import Attr, Key
from tflite_runtime.interpreter import Interpreter

S3_BUCKET = "stock-prediction-raw-542601847637-ap-south-1-an"
MODEL_KEY = "models/aapl_lstm_model.tflite"
SCALER_KEY = "models/scaler.pkl"
MODEL_VERSION = "aapl_lstm_model.tflite (S3 upload 2026-09-16, 443852 bytes)"

MODEL_PATH = "/tmp/model.tflite"
SCALER_PATH = "/tmp/scaler.pkl"

PRICES_TABLE = os.environ.get("PRICES_TABLE", "stock-prices")
PREDICTIONS_TABLE = os.environ.get("PREDICTIONS_TABLE", "stock-predictions")
REAL_SOURCE = "alphavantage"
SUPPORTED_SYMBOLS = {"AAPL"}  # the model was trained on AAPL only
SEQ_LEN = 60
FEATURES = 1

_interpreter = None
_scaler = None


def _load_artifacts():
    global _interpreter, _scaler
    if _interpreter is None:
        s3 = boto3.client("s3")
        s3.download_file(S3_BUCKET, MODEL_KEY, MODEL_PATH)
        s3.download_file(S3_BUCKET, SCALER_KEY, SCALER_PATH)
        _interpreter = Interpreter(model_path=MODEL_PATH)
        _interpreter.allocate_tensors()
    if _scaler is None:
        with open(SCALER_PATH, "rb") as f:
            _scaler = pickle.load(f)
    return _interpreter, _scaler


def _real_rows(symbol):
    """All real rows for symbol, oldest first. Synthetic rows (no source tag) are skipped."""
    table = boto3.resource("dynamodb").Table(PRICES_TABLE)
    kwargs = {
        "KeyConditionExpression": Key("symbol").eq(symbol),
        "FilterExpression": Attr("source").eq(REAL_SOURCE),
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    items.sort(key=lambda i: i["timestamp"])
    return [(i["trade_date"], float(i["close"])) for i in items]


def _predict_window(interp, scaler, closes):
    raw = np.array(closes, dtype=np.float32).reshape(-1, 1)
    x = scaler.transform(raw).astype(np.float32).reshape(1, SEQ_LEN, FEATURES)
    inp = interp.get_input_details()[0]
    out = interp.get_output_details()[0]
    interp.set_tensor(inp["index"], x)
    interp.invoke()
    pred_scaled = interp.get_tensor(out["index"]).reshape(-1, 1)
    return float(scaler.inverse_transform(pred_scaled)[0][0])


def _scaler_range(scaler):
    return float(scaler.data_min_[0]), float(scaler.data_max_[0])


def _next_weekday(date_str):
    d = dt.date.fromisoformat(date_str) + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return d.isoformat()


def _d(x, places=4):
    return Decimal(str(round(x, places)))


def _predict(symbol, execution_id):
    interp, scaler = _load_artifacts()
    rows = _real_rows(symbol)
    if len(rows) < SEQ_LEN:
        return {"statusCode": 400, "symbol": symbol, "error": f"need {SEQ_LEN} real prices, have {len(rows)}"}
    window = rows[-SEQ_LEN:]
    closes = [c for _, c in window]
    pred = _predict_window(interp, scaler, closes)
    lo, hi = _scaler_range(scaler)
    out_of_range = any(c < lo or c > hi for c in closes)
    as_of, last_close = window[-1]
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    item = {
        "symbol": symbol,
        "as_of_date": as_of,
        "target": "next_trading_day_close",
        "target_date_estimate": _next_weekday(as_of),
        "predicted_close": _d(pred),
        "last_close": _d(last_close),
        "predicted_change_pct": _d((pred - last_close) / last_close * 100, 3),
        "window_start": window[0][0],
        "window_end": as_of,
        "input_source": REAL_SOURCE,
        "inputs_outside_scaler_range": out_of_range,
        "scaler_range": [_d(lo), _d(hi)],
        "model_version": MODEL_VERSION,
        "created_at": now,
    }
    if execution_id:
        item["execution_id"] = execution_id
    # Keyed by (symbol, as_of_date): re-running on the same data overwrites the same item.
    boto3.resource("dynamodb").Table(PREDICTIONS_TABLE).put_item(Item=item)
    print(f"prediction symbol={symbol} as_of={as_of} last_close={last_close:.2f} predicted={pred:.4f}")
    return {
        "statusCode": 200,
        "symbol": symbol,
        "prediction": round(pred, 4),
        "as_of_date": as_of,
        "last_close": last_close,
        "predicted_change_pct": round((pred - last_close) / last_close * 100, 3),
        "inputs_outside_scaler_range": out_of_range,
        "persisted_to": PREDICTIONS_TABLE,
    }


def _metrics(errors, actuals):
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    mape = sum(abs(e) / a for e, a in zip(errors, actuals)) / n * 100
    bias = sum(errors) / n
    return {"mae": round(mae, 4), "rmse": round(rmse, 4), "mape_pct": round(mape, 4), "mean_error_bias": round(bias, 4)}


def _evaluate(symbol):
    """Walk-forward: for each real day t with 60 prior real closes, predict close[t]."""
    interp, scaler = _load_artifacts()
    rows = _real_rows(symbol)
    if len(rows) <= SEQ_LEN:
        return {"statusCode": 400, "symbol": symbol, "error": f"need > {SEQ_LEN} real prices, have {len(rows)}"}
    lo, hi = _scaler_range(scaler)
    points, m_err, n_err, actuals = [], [], [], []
    dir_hits = dir_total = 0
    for t in range(SEQ_LEN, len(rows)):
        closes = [c for _, c in rows[t - SEQ_LEN:t]]
        prev = closes[-1]
        date, actual = rows[t]
        pred = _predict_window(interp, scaler, closes)
        m_err.append(pred - actual)
        n_err.append(prev - actual)
        actuals.append(actual)
        if actual != prev:
            dir_total += 1
            dir_hits += (pred > prev) == (actual > prev)
        points.append({"date": date, "actual": actual, "predicted": round(pred, 4), "previous_close": prev})
    return {
        "statusCode": 200,
        "symbol": symbol,
        "mode": "evaluate",
        "method": "walk-forward, 60 real closes -> next real close; inputs are unadjusted Alpha Vantage closes",
        "model_version": MODEL_VERSION,
        "n_predictions": len(points),
        "first_target_date": points[0]["date"],
        "last_target_date": points[-1]["date"],
        "model": _metrics(m_err, actuals),
        "naive_last_close_baseline": _metrics(n_err, actuals),
        "directional_accuracy_pct": round(dir_hits / dir_total * 100, 2) if dir_total else None,
        "directional_days": dir_total,
        "scaler_range": [round(lo, 4), round(hi, 4)],
        "real_price_range": [min(c for _, c in rows), max(c for _, c in rows)],
        "days_above_scaler_max": sum(1 for _, c in rows if c > hi),
        "points": points,
    }


def lambda_handler(event, context):
    event = event or {}
    symbol = event.get("symbol")
    if not isinstance(symbol, str) or symbol not in SUPPORTED_SYMBOLS:
        return {"statusCode": 400, "symbol": symbol, "error": f"unsupported or missing symbol; model supports {sorted(SUPPORTED_SYMBOLS)}"}
    mode = event.get("mode", "predict")
    if mode == "evaluate":
        return _evaluate(symbol)
    if mode != "predict":
        return {"statusCode": 400, "symbol": symbol, "error": f"unknown mode {mode!r}"}
    return _predict(symbol, event.get("execution_id"))
