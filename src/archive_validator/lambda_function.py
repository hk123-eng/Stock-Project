"""stock-archive-validator: S3 ObjectCreated on raw/ -> validation manifest under manifests/.

For each archived Alpha Vantage response it checks that the JSON parses, has "Meta Data" and
"Time Series (Daily)", that the symbol matches the key, that every day has numeric OHLCV, and
that the archive contains no API key and no URL. It then writes ONE single-line JSON manifest to
manifests/<path after raw/>.manifest.json (validation result + the parsed daily rows, so Athena can
query it). It never writes under raw/ and only reports the NAMES of findings, never the matched text.
Direct invocation with {"keys": ["raw/..."]} validates existing archives (backfill).
"""
import datetime as dt
import hashlib
import json
import os
import re
import urllib.parse

import boto3

BUCKET = os.environ.get("RAW_BUCKET", "stock-prediction-raw-542601847637-ap-south-1-an")
IN_PREFIX, OUT_PREFIX = "raw/", "manifests/"
MAX_BYTES = 5 * 1024 * 1024
FORBIDDEN = {  # names only are reported
    "apikey parameter": re.compile(r"api_?key", re.I),
    "URL": re.compile(r"https?://", re.I),
    "alphavantage.co host": re.compile(r"alphavantage\.co", re.I),
}
OHLCV = (("open", "1. open"), ("high", "2. high"), ("low", "3. low"), ("close", "4. close"), ("volume", "5. volume"))
_s3 = None


def _client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def manifest_key(key):
    if not key.startswith(IN_PREFIX):
        raise ValueError("only raw/ objects are validated")
    out = OUT_PREFIX + key[len(IN_PREFIX):] + ".manifest.json"
    assert not out.startswith(IN_PREFIX)
    return out


def _symbol_from_key(key):
    parts = key.split("/")  # raw/alphavantage/<SYMBOL>/<date>/<file>
    return parts[2] if len(parts) >= 5 and parts[1] == "alphavantage" else None


def validate(key, body):
    """Pure validation of one archive. Returns the manifest dict (without S3 metadata)."""
    text = body.decode("utf-8", errors="replace")
    findings = [name for name, rx in FORBIDDEN.items() if rx.search(text)]
    checks = {"no_key_or_url": not findings, "json_parses": False, "has_meta_data": False,
              "has_time_series": False, "symbol_matches_key": None, "rows_numeric": False}
    m = {"source_key": key, "sha256": hashlib.sha256(body).hexdigest(), "size": len(body),
         "findings": findings, "checks": checks, "symbol": None, "last_refreshed": None,
         "n_days": 0, "first_date": None, "last_date": None, "rows": []}
    try:
        d = json.loads(text)
        checks["json_parses"] = isinstance(d, dict)
    except ValueError:
        d = None
    if checks["json_parses"]:
        meta, ts = d.get("Meta Data"), d.get("Time Series (Daily)")
        checks["has_meta_data"] = isinstance(meta, dict)
        checks["has_time_series"] = isinstance(ts, dict) and len(ts) > 0
        if checks["has_meta_data"]:
            m["symbol"], m["last_refreshed"] = meta.get("2. Symbol"), meta.get("3. Last Refreshed")
            ks = _symbol_from_key(key)
            checks["symbol_matches_key"] = None if ks is None else (m["symbol"] == ks)
        if checks["has_time_series"]:
            rows, ok = [], True
            for day in sorted(ts):
                try:
                    r = {"trade_date": day}
                    for col, src in OHLCV:
                        v = float(ts[day][src])
                        r[col] = int(v) if col == "volume" else v
                    rows.append(r)
                except (KeyError, TypeError, ValueError):
                    ok = False
            checks["rows_numeric"] = ok
            m.update(rows=rows, n_days=len(rows), first_date=rows[0]["trade_date"] if rows else None,
                     last_date=rows[-1]["trade_date"] if rows else None)
    m["status"] = "ok" if all(v is not False for v in checks.values()) else "failed"
    return m


def process(key):
    obj = _client().get_object(Bucket=BUCKET, Key=key)
    if obj["ContentLength"] > MAX_BYTES:
        m = {"source_key": key, "size": obj["ContentLength"], "status": "failed", "findings": ["too large"],
             "checks": {}, "rows": []}
    else:
        m = validate(key, obj["Body"].read())
    m.update(schema=1, source_bucket=BUCKET, source_etag=obj.get("ETag", "").strip('"'),
             validated_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    out = manifest_key(key)
    _client().put_object(Bucket=BUCKET, Key=out, Body=(json.dumps(m, sort_keys=True) + "\n").encode("utf-8"),
                         ContentType="application/json", ServerSideEncryption="AES256")
    summary = {"source_key": key, "manifest_key": out, "status": m["status"], "findings": m["findings"],
               "n_days": m.get("n_days", 0)}
    print(json.dumps(summary))
    return summary


def lambda_handler(event, context):
    if "keys" in event:  # direct invocation / backfill
        keys = event["keys"]
    else:
        keys = [urllib.parse.unquote_plus(r["s3"]["object"]["key"]) for r in event.get("Records", [])
                if r.get("eventSource") == "aws:s3" and r["s3"]["bucket"]["name"] == BUCKET]
    results = [process(k) for k in keys if k.startswith(IN_PREFIX)]
    return {"validated": len(results), "failed": sum(r["status"] != "ok" for r in results), "results": results}
