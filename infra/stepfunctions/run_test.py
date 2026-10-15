"""Start a labelled test execution of stock-prediction-pipeline, wait for it, print a per-ticker summary.

Usage: python infra/stepfunctions/run_test.py <name-suffix> '<json input>'
Uses AWS profile stock-project in ap-south-1. Refuses to run inside the protected windows (infra/time_guard.py).
"""
import json
import pathlib
import subprocess
import sys
import time

import boto3

ROOT = pathlib.Path(__file__).resolve().parents[2]
SM = "arn:aws:states:ap-south-1:542601847637:stateMachine:stock-prediction-pipeline"


def main():
    suffix, payload = sys.argv[1], sys.argv[2]
    json.loads(payload)
    if subprocess.run([sys.executable, str(ROOT / "infra" / "time_guard.py")]).returncode:
        sys.exit("refusing: protected time window")
    sfn = boto3.Session(profile_name="stock-project", region_name="ap-south-1").client("stepfunctions")
    name = f"test-{suffix}-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}"
    arn = sfn.start_execution(stateMachineArn=SM, name=name, input=payload)["executionArn"]
    print("started", name, flush=True)
    while True:
        d = sfn.describe_execution(executionArn=arn)
        if d["status"] != "RUNNING":
            break
        time.sleep(10)
    print("status", d["status"], "duration_s", round((d["stopDate"] - d["startDate"]).total_seconds()))
    out = json.loads(d.get("output") or "{}")
    for t in out.get("tickers", []):
        ing, pred, sig, sc = (t.get(k) or {} for k in ("ingest", "prediction", "signals", "score"))
        dq = ing.get("data_quality") or {}
        print(json.dumps({
            "symbol": t.get("symbol"), "ok": t.get("ok"), "failed_step": t.get("failed_step"),
            "error": (t.get("error") or "")[:200] or None,
            "ingest": {k: ing.get(k) for k in ("inserted", "updated", "unchanged", "first_trade_date", "latest_trade_date")},
            "jumps_in_window": dq.get("jumps_in_window"), "new_jumps": dq.get("new_jumps_count"),
            "prediction": pred.get("prediction"), "as_of": pred.get("as_of_date"),
            "signals_date": sig.get("trade_date"), "new_alerts": [a.get("type") for a in sig.get("alerts") or []],
            "already_sent": sig.get("already_sent"), "score": {k: sc.get(k) for k in ("newly_scored", "already_scored", "pending")} if sc else None,
        }))
    dg = (out.get("digest") or {}).get("result") or {}
    print("digest", json.dumps({k: dg.get(k) for k in ("send", "subject", "tickers", "ok", "failed", "alerts", "warnings")}))
    print("email published:", "digestPublish" in out)
    if d["status"] != "SUCCEEDED":
        print("error", d.get("error"), (d.get("cause") or "")[:500])
    pathlib.Path(ROOT / "build" / f"{name}.json").write_text(json.dumps(out, indent=1, default=str))
    sys.exit(0 if d["status"] == "SUCCEEDED" else 1)


if __name__ == "__main__":
    main()
