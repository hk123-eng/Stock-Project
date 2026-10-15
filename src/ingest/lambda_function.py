"""stock-ingest: fetch real daily prices from Alpha Vantage and store them.

Flow: read API key from SSM (SecureString) -> call TIME_SERIES_DAILY (compact,
latest 100 trading days, UNADJUSTED prices) -> validate -> archive raw JSON to
S3 -> write new/changed rows to DynamoDB `stock-prices` as Numbers.

Security: the API key travels in the request URL (Alpha Vantage requires the
`apikey` query parameter). The URL is never logged, returned or stored, and
errors are re-raised with sanitized messages only.

Coexistence with legacy synthetic rows: every real row carries
source="alphavantage" and data_type="real". Its sort key is the US market close
time in UTC (20:00Z or 21:00Z), which never matches the synthetic rows'
timestamps (00:00Z / 10:19Z / 10:24Z). Writes are additionally conditional so
they can never overwrite a row that is not from Alpha Vantage.
"""
import datetime as dt
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "stock-prices")
RAW_BUCKET = os.environ.get("RAW_BUCKET", "stock-prediction-raw-542601847637-ap-south-1-an")
API_KEY_PARAM = os.environ.get("API_KEY_PARAM", "/stock-project/alphavantage-api-key")
API_BASE = "https://www.alphavantage.co/query"
SOURCE = "alphavantage"
SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")
HTTP_TIMEOUT = 15


class IngestError(Exception):
    """Sanitized ingestion failure (never contains the API key or URL)."""


class RateLimitError(IngestError):
    pass


def us_close_utc(trade_date):
    """16:00 America/New_York on trade_date, as an ISO-8601 UTC string.

    US DST (since 2007): second Sunday of March to first Sunday of November.
    The 2 a.m. switch is before 16:00, so the switch dates follow the new rule.
    """
    y = trade_date.year
    march1 = dt.date(y, 3, 1)
    dst_start = march1 + dt.timedelta(days=(6 - march1.weekday()) % 7 + 7)
    nov1 = dt.date(y, 11, 1)
    dst_end = nov1 + dt.timedelta(days=(6 - nov1.weekday()) % 7)
    hour = 20 if dst_start <= trade_date < dst_end else 21
    return f"{trade_date.isoformat()}T{hour:02d}:00:00Z"


def _dec(value, field, day):
    try:
        d = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        raise IngestError(f"non-numeric {field} on {day}") from None
    if not d.is_finite() or d < 0:
        raise IngestError(f"invalid {field} on {day}")
    return d


