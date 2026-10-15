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


if __name__ == "__main__":
    import sys
    with_signals = "--with-signals" in sys.argv
    out = os.path.join(os.path.dirname(__file__), "stock-prediction-pipeline.asl.json")
    with open(out, "w") as f:
        json.dump(build(with_signals), f, indent=2)
    print(out, "with_signals" if with_signals else "phase2")
