-- One row per (symbol, trade_date): the bar from the most recent validated archive (later archives
-- may carry revised bars). Only manifests with status 'ok'. Real Alpha Vantage data, unadjusted.
CREATE OR REPLACE VIEW stock_project.daily_prices AS
SELECT symbol, trade_date, open, high, low, close, volume, source_key
FROM (
  SELECT m.symbol, r.trade_date, r.open, r.high, r.low, r.close, r.volume, m.source_key,
         row_number() OVER (PARTITION BY m.symbol, r.trade_date ORDER BY m.source_key DESC) AS rn
  FROM stock_project.archive_manifests m
  CROSS JOIN UNNEST(m."rows") AS t(r)
  WHERE m.status = 'ok'
)
WHERE rn = 1
