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

---

# Baseline benchmark (2026-10-22, local only)

Nothing was trained and the deployed model was not touched. The script [`infra/ml/baseline_benchmark.py`](../infra/ml/baseline_benchmark.py) reads the stored real AAPL closes from DynamoDB `stock-prices` (`source = alphavantage`, read-only) and runs four simple baselines walk-forward. It made no Alpha Vantage calls. Raw output, including every per-day prediction: [`evaluation/AAPL-baselines-2026-10-22.json`](evaluation/AAPL-baselines-2026-10-22.json). Unit tests: `tests/test_baseline_benchmark.py` (7), including a no-look-ahead check.

## Setup
- **Data:** 113 real daily closes for AAPL, 2026-05-12 → 2026-10-21, unadjusted, with no gaps longer than a weekend.
- **Method:** for each day *t* with at least 60 earlier closes (the same rule the LSTM backtest used), predict close[*t*] using only closes before *t*. This gives **53 target days, 2026-08-07 → 2026-10-21**.
- **Baselines:**

| Name | Prediction of the next close |
|---|---|
| Naive | today's close |
| 5-day mean | mean of the last 5 closes |
| Drift | today's close + (today's close − first stored close) / (days − 1) |
| AR(5) | today's close × exp(r̂), where r̂ comes from an ordinary-least-squares AR(5) on daily log returns, refit at every step on returns before *t* only |

- **Directional accuracy** counts days where the predicted move and the real move have the same sign. Naive predicts no move, so it has none.

## Results — all 53 target days (2026-08-07 → 2026-10-21)

| Model | n | MAE | RMSE | MAPE | Bias | Direction |
|---|---|---|---|---|---|---|
| Naive | 53 | $3.07 | $3.91 | 0.94 % | −$0.60 | n/a |
| 5-day mean | 53 | $4.19 | $5.17 | 1.29 % | −$1.83 | 47.2 % (25/53) |
| Drift | 53 | **$3.05** | $3.90 | 0.94 % | −$0.24 | 54.7 % (29/53) |
| AR(5) | 53 | $3.27 | $4.07 | 1.01 % | −$0.22 | 56.6 % (30/53) |

## Same 40 days as the LSTM backtest (2026-08-07 → 2026-10-02)
These actual and previous closes match the 2026-10-05 LSTM evaluation file exactly (0 mismatches). The naive MAE reproduces the earlier $3.33.

| Model | n | MAE | RMSE | MAPE | Bias | Direction |
|---|---|---|---|---|---|---|
| LSTM (from the 2026-10-05 evaluation) | 40 | $6.18 | $7.03 | 1.91 % | −$2.44 | 50.0 % |
| Naive | 40 | $3.33 | $4.23 | 1.03 % | −$0.53 | n/a |
| 5-day mean | 40 | $4.65 | $5.65 | 1.44 % | −$1.68 | 47.5 % |
| Drift | 40 | **$3.33** | $4.23 | 1.03 % | −$0.20 | 52.5 % |
| AR(5) | 40 | $3.60 | $4.41 | 1.12 % | −$0.18 | 57.5 % |

## Scored live predictions (actual dates 2026-10-05 → 2026-10-21)
These cover the same days as the 13 live LSTM predictions scored so far in `stock-predictions`, read on 2026-10-22. Each prediction's stored `last_close` matches the stored real close of the day before.

| Model | n | MAE | RMSE | Bias | Direction |
|---|---|---|---|---|---|
| LSTM (live) | 13 | $4.18 | $4.77 | −$3.79 | 53.8 % |
| Naive | 13 | $2.25 | $2.71 | −$0.79 | n/a |
| 5-day mean | 13 | $2.78 | $3.32 | −$2.30 | 46.2 % |
| Drift | 13 | $2.19 | $2.64 | −$0.37 | 61.5 % |
| AR(5) | 13 | $2.26 | $2.75 | −$0.37 | 53.8 % |

## What this shows (and what it does not)
- **The LSTM is the worst model in both comparisons.** On the 40 backtest days its MAE is $6.18, against $3.33–$4.65 for all four baselines. On the 13 live days it is $4.18, against $2.19–$2.78.
- **Naive, drift and AR(5) are practically tied.** Drift's MAE is $0.02 lower than naive's over 53 days ($0.0011 lower over 40). That gap is far too small to call either better.
- **No model shows directional skill.** AR(5) gets the sign right on 30 of 53 days. A fair coin lands this far from 50 % about 41 % of the time (two-sided binomial p = 0.41); for drift (29/53) p = 0.58. The 13 live days are too few to say anything.
- **The bar to beat stays "tomorrow = today".** Any future model has to beat naive, drift and AR(5) on the same walk-forward days, with the larger sample required in [`retraining-plan.md`](retraining-plan.md) (at least 250 predictions plus a 60-day hold-out).

## Limits
- n = 53 (40 and 13 in the subsets), all from one 2½-month period in a single market regime. Treat these numbers as indicative only.
- Prices are unadjusted; no split occurred in the window.
- Drift is anchored to the first stored close (2026-05-12), so a different start date would give a slightly different drift.
- AAPL predictions remain **experimental**. Nothing here changes the deployed model, the scaler or the pipeline.
