# Model evaluation: LSTM vs real AAPL prices

Run on 2026-10-05 with `stock-lstm-inference` in `evaluate` mode (read-only).
Raw output: [`evaluation/AAPL-evaluation-2026-10-05.json`](evaluation/AAPL-evaluation-2026-10-05.json),
also published to `s3://stock-prediction-raw-542601847637-ap-south-1-an/predictions/evaluation/AAPL-latest.json`
and served by `GET /evaluation`.

## What was measured
- **Model:** `models/aapl_lstm_model.tflite` (443,852 bytes, uploaded 2026-09-16) + `models/scaler.pkl`. Unchanged.
- **Target:** next trading day's close. This is inferred from how the model is used (60 closes in, 1 value out). The training code is not in this repo, so it could not be confirmed.
- **Data:** 100 real daily closes from Alpha Vantage `TIME_SERIES_DAILY` (2026-05-12 → 2026-10-02), **unadjusted**.
- **Method:** walk-forward. For every day *t* with 60 earlier real closes, predict close[*t*] from closes[*t*-60 … *t*-1]. That gives **40 out-of-sample predictions** (2026-08-07 → 2026-10-02). No synthetic data was used.
- **Baseline:** naive persistence, "tomorrow's close = today's close".

## Results

| Metric (40 days) | LSTM | Naive baseline |
|---|---|---|
| MAE | **$6.18** | **$3.33** |
| RMSE | $7.03 | $4.23 |
| MAPE | 1.91 % | 1.03 % |
| Mean error (bias) | −$2.44 (under-predicts) | −$0.53 |
| Directional accuracy | 50.0 % (20 of 40) | n/a |

Individual errors ranged from −$12.17 to +$10.71.

## Conclusion
**On this data the LSTM is worse than the naive baseline:** its MAE is about 1.85× higher, and its up/down accuracy (50 %) is no better than a coin flip. On average it predicts $2.44 too low; the gap grew from −$1.69 in the first 20 days to −$3.20 in the last 20. The pipeline runs it correctly end to end, but **its predictions should not be used for decisions.**

## Likely reasons (not proven)
1. **Out-of-range inputs.** The scaler was fitted on 1,674 prices between $54.12 and $339.79. Recent AAPL closes reach $341.07 (2 of 100 days are above the training maximum). Near the top of the range a MinMax-scaled LSTM tends to regress toward values it has seen, which matches the negative bias.
2. **Unknown training data.** Training code and data are not in the repo, so we cannot check for leakage, how the data was split, or whether it used adjusted prices. Alpha Vantage free data is unadjusted.
3. **Single feature.** The model sees only close prices: no volume, no returns, no market context.

## Limitations of this evaluation
- 40 points from one ~2-month period are a small sample from a single market regime. Treat the numbers as indicative, not definitive.
- The free tier's 100-day limit (`outputsize=compact`) prevents a longer backtest. A longer one needs `outputsize=full` (premium or educational verification) or another licensed source.
- Unadjusted prices: a split would create a false jump. None occurred in this window.
- Live predictions (one per trading day, in `stock-predictions`) are scored automatically by `GET /predictions` against the next real close. As of 2026-10-05 none has been scored yet, because the first target day hasn't closed.

## Recommended next steps (not done)
- Retrain on a longer, adjusted, documented dataset with a held-out test period, and re-fit the scaler on it so current prices fall inside its range.
- Predict returns (percentage change) instead of price level so the scale doesn't matter, and keep the naive baseline as the bar to beat.
- Re-run `evaluate` after retraining; only claim improvement if MAE is below the baseline.
