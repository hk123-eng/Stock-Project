-- One row per validated Alpha Vantage archive (written by stock-archive-validator). Hand-defined; no crawler.
CREATE EXTERNAL TABLE IF NOT EXISTS stock_project.archive_manifests (
  source_key string,
  source_etag string,
  sha256 string,
  `size` bigint,
  status string,
  findings array<string>,
  checks struct<json_parses:boolean, has_meta_data:boolean, has_time_series:boolean, no_key_or_url:boolean,
                symbol_matches_key:boolean, rows_numeric:boolean>,
  symbol string,
  last_refreshed string,
  n_days int,
  first_date string,
  last_date string,
  validated_at string,
  `rows` array<struct<trade_date:string, open:double, high:double, low:double, close:double, volume:bigint>>
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://stock-prediction-raw-542601847637-ap-south-1-an/manifests/alphavantage/'
TBLPROPERTIES ('classification'='json', 'comment'='Real Alpha Vantage data, unadjusted. Excludes manifests/_test/.')
