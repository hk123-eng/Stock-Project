# Retraining plan (document only — nothing has been trained or replaced)

_Written 2026-10-15 (Phase 8 item 4). Status: **plan**. The deployed AAPL LSTM (`models/aapl_lstm_model.tflite`
+ scaler) is unchanged. It stays labelled "experimental, does not beat baseline"._

## 1. Why retrain at all
Measured so far, always against the naive "tomorrow's close = today's close" baseline:

| Source | n | LSTM MAE | Naive MAE | Notes |
|---|---|---|---|---|
| Walk-forward backtest, 2026-08-07 → 2026-10-02 (`docs/model-evaluation.md`) | 40 | $6.18 | $3.33 | directional accuracy 50% |
| Live scored predictions, actual dates 2026-10-05 → 2026-10-14 (`stock-predictions`, read 2026-10-15) | 8 | $4.40 | $2.30 | below the 20-day minimum, so no live verdict is claimed |

The current model does not beat the naive baseline on either measurement. Training code and training data for it
are not available, so it cannot be reproduced; any new model must be built from scratch with the process below.

## 2. Target and features
- **Target: next-day log return** `r(t+1) = ln(close(t+1) / close(t))`, not the price level. A return target does not
  depend on where the price sits relative to a fitted scaler, and the naive baseline becomes "predict 0".
  Price forecasts for the dashboard are derived as `close(t) * exp(r̂)`.
- **Inputs:** the previous 60 daily log returns (same window length as today), optionally plus volume change and the
  existing signals (RSI14, MACD histogram, %B) — each one added only if it improves walk-forward MAE.
- **Scaling:** fit on the training fold only (never on validation/test data). Standardise returns (mean/σ) instead of
  MinMax over prices, so new highs never push inputs outside the fitted range.

## 3. Validation: expanding-window walk-forward
1. Sort by trade date. Never shuffle.
2. Folds: train on all data up to day T, predict T+1 … T+20, move T forward by 20 trading days, repeat.
3. Hold out the **final 60 trading days** completely; they are evaluated once, after all model choices are frozen.
4. Minimum evaluation window for any promotion decision: **≥ 250 walk-forward predictions** (≈ 1 trading year)
   plus the 60-day hold-out. (The current backtest has 40 points because the free feed returns only 100 days.)
5. Report per fold and overall: MAE and RMSE of the price derived from the return, MAPE, bias (mean error), and
   directional accuracy, each with its n.

## 4. Baselines (every fold, same days)
| Baseline | Prediction of next close |
|---|---|
| Naive | today's close (return 0) |
| Drift / 5-day mean | today's close × exp(mean of the last 5 daily log returns) |
| AR(5) | linear autoregression on the last 5 log returns, refit on each training fold (ordinary least squares) |

The LSTM is only interesting if it beats **all three**; AR(5) shows whether a deep model adds anything over a
linear one.

## 5. Promotion rule (all must hold; a human approves)
1. Walk-forward MAE **below the naive MAE** over the full walk-forward window (≥ 250 predictions) **and** on the
   60-day hold-out.
2. Also below the drift and AR(5) MAE on the hold-out.
3. **Directional accuracy meaningfully above 50%**: the lower bound of a 95% binomial (Wilson) confidence interval
   must be above 50% over the walk-forward window. Example: with n = 250 that needs roughly 57% or more correct
   (a raw 52% over 250 days is indistinguishable from a coin flip).
4. No inputs outside the training distribution on the hold-out (logged per prediction, as today).
5. The project owner approves in writing. Promotion is a change to `models/registry.json` only — the old version
   stays in S3 for rollback.

## 6. S3 model versioning layout
```
s3://stock-prediction-raw-542601847637-ap-south-1-an/models/
  aapl_lstm_model.tflite, …            existing files, untouched (= "v0")
  registry.json                        {"AAPL": {"active": "v0", "history": [...]}}
  AAPL/<version>/model.tflite
  AAPL/<version>/scaler.json           mean/σ (or other parameters) as JSON, not pickle
  AAPL/<version>/metadata.json         data source + terms reference, date range, adjusted or not,
                                       target definition, feature list, code git hash,
                                       walk-forward + hold-out metrics with n, all baseline metrics,
                                       approval (who, when)
```
The inference Lambda would read `registry.json` to choose the version (a code change that needs its own approval;
`stock-lstm-inference` is not modified in this phase). Permission needed only at promotion time:
`s3:PutObject` on `arn:aws:s3:::stock-prediction-raw-542601847637-ap-south-1-an/models/*` — not granted today.

## 7. Train/serve mismatch: adjusted training data vs unadjusted live feed
The live feed is `TIME_SERIES_DAILY` (unadjusted; `adjusted=false` on every row). Adjusted history
(`TIME_SERIES_DAILY_ADJUSTED`) is a premium function. If a model is trained on adjusted prices and served unadjusted
prices, the two series diverge at every split and (slightly) at every dividend.

