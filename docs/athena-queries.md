# Athena queries (tested 2026-10-22)

Ad-hoc SQL over the archived Alpha Vantage responses. Real data, **unadjusted** prices. Nothing here feeds the pipeline.

## How it is built
- Raw archives (`raw/alphavantage/<SYMBOL>/<date>/*.json`) are pretty-printed nested JSON, which Athena's JSON SerDes cannot read (they need one record per line). `stock-archive-validator` therefore writes one **single-line manifest** per archive under `manifests/alphavantage/…` with the validation result and the parsed daily rows. Athena reads only `manifests/alphavantage/`; `raw/` is never queried or modified.
- Glue database `stock_project` (hand-defined, **no crawler**):
  - table `archive_manifests` — one row per archive: [`infra/athena/01_archive_manifests.sql`](../infra/athena/01_archive_manifests.sql)
  - view `daily_prices` — one row per (symbol, trade_date), taken from the most recent validated archive: [`infra/athena/02_daily_prices_view.sql`](../infra/athena/02_daily_prices_view.sql)
- Workgroup `stock-workgroup`: settings enforced, results in `s3://stock-prediction-raw-542601847637-ap-south-1-an/athena-results/` (SSE-S3), **bytes-scanned cutoff 10 MB per query** (the minimum Athena allows), CloudWatch metrics off.
- Run a query: `python infra/athena/run_query.py "SELECT …"` (profile `stock-project`, `ap-south-1`).
- Cost: $5.00 per TB scanned in ap-south-1 (AWS Price List API, 2026-10-22), billed with a 10 MB minimum per query. The whole dataset is 531,908 bytes (44 manifests), so each query costs about $0.00005.

## Tested queries
All results below are from 2026-10-22 (archives up to the 2026-10-21 close). Each query scanned 531,908 bytes.

### Q1 – days per ticker
```sql
SELECT symbol, count(*) AS days, min(trade_date) AS first, max(trade_date) AS last
FROM daily_prices GROUP BY symbol ORDER BY symbol;
```
| symbol | days | first | last |
|---|---|---|---|
| AAPL | 113 | 2026-05-12 | 2026-10-21 |
| AMZN | 104 | 2026-05-26 | 2026-10-21 |
| GOOGL | 104 | 2026-05-26 | 2026-10-21 |
| MSFT | 104 | 2026-05-26 | 2026-10-21 |
| NVDA | 104 | 2026-05-26 | 2026-10-21 |

### Q2 – daily change % for the last week
```sql
SELECT symbol, trade_date, close,
       round(100 * (close / lag(close) OVER (PARTITION BY symbol ORDER BY trade_date) - 1), 2) AS change_pct
FROM daily_prices WHERE trade_date >= '2026-10-15' ORDER BY symbol, trade_date;
```
Returned 25 rows; e.g. AMZN 2026-10-19 close 262.45, +4.98% (the day the `BIG_MOVE` alert fired), GOOGL 2026-10-21 334.76, −1.62%.

### Q3 – bars revised between archives
```sql
SELECT m.symbol, r.trade_date, count(DISTINCT r.close) AS distinct_closes,
       count(DISTINCT r.volume) AS distinct_volumes, count(*) AS archives
FROM archive_manifests m CROSS JOIN UNNEST(m."rows") AS t(r)
GROUP BY m.symbol, r.trade_date
HAVING count(DISTINCT r.close) > 1 OR count(DISTINCT r.volume) > 1
ORDER BY m.symbol, r.trade_date;
```
28 (symbol, date) pairs were revised, and **every revision changed only the volume** (`distinct_closes` = 1 everywhere). This explains why each scheduled ingest reports `updated 1`: the previous day's volume is finalised a day later.

### Q4 – archive quality
```sql
SELECT status, checks.no_key_or_url AS no_key_or_url, checks.symbol_matches_key AS symbol_ok, count(*) AS archives
FROM archive_manifests GROUP BY 1, 2, 3;
```
| status | no_key_or_url | symbol_ok | archives |
|---|---|---|---|
| ok | true | true | 44 |

### Q5 – cross-check with DynamoDB
```sql
SELECT symbol, count(*) AS n, round(sum(close), 4) AS sum_close FROM daily_prices GROUP BY symbol ORDER BY symbol;
```
Matches the real (`source = alphavantage`) rows in DynamoDB `stock-prices` exactly (checked with a separate boto3 query the same day): AAPL 113 / 35811.5, AMZN 104 / 26279.26, GOOGL 104 / 36496.925, MSFT 104 / 47554.27, NVDA 104 / 22316.56.

## Limits
- Prices are unadjusted (Alpha Vantage free tier). A split would appear as a jump.
- `daily_prices` takes the bar from the archive with the latest key, i.e. the latest ingest.
- The test manifest under `manifests/_test/` is outside the table location and is never read.
- Synthetic rows exist only in DynamoDB and never appear here.
