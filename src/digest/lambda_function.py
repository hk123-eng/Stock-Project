"""stock-alert-digest: one combined email per pipeline run.

Input (from the Step Functions Map): {"tickers": [<per-ticker result>], "execution_id": ...}
Each per-ticker result is {"symbol", "ok", "failed_step"?, "error"?, "ingest", "prediction", "signals", "score"}
where the nested objects are the Lambda results (or {} when the step did not run).

Output: {"statusCode": 200, "send": bool, "subject", "message", counts...}. The state machine
publishes subject/message to SNS only when send is true (new alerts, new data-quality
warnings or failed tickers). Alerts arrive already deduplicated per
(symbol, trade_date, type) by stock-signals.

Also publishes StockProject/Pipeline metrics TickersProcessed and TickerFailures
(best effort: a metrics error never blocks the email).
"""
import json
import os

import boto3

MODEL_SYMBOLS = {s.strip() for s in os.environ.get("MODEL_SYMBOLS", "AAPL").split(",") if s.strip()}
METRIC_NAMESPACE = "StockProject/Pipeline"
SUBJECT_MAX = 100  # SNS email subject limit


def _err_text(err):
    """Readable, bounded error text from a Step Functions error object or a Lambda result."""
    if isinstance(err, str):
        try:
            err = json.loads(err)
        except ValueError:
            return err[:300]
    if isinstance(err, dict):
        cause = err.get("Cause")
        if isinstance(cause, str):
            try:
                c = json.loads(cause)
                if isinstance(c, dict) and "errorMessage" in c:
                    return f"{c.get('errorType', err.get('Error', 'Error'))}: {c['errorMessage']}"[:300]
            except ValueError:
                pass
            return f"{err.get('Error', 'Error')}: {cause}"[:300]
        if "error" in err:
            return str(err["error"])[:300]
    return json.dumps(err, default=str)[:300]


def _obj(t, key):
    v = t.get(key)
    return v if isinstance(v, dict) else {}


def build_digest(tickers, execution_id="manual"):
    tickers = [t for t in (tickers or []) if isinstance(t, dict)]
    alerts, warnings, failures, ok, notes = [], [], [], [], []
    trade_dates = set()
    for t in tickers:
        sym = str(t.get("symbol", "?"))
        sig, ing, pred = _obj(t, "signals"), _obj(t, "ingest"), _obj(t, "prediction")
        for a in sig.get("alerts") or []:
            if isinstance(a, dict):
                alerts.append((sym, sig.get("trade_date"), a.get("type"), a.get("detail")))
        if sig.get("trade_date"):
            trade_dates.add(sig["trade_date"])
        dq = ing.get("data_quality") if isinstance(ing.get("data_quality"), dict) else {}
        for j in dq.get("jumps") or []:
            if isinstance(j, dict) and j.get("new"):
                hint = f" ({j['split_hint']})" if j.get("split_hint") else ""
                warnings.append(f"{sym}: close {j.get('prev_close')} on {j.get('prev_trade_date')} -> {j.get('close')} "
                                f"on {j.get('trade_date')} ({j.get('change_pct')}%){hint}. Prices are unadjusted; check for a split.")
        if t.get("ok") is True:
            ok.append(sym)
            if sym in MODEL_SYMBOLS and pred.get("statusCode") != 200:
                notes.append(f"{sym}: model prediction skipped (suspicious price jump in new data).")
        else:
            failures.append(f"{sym}: failed at {t.get('failed_step', 'unknown step')}: {_err_text(t.get('error'))}")

    lines = [f"Stock watchlist run: {len(ok)} of {len(tickers)} tickers OK"
             + (f", trading day {', '.join(sorted(trade_dates))}" if trade_dates else "") + ".", ""]
    if alerts:
        lines.append(f"New alerts ({len(alerts)}):")
        lines += [f"- {s} {d}: {ty}: {de}" for s, d, ty, de in alerts]
        lines.append("")
    if warnings:
        lines.append("Data-quality warnings:")
        lines += [f"- {w}" for w in warnings]
        lines.append("")
    if failures:
        lines.append(f"FAILED tickers ({len(failures)} of {len(tickers)}); the other tickers were processed:")
        lines += [f"- {f}" for f in failures]
        lines.append("")
    if notes:
        lines += [f"- {n}" for n in notes] + [""]
    lines += [f"Execution: {execution_id}",
              "Data: real Alpha Vantage daily prices, unadjusted. Signals are rule-based.",
              f"Model predictions exist only for {', '.join(sorted(MODEL_SYMBOLS))} and are experimental "
              "(the LSTM does not beat a naive baseline). Other tickers: prices and signals only.",
              "Not financial advice. College project."]

    parts = []
    if failures:
        parts.append(f"{len(failures)} FAILED")
    if alerts:
        by_sym = {}
        for s, _, ty, _ in alerts:
            by_sym.setdefault(s, []).append(ty)
        parts.append("; ".join(f"{s} {'/'.join(sorted(set(v)))}" for s, v in by_sym.items()))
    if warnings:
        parts.append("data-quality warning")
    subject = "Stock watchlist: " + (" | ".join(parts) if parts else "no news")
    if len(subject) > SUBJECT_MAX:
        subject = subject[:SUBJECT_MAX - 3] + "..."
    return {"statusCode": 200, "send": bool(alerts or warnings or failures), "subject": subject,
            "message": "\n".join(lines), "tickers": len(tickers), "ok": len(ok), "failed": len(failures),
            "alerts": len(alerts), "warnings": len(warnings)}


def _put_metrics(d):
    try:
        boto3.client("cloudwatch").put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=[
            {"MetricName": "TickersProcessed", "Value": d["ok"], "Unit": "Count"},
            {"MetricName": "TickerFailures", "Value": d["failed"], "Unit": "Count"},
        ])
        return None
    except Exception as e:  # best effort only
        return type(e).__name__


def lambda_handler(event, context):
    event = event or {}
    d = build_digest(event.get("tickers"), str(event.get("execution_id", "manual")))
    err = _put_metrics(d)
    if err:
        d["metrics_error"] = err
    print(json.dumps({k: d[k] for k in ("send", "tickers", "ok", "failed", "alerts", "warnings")}))
    return d
