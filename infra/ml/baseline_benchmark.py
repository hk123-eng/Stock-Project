"""Local walk-forward benchmark of simple baselines on stored real AAPL closes.

No training of the LSTM, no model replacement, no AWS writes. Reads the real
(source = alphavantage) rows from DynamoDB `stock-prices` (read-only), or a
local JSON file of [trade_date, close] pairs with --input.

For every day t with at least MIN_HISTORY earlier real closes, each baseline
predicts close[t] from closes[0 .. t-1] only:
  naive  close[t-1]
  mean5  mean of the last 5 closes
  drift  close[t-1] + (close[t-1] - close[0]) / (t - 1)   (random walk with drift)
  ar5    close[t-1] * exp(r_hat); r_hat from an OLS AR(5) on log returns,
         refit on every step using only returns up to t-1

Usage:
  python infra/ml/baseline_benchmark.py [--symbol AAPL] [--input rows.json]
         [--lstm docs/evaluation/AAPL-evaluation-2026-10-05.json] [--out result.json]
"""
import argparse
import json
import math
import sys

MIN_HISTORY = 60   # same window the LSTM backtest needed, so the target days line up
AR_LAGS = 5
MODELS = ("naive", "mean5", "drift", "ar5")


def solve(a, b):
    """Solve a x = b (small dense system) by Gaussian elimination with partial pivoting."""
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-18:
            raise ValueError("singular system")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_ar(returns, lags=AR_LAGS):
    """OLS coefficients [const, b1..b_lags] for r[i] = const + sum b_k r[i-k]."""
    xs, ys = [], []
    for i in range(lags, len(returns)):
        xs.append([1.0] + [returns[i - k] for k in range(1, lags + 1)])
        ys.append(returns[i])
    if len(ys) <= lags + 1:
        raise ValueError("not enough returns for AR fit")
    p = lags + 1
    xtx = [[sum(x[i] * x[j] for x in xs) for j in range(p)] for i in range(p)]
    xty = [sum(x[i] * y for x, y in zip(xs, ys)) for i in range(p)]
    return solve(xtx, xty)


def predict(closes, model):
    """Prediction of the next close from the history `closes` (oldest first)."""
    last = closes[-1]
    if model == "naive":
        return last
    if model == "mean5":
        return sum(closes[-5:]) / len(closes[-5:])
    if model == "drift":
        return last + (last - closes[0]) / (len(closes) - 1)
    if model == "ar5":
        r = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
        coef = fit_ar(r)
        r_hat = coef[0] + sum(coef[k] * r[-k] for k in range(1, AR_LAGS + 1))
        return last * math.exp(r_hat)
    raise ValueError(model)


def walk_forward(rows, min_history=MIN_HISTORY):
    """rows: [(trade_date, close)] sorted oldest first -> list of per-day points."""
    closes = [c for _, c in rows]
    points = []
    for t in range(min_history, len(rows)):
        hist = closes[:t]
        p = {"date": rows[t][0], "actual": closes[t], "previous_close": closes[t - 1]}
        for m in MODELS:
            p[m] = round(predict(hist, m), 4)
        points.append(p)
    return points


def metrics(points, key):
    errs = [p[key] - p["actual"] for p in points]
    n = len(errs)
    out = {
        "n": n,
        "mae": sum(abs(e) for e in errs) / n,
        "rmse": math.sqrt(sum(e * e for e in errs) / n),
        "mape_pct": sum(abs(e) / p["actual"] for e, p in zip(errs, points)) / n * 100,
        "bias": sum(errs) / n,
    }
    hits = days = 0
    for p in points:
        pred_move = p[key] - p["previous_close"]
        real_move = p["actual"] - p["previous_close"]
        if pred_move == 0 or real_move == 0:
            continue   # no direction predicted (naive) or no move
        days += 1
        hits += (pred_move > 0) == (real_move > 0)
    out["directional_days"] = days
    out["directional_accuracy_pct"] = (hits / days * 100) if days else None
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def summary(points, keys):
    return {k: metrics(points, k) for k in keys}


