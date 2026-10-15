"""Generates infra/stepfunctions/stock-prediction-pipeline.asl.json.

Design rules (from the audit):
- Validate input first with Choice rules that cannot raise States.Runtime
  (IsPresent/IsString before any comparison); invalid input -> failure alert.
- Every Lambda result is wrapped with ResultSelector {"result.$": "$.Payload"}
  (always present) so a missing field can never cause a JSONPath runtime error;
  later Choices check IsPresent before comparing.
- Every Task catches States.ALL into $.error and goes to PublishFailure.
- Anything that still escapes (States.Runtime, timeouts, aborts) is covered by
  the CloudWatch alarm `stock-pipeline-failed-executions` -> SNS.
"""
import json
import os

ACCOUNT = "542601847637"
REGION = "ap-south-1"
TOPIC = f"arn:aws:sns:{REGION}:{ACCOUNT}:stock-prediction-alerts"
FN = lambda name: f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:{name}"  # noqa: E731
SUPPORTED_SYMBOLS = ["AAPL"]

LAMBDA_RETRY = {
    "ErrorEquals": ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                    "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
    "IntervalSeconds": 5, "MaxAttempts": 2, "BackoffRate": 2,
}
CATCH_ALL = [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "PublishFailure"}]


def lambda_task(fn, payload, result_path, nxt, extra_retry=None, timeout=120):
    return {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {"FunctionName": FN(fn), "Payload": payload},
        "ResultSelector": {"result.$": "$.Payload"},
        "ResultPath": result_path,
        "TimeoutSeconds": timeout,
        "Retry": [LAMBDA_RETRY] + (extra_retry or []),
        "Catch": CATCH_ALL,
        "Next": nxt,
    }


def status_ok(path, ok_next, fail_state):
    return {
        "Type": "Choice",
        "Choices": [{
            "And": [
                {"Variable": f"{path}.statusCode", "IsPresent": True},
                {"Variable": f"{path}.statusCode", "IsNumeric": True},
                {"Variable": f"{path}.statusCode", "NumericEquals": 200},
            ],
            "Next": ok_next,
        }],
        "Default": fail_state,
    }


def fail_pass(error_name, cause_path):
    return {
        "Type": "Pass",
        "Parameters": {
            "symbol.$": "$.symbol",
            "error": {"Error": error_name, "Cause.$": f"States.JsonToString({cause_path})"},
        },
        "Next": "PublishFailure",
    }