def parse_daily(payload, symbol):
    """Validate a TIME_SERIES_DAILY response and return normalized rows (oldest first)."""
    if not isinstance(payload, dict):
        raise IngestError("response is not a JSON object")
    for k in ("Note", "Information"):
        if k in payload and "Time Series (Daily)" not in payload:
            # Free tier: 25 requests/day. The message text is safe (no key in it).
            raise RateLimitError(f"Alpha Vantage {k}: {str(payload[k])[:200]}")
    if "Error Message" in payload:
        raise IngestError(f"Alpha Vantage error: {str(payload['Error Message'])[:200]}")
    meta = payload.get("Meta Data") or {}
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        raise IngestError("response has no 'Time Series (Daily)'")
    got_symbol = str(meta.get("2. Symbol", "")).upper()
    if got_symbol and got_symbol != symbol:
        raise IngestError(f"symbol mismatch: asked {symbol}, got {got_symbol}")

    rows = []
    for day, v in series.items():
        try:
            d = dt.date.fromisoformat(day)
        except ValueError:
            raise IngestError(f"bad date key {day!r}") from None
        o = _dec(v.get("1. open"), "open", day)
        h = _dec(v.get("2. high"), "high", day)
        lo = _dec(v.get("3. low"), "low", day)
        c = _dec(v.get("4. close"), "close", day)
        vol = _dec(v.get("5. volume"), "volume", day)
        if c <= 0 or not (lo <= min(o, c) and max(o, c) <= h):
            raise IngestError(f"inconsistent OHLC on {day}")
        rows.append({
            "symbol": symbol,
            "timestamp": us_close_utc(d),
            "trade_date": day,
            "open": o, "high": h, "low": lo, "close": c,
            "volume": int(vol),
            "source": SOURCE,
            "data_type": "real",
            "adjusted": False,
        })
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def _fetch(symbol, api_key):
    query = urllib.parse.urlencode({
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": "compact",
        "datatype": "json",
        "apikey": api_key,
    })
    req = urllib.request.Request(f"{API_BASE}?{query}", headers={"User-Agent": "stock-ingest/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise IngestError(f"Alpha Vantage HTTP {e.code}") from None
    except Exception as e:  # URLError, timeout, TLS: report the type only
        raise IngestError(f"Alpha Vantage request failed ({type(e).__name__})") from None
    try:
        text = body.decode("utf-8")
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise IngestError("Alpha Vantage returned non-JSON") from None
    if api_key in text:
        raise IngestError("response unexpectedly contains the API key; not stored")
    return payload, text


def _existing_real_rows(table, symbol):
    rows, kwargs = {}, {
        "KeyConditionExpression": Key("symbol").eq(symbol),
        "FilterExpression": Attr("source").eq(SOURCE),
    }
    while True:
        resp = table.query(**kwargs)
        for i in resp.get("Items", []):
            rows[i["timestamp"]] = i
        if "LastEvaluatedKey" not in resp:
            return rows
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _same(new, old):
    fields = ("open", "high", "low", "close", "volume")
    return old is not None and all(Decimal(str(old.get(f))) == Decimal(str(new[f])) for f in fields)


def lambda_handler(event, context):
    symbol = (event or {}).get("symbol")
    if not isinstance(symbol, str) or not SYMBOL_RE.match(symbol):
        raise IngestError("invalid or missing 'symbol' (expected 1-5 uppercase letters)")

    api_key = boto3.client("ssm").get_parameter(Name=API_KEY_PARAM, WithDecryption=True)["Parameter"]["Value"]
    payload, raw_text = _fetch(symbol, api_key)
    del api_key
    rows = parse_daily(payload, symbol)

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    now_iso = now.isoformat().replace("+00:00", "Z")
    latest = rows[-1]["trade_date"]
    raw_key = f"raw/alphavantage/{symbol}/{latest}/TIME_SERIES_DAILY_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    boto3.client("s3").put_object(
        Bucket=RAW_BUCKET, Key=raw_key, Body=raw_text.encode("utf-8"),
        ContentType="application/json", ServerSideEncryption="AES256",
    )

    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    existing = _existing_real_rows(table, symbol)
    inserted = updated = unchanged = 0
    for r in rows:
        old = existing.get(r["timestamp"])
        if _same(r, old):
            unchanged += 1
            continue
        item = dict(r, ingested_at=now_iso, raw_s3_key=raw_key)
        try:
            table.put_item(
                Item=item,
                # Never overwrite a row that did not come from Alpha Vantage.
                ConditionExpression="attribute_not_exists(#ts) OR #src = :src",
                ExpressionAttributeNames={"#ts": "timestamp", "#src": "source"},
                ExpressionAttributeValues={":src": SOURCE},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise IngestError(f"refused to overwrite non-Alpha-Vantage row {r['timestamp']}") from None
            raise
        if old is None:
            inserted += 1
        else:
            updated += 1

    result = {
        "statusCode": 200,
        "symbol": symbol,
        "source": SOURCE,
        "rows_received": len(rows),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "first_trade_date": rows[0]["trade_date"],
        "latest_trade_date": latest,
        "latest_close": float(rows[-1]["close"]),
        "raw_s3_key": raw_key,
    }
    print(json.dumps(result))
    return result