def _real_rows_dynamodb(symbol):
    import boto3
    from boto3.dynamodb.conditions import Attr, Key
    table = boto3.Session(profile_name="stock-project", region_name="ap-south-1") \
        .resource("dynamodb").Table("stock-prices")
    kwargs = {"KeyConditionExpression": Key("symbol").eq(symbol),
              "FilterExpression": Attr("source").eq("alphavantage")}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    items.sort(key=lambda i: i["trade_date"])
    return [(i["trade_date"], float(i["close"])) for i in items]


def _scored_predictions(symbol):
    import boto3
    from boto3.dynamodb.conditions import Key
    table = boto3.Session(profile_name="stock-project", region_name="ap-south-1") \
        .resource("dynamodb").Table("stock-predictions")
    items = table.query(KeyConditionExpression=Key("symbol").eq(symbol))["Items"]
    return [{"actual_date": i["actual_date"], "last_close": float(i["last_close"]),
             "predicted_close": float(i["predicted_close"])} for i in items if "scored_at" in i]


def live_comparison(rows, scored):
    """Baselines on the same target days as the scored live LSTM predictions."""
    idx = {d: i for i, (d, _) in enumerate(rows)}
    closes = [c for _, c in rows]
    pts = []
    for s in sorted(scored, key=lambda s: s["actual_date"]):
        t = idx[s["actual_date"]]
        if abs(s["last_close"] - closes[t - 1]) > 1e-6:
            raise ValueError(f"last_close mismatch on {s['actual_date']}")
        p = {"date": s["actual_date"], "actual": closes[t], "previous_close": closes[t - 1],
             "lstm": s["predicted_close"]}
        for m in MODELS:
            p[m] = round(predict(closes[:t], m), 4)
        pts.append(p)
    return {"days": len(pts),
            "first_target_date": pts[0]["date"] if pts else None,
            "last_target_date": pts[-1]["date"] if pts else None,
            "metrics": summary(pts, ("lstm",) + MODELS) if pts else {}}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--input")
    ap.add_argument("--lstm", help="LSTM walk-forward evaluation JSON to compare on the same days")
    ap.add_argument("--live", action="store_true",
                    help="also compare scored live LSTM predictions from stock-predictions (read-only)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)

    rows = [tuple(r) for r in json.load(open(a.input))] if a.input else _real_rows_dynamodb(a.symbol)
    dates = [d for d, _ in rows]
    if dates != sorted(set(dates)):
        sys.exit("rows must be unique trade dates")
    points = walk_forward(rows)
    result = {
        "symbol": a.symbol,
        "data": {"source": "alphavantage TIME_SERIES_DAILY, unadjusted", "days": len(rows),
                 "first": dates[0], "last": dates[-1]},
        "method": f"walk-forward, predict close[t] from closes before t; t needs >= {MIN_HISTORY} earlier closes",
        "first_target_date": points[0]["date"], "last_target_date": points[-1]["date"],
        "all_days": summary(points, MODELS),
    }

    if a.lstm:
        lstm = json.load(open(a.lstm))
        by_date = {p["date"]: p for p in points}
        common, mismatched = [], []
        for lp in lstm["points"]:
            bp = by_date.get(lp["date"])
            if bp is None:
                continue
            if abs(bp["actual"] - lp["actual"]) > 1e-6 or abs(bp["previous_close"] - lp["previous_close"]) > 1e-6:
                mismatched.append(lp["date"])
            common.append({**bp, "lstm": lp["predicted"]})
        result["lstm_overlap"] = {
            "source": a.lstm, "days": len(common), "actuals_mismatched": mismatched,
            "first_target_date": common[0]["date"] if common else None,
            "last_target_date": common[-1]["date"] if common else None,
            "metrics": summary(common, ("lstm",) + MODELS),
        }

    if a.live:
        result["live_scored"] = live_comparison(rows, _scored_predictions(a.symbol))

    result["points"] = points
    text = json.dumps(result, indent=2)
    if a.out:
        with open(a.out, "w", newline="\n") as f:
            f.write(text + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "points"}, indent=2))


if __name__ == "__main__":
    main()