def build(with_signals):
    states = {
        "ValidateInput": {
            "Type": "Choice",
            "Choices": [{
                "And": [
                    {"Variable": "$.symbol", "IsPresent": True},
                    {"Variable": "$.symbol", "IsString": True},
                    {"Or": [{"Variable": "$.symbol", "StringEquals": s} for s in SUPPORTED_SYMBOLS]},
                ],
                "Next": "IngestPrices",
            }],
            "Default": "InvalidInput",
        },
        "InvalidInput": {
            "Type": "Pass",
            # Builds a fresh object, so it works for any JSON input (even non-objects).
            "Parameters": {
                "symbol": "INVALID",
                "error": {"Error": "InvalidInput",
                          "Cause.$": "States.Format('Expected input with symbol = one of " + "/".join(SUPPORTED_SYMBOLS) + ". Got: {}', States.JsonToString($))"},
            },
            "Next": "PublishFailure",
        },
        "IngestPrices": lambda_task(
            "stock-ingest", {"symbol.$": "$.symbol"}, "$.ingest", "CheckIngest",
            extra_retry=[{"ErrorEquals": ["IngestError"], "IntervalSeconds": 60, "MaxAttempts": 1}],
        ),
        "CheckIngest": status_ok("$.ingest.result", "Predict", "IngestFailed"),
        "IngestFailed": fail_pass("IngestFailed", "$.ingest.result"),
        "Predict": lambda_task(
            "stock-lstm-inference",
            {"symbol.$": "$.symbol", "mode": "predict", "execution_id.$": "$$.Execution.Id"},
            "$.prediction", "CheckPrediction",
        ),
        "CheckPrediction": status_ok("$.prediction.result", "ComputeSignals" if with_signals else "Done", "PredictionFailed"),
        "PredictionFailed": fail_pass("PredictionFailed", "$.prediction.result"),
        "PublishFailure": {
            "Type": "Task",
            "Resource": "arn:aws:states:::sns:publish",
            "Parameters": {
                "TopicArn": TOPIC,
                "Subject": "Stock pipeline FAILED",
                "Message.$": "States.Format('The stock prediction pipeline failed.\nSymbol: {}\nExecution: {}\nError: {}', $.symbol, $$.Execution.Id, States.JsonToString($.error))",
            },
            "ResultPath": None,
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5, "MaxAttempts": 2, "BackoffRate": 2}],
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.publishError", "Next": "Failed"}],
            "Next": "Failed",
        },
        "Failed": {"Type": "Fail", "Error": "PipelineFailed", "Cause": "See SNS failure alert / CloudWatch alarm"},
        "Done": {"Type": "Succeed"},
    }
    if with_signals:
        states.update({
            "ComputeSignals": lambda_task(
                "stock-signals",
                {"symbol.$": "$.symbol", "prediction.$": "$.prediction.result", "execution_id.$": "$$.Execution.Id"},
                "$.signals", "CheckSignals",
            ),
            "CheckSignals": status_ok("$.signals.result", "AlertNeeded", "SignalsFailed"),
            "SignalsFailed": fail_pass("SignalsFailed", "$.signals.result"),
            "AlertNeeded": {
                "Type": "Choice",
                "Choices": [{
                    "And": [
                        {"Variable": "$.signals.result.alert", "IsPresent": True},
                        {"Variable": "$.signals.result.alert", "IsBoolean": True},
                        {"Variable": "$.signals.result.alert", "BooleanEquals": True},
                        {"Variable": "$.signals.result.subject", "IsString": True},
                        {"Variable": "$.signals.result.message", "IsString": True},
                    ],
                    "Next": "PublishAlert",
                }],
                "Default": "ScorePredictions",
            },
            "PublishAlert": {
                "Type": "Task",
                "Resource": "arn:aws:states:::sns:publish",
                "Parameters": {"TopicArn": TOPIC, "Subject.$": "$.signals.result.subject", "Message.$": "$.signals.result.message"},
                "ResultPath": "$.alertPublish",
                "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5, "MaxAttempts": 2, "BackoffRate": 2}],
                "Catch": CATCH_ALL,
                "Next": "ScorePredictions",
            },
            # Last step: a scoring failure can never block the prediction or the alert.
            "ScorePredictions": lambda_task("stock-evaluate", {"symbol.$": "$.symbol"}, "$.score", "CheckScore"),
            "CheckScore": status_ok("$.score.result", "Done", "ScoreFailed"),
            "ScoreFailed": fail_pass("ScoreFailed", "$.score.result"),
        })
    return {
        "Comment": "Daily stock pipeline: validate input -> ingest real prices -> LSTM prediction (persisted)"
                   + (" -> signals + deduplicated alerts -> score saved predictions vs actuals" if with_signals else "")
                   + ". Every failure publishes to SNS; a CloudWatch alarm covers anything else.",
        "StartAt": "ValidateInput",
        "TimeoutSeconds": 900,
        "States": states,
    }


# ---------------------------------------------------------------------------
# Phase 8 item 3: watchlist pipeline (Map over tickers, one combined email).
# ---------------------------------------------------------------------------
WATCHLIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
MODEL_SYMBOLS = ["AAPL"]  # only these get an LSTM prediction (experimental, does not beat baseline)
WAIT_BETWEEN_TICKERS = 15  # seconds; keeps Alpha Vantage calls well under its burst limit
# One retry in total for IngestError/RateLimitError (shared retrier). DailyLimitError is never retried.
INGEST_RETRY = {"ErrorEquals": ["IngestError", "RateLimitError"], "IntervalSeconds": 60, "MaxAttempts": 1}


def ticker_task(fn, payload, step, nxt):
    """Lambda task inside the Map. Errors are stored where the result would be and lead to
    the per-ticker failure state, so one ticker can never stop the others."""
    t = lambda_task(fn, payload, f"$.{step}", nxt, extra_retry=[INGEST_RETRY] if step == "ingest" else None)
    t["Catch"] = [{"ErrorEquals": ["States.ALL"], "ResultPath": f"$.{step}.result", "Next": f"Ticker{step.title()}Failed"}]
    return t


def ticker_failed(step):
    return {
        "Type": "Pass",
        "Parameters": {
            "symbol.$": "$.symbol", "ok": False, "failed_step": step,
            "error.$": f"States.JsonToString($.{step}.result)",
            # alerts already marked sent by stock-signals must still reach the email
            "ingest.$": "$.ingest.result", "prediction.$": "$.prediction.result",
            "signals.$": "$.signals.result", "score.$": "$.score.result",
        },
        "End": True,
    }


def is_one_of(path, values):
    return {"Or": [{"Variable": path, "StringEquals": v} for v in values]}