| Option | How | Failure on a split day |
|---|---|---|
| A. Serve adjusted inputs | apply split factors from a corporate-actions source to the 60-day input window before inference | needs a reliable split feed on the same day; if it is late, the window contains a fake −50%/−75% "crash" |
| B. Train on unadjusted data | train on the same unadjusted series the feed delivers | the model sees splits as real crashes; training data must be cleaned of them anyway, so this reduces to A |
| C. Predict returns (recommended) | inputs and target are daily returns | only the one return that spans the split is wrong; the Phase 8 ingest check already flags any ≥ 25% day-over-day jump and the pipeline **skips the prediction** for that ticker, so the bad return is never used silently. Dividends (~0.1–0.3%) are small next to daily noise |

Recommendation: option C plus the existing jump check; replace a flagged return by a split-corrected one only after
a human confirms the split.

## 8. Is the scaler range part of the problem? (hypothesis only)
The deployed scaler is MinMax over 1,674 prices with maximum **$339.7869**. Measured on 2026-10-15 from the 108 real
AAPL rows (2026-05-12 → 2026-10-14):

| Window | Above the max | Within 1% of the max or above | Within 5% or above |
|---|---|---|---|
| All 108 days | 6 | 15 | 39 |
| Last 60 days (the model's input window) | 6 | 15 | 34 |
| Last 20 days | 5 | 12 | 20 |

All 8 live scored predictions were made with inputs flagged outside the scaler range.

Exploratory split of the 40 walk-forward predictions by the last input close:

| Last close | n | LSTM MAE | LSTM bias | Naive MAE |
|---|---|---|---|---|
| ≥ 95% of the scaler max | 19 | $6.69 | −$4.67 | $3.18 |
| < 95% of the scaler max | 21 | $5.72 | −$0.43 | $3.47 |

Live scored days (all near the max, n = 8): LSTM MAE $4.40, bias −$3.80; naive $2.30.

**Hypothesis (not established):** when inputs approach or exceed the top of the MinMax range, the network's outputs
saturate and it under-predicts, which would explain the negative bias. The numbers above are consistent with that,
but the samples are small, the two groups are also different calendar periods (so market regime is confounded), and
the model underperforms naive in **both** groups — so the scaler range cannot be the whole explanation. A proper
test: on the new walk-forward (≥ 250 points), compare bias and MAE for inputs inside vs near/above the training range,
with n and a confidence interval for each group. Using a return target (§2) removes this failure mode by design.

## 9. Training data sources and terms
| Source | What it gives | Terms (checked 2026-10-15) | Verdict |
|---|---|---|---|
| Alpha Vantage free key (current) | `TIME_SERIES_DAILY` compact = latest 100 days, unadjusted; 25 requests/day | Licence is for "personal, non-commercial use"; use "as or on behalf of a corporation, firm, partnership, trust or any other association and not as an individual" counts as commercial (contact premium@alphavantage.co). Documentation: "The 'full' outputsize is available to premium keys"; `TIME_SERIES_DAILY_ADJUSTED` "is a premium API function". | Fine for the live feed of an individual project; too short for training |
| Alpha Vantage premium | full history ("25+ years" per the docs), adjusted series with split/dividend events | Cheapest plan listed on alphavantage.co/premium: $49.99/month (75 requests/min) | Only if the owner chooses to pay; a team project should first ask Alpha Vantage about educational use (open item in TODO) |
| The project's own accumulated data | the daily rows this pipeline stores (now 5 tickers) | covered by the same Alpha Vantage licence | Licence-clean but slow: ≈ 250 rows per ticker per year; ≥ 250 walk-forward points need over a year of collection |
| Twelve Data free plan | — | "internal non-display" use only | Rejected 2026-10-04 |
| Tiingo free plan | — | no persistent storage | Rejected 2026-10-04 |
| Yahoo Finance via `yfinance` | long adjusted history | The yfinance README states it is "not affiliated, endorsed, or vetted by Yahoo" and "the Yahoo! finance API is intended for personal use only"; it is an unofficial scraper | **Not recommended** |

Any other source's terms must be fetched and quoted before it is proposed.

## 10. Where and how training would run
- Locally on a laptop CPU (a 60-step, 1–2 layer LSTM trains in minutes), exported to TFLite with the same
  `tflite-runtime` constraints as today. No SageMaker, no GPU, no AWS cost.
- Reproducible script + pinned requirements + fixed random seeds, committed to git with the data snapshot's S3 key.
- Cost: $0 now; a few MB of S3 per version (< $0.01/month) after promotion, plus any data plan the owner chooses.

## 11. Steps, in order (each needs the owner's go-ahead)
1. Decide the data source (§9) — owner.
2. Build the walk-forward harness and the three baselines; publish baseline numbers first.
3. Train the return-target LSTM; evaluate with §3/§5. If it fails the promotion rule, record the result and stop.
4. If it passes: owner approves, grant `s3:PutObject` on `models/*`, upload under a new version, update
   `registry.json`, change inference to read the registry (separate reviewed change), keep v0 for rollback.