def ticker_processor():
    is_model = is_one_of("$.symbol", MODEL_SYMBOLS)
    states = {
        "CheckSymbol": {
            "Type": "Choice",
            "Choices": [{"And": [{"Variable": "$.symbol", "IsPresent": True}, {"Variable": "$.symbol", "IsString": True},
                                 is_one_of("$.symbol", WATCHLIST)], "Next": "SpaceOutCalls"}],
            "Default": "TickerInvalid",
        },
        "TickerInvalid": {
            "Type": "Pass",
            "Parameters": {"symbol.$": "States.JsonToString($.symbol)", "ok": False, "failed_step": "validate",
                           "error": "not in the watchlist " + "/".join(WATCHLIST),
                           "ingest": {}, "prediction": {}, "signals": {}, "score": {}},
            "End": True,
        },
        "SpaceOutCalls": {
            "Type": "Choice",
            "Choices": [{"Variable": "$.index", "NumericGreaterThan": 0, "Next": "WaitBetweenTickers"}],
            "Default": "IngestPrices",
        },
        "WaitBetweenTickers": {"Type": "Wait", "Seconds": WAIT_BETWEEN_TICKERS, "Next": "IngestPrices"},
        "IngestPrices": ticker_task("stock-ingest", {"symbol.$": "$.symbol"}, "ingest", "CheckIngest"),
        "CheckIngest": status_ok("$.ingest.result", "RouteModel", "TickerIngestFailed"),
        "RouteModel": {
            "Type": "Choice",
            "Choices": [{"And": [is_model,
                                 {"Variable": "$.ingest.result.data_quality.new_jumps_count", "IsPresent": True},
                                 {"Variable": "$.ingest.result.data_quality.new_jumps_count", "IsNumeric": True},
                                 {"Variable": "$.ingest.result.data_quality.new_jumps_count", "NumericEquals": 0}],
                         "Next": "Predict"}],
            # no model, or a suspicious jump (possible split) in new data: signals only
            "Default": "ComputeSignals",
        },
        "Predict": ticker_task("stock-lstm-inference",
                               {"symbol.$": "$.symbol", "mode": "predict", "execution_id.$": "$$.Execution.Id"},
                               "prediction", "CheckPrediction"),
        "CheckPrediction": status_ok("$.prediction.result", "ComputeSignals", "TickerPredictionFailed"),
        "ComputeSignals": ticker_task("stock-signals",
                                      {"symbol.$": "$.symbol", "prediction.$": "$.prediction.result",
                                       "execution_id.$": "$$.Execution.Id"},
                                      "signals", "CheckSignals"),
        "CheckSignals": status_ok("$.signals.result", "RouteScore", "TickerSignalsFailed"),
        "RouteScore": {"Type": "Choice", "Choices": [dict(is_model, Next="ScorePredictions")], "Default": "TickerDone"},
        # Last per-ticker step: a scoring failure can never block the prediction or the alerts.
        "ScorePredictions": ticker_task("stock-evaluate", {"symbol.$": "$.symbol"}, "score", "CheckScore"),
        "CheckScore": status_ok("$.score.result", "TickerDone", "TickerScoreFailed"),
        "TickerDone": {
            "Type": "Pass",
            "Parameters": {"symbol.$": "$.symbol", "ok": True, "ingest.$": "$.ingest.result",
                           "prediction.$": "$.prediction.result", "signals.$": "$.signals.result",
                           "score.$": "$.score.result"},
            "End": True,
        },
    }
    for step in ("ingest", "prediction", "signals", "score"):
        states[f"Ticker{step.title()}Failed"] = ticker_failed(step)
    return {"ProcessorConfig": {"Mode": "INLINE"}, "StartAt": "CheckSymbol", "States": states}


def build_watchlist():
    states = {
        "ValidateInput": {
            "Type": "Choice",
            "Choices": [
                {   # {"symbols": [1..5 items]}; each item is validated inside the Map
                    "And": [{"Variable": "$.symbols", "IsPresent": True},
                            {"Variable": "$.symbols[0]", "IsPresent": True},
                            {"Not": {"Variable": "$.symbols[5]", "IsPresent": True}}],
                    "Next": "ProcessWatchlist",
                },
                {   # legacy single-symbol input {"symbol": "AAPL"}
                    "And": [{"Variable": "$.symbol", "IsPresent": True}, {"Variable": "$.symbol", "IsString": True}],
                    "Next": "LegacyInput",
                },
            ],
            "Default": "InvalidInput",
        },
        "LegacyInput": {"Type": "Pass", "Parameters": {"symbols.$": "States.Array($.symbol)"}, "Next": "ProcessWatchlist"},
        "InvalidInput": {
            "Type": "Pass",
            # Builds a fresh object, so it works for any JSON input (even non-objects).
            "Parameters": {
                "symbols": "INVALID",
                "error": {"Error": "InvalidInput",
                          "Cause.$": "States.Format('Expected input with symbols = 1 to 5 of " + "/".join(WATCHLIST)
                                     + " (or a legacy symbol). Got: {}', States.JsonToString($))"},
            },
            "Next": "PublishFailure",
        },
        "ProcessWatchlist": {
            "Type": "Map",
            "ItemsPath": "$.symbols",
            "MaxConcurrency": 1,
            "ItemSelector": {
                "symbol.$": "$$.Map.Item.Value", "index.$": "$$.Map.Item.Index",
                "ingest": {"result": {}}, "prediction": {"result": {}}, "signals": {"result": {}}, "score": {"result": {}},
            },
            "ItemProcessor": ticker_processor(),
            "ResultPath": "$.tickers",
            "Catch": CATCH_ALL,
            "Next": "BuildDigest",
        },
        "BuildDigest": lambda_task("stock-alert-digest", {"tickers.$": "$.tickers", "execution_id.$": "$$.Execution.Id"},
                                   "$.digest", "CheckDigest"),
        "CheckDigest": status_ok("$.digest.result", "DigestNeeded", "DigestFailed"),
        "DigestFailed": {
            "Type": "Pass",
            "Parameters": {"symbols.$": "$.symbols",
                           "error": {"Error": "DigestFailed", "Cause.$": "States.JsonToString($.digest.result)"}},
            "Next": "PublishFailure",
        },
        "DigestNeeded": {
            "Type": "Choice",
            "Choices": [{"And": [
                {"Variable": "$.digest.result.send", "IsPresent": True},
                {"Variable": "$.digest.result.send", "IsBoolean": True},
                {"Variable": "$.digest.result.send", "BooleanEquals": True},
                {"Variable": "$.digest.result.subject", "IsString": True},
                {"Variable": "$.digest.result.message", "IsString": True},
            ], "Next": "PublishDigest"}],
            "Default": "Done",
        },
        # ONE email per run: all new alerts, data-quality warnings and failed tickers.
        "PublishDigest": {
            "Type": "Task",
            "Resource": "arn:aws:states:::sns:publish",
            "Parameters": {"TopicArn": TOPIC, "Subject.$": "$.digest.result.subject", "Message.$": "$.digest.result.message"},
            "ResultPath": "$.digestPublish",
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5, "MaxAttempts": 2, "BackoffRate": 2}],
            "Catch": CATCH_ALL,
            "Next": "Done",
        },
        "PublishFailure": {
            "Type": "Task",
            "Resource": "arn:aws:states:::sns:publish",
            "Parameters": {
                "TopicArn": TOPIC,
                "Subject": "Stock pipeline FAILED",
                "Message.$": "States.Format('The stock watchlist pipeline failed.\nSymbols: {}\nExecution: {}\nError: {}', "
                             "States.JsonToString($.symbols), $$.Execution.Id, States.JsonToString($.error))",
            },
            "ResultPath": None,
            "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 5, "MaxAttempts": 2, "BackoffRate": 2}],
            "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.publishError", "Next": "Failed"}],
            "Next": "Failed",
        },
        "Failed": {"Type": "Fail", "Error": "PipelineFailed", "Cause": "See SNS failure alert / CloudWatch alarm"},
        "Done": {"Type": "Succeed"},
    }
    return {
        "Comment": "Daily watchlist pipeline (" + " ".join(WATCHLIST) + "): per ticker, one at a time with a "
                   f"{WAIT_BETWEEN_TICKERS} s gap: ingest real prices -> LSTM prediction for " + "/".join(MODEL_SYMBOLS)
                   + " only (skipped on a suspicious price jump) -> signals (per-type dedup) -> score saved predictions. "
                   "A failing ticker never stops the others. Then ONE combined email (alerts, data-quality warnings, "
                   "failed tickers). Whole-run failures publish to SNS; a CloudWatch alarm covers anything else.",
        "StartAt": "ValidateInput",
        "TimeoutSeconds": 1800,
        "States": states,
    }


if __name__ == "__main__":
    import sys
    here = os.path.dirname(__file__)
    if "--watchlist" in sys.argv:
        out = os.path.join(here, "stock-prediction-pipeline.watchlist.asl.json")
        definition, label = build_watchlist(), "watchlist"
    else:
        with_signals = "--with-signals" in sys.argv
        out = os.path.join(here, "stock-prediction-pipeline.asl.json")
        definition, label = build(with_signals), "with_signals" if with_signals else "phase2"
    with open(out, "w") as f:
        json.dump(definition, f, indent=2)
    print(out, label)
