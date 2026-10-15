"""Offline unit tests for the model-health summary in the API."""
import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")  # the module creates a boto3 resource at import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "api"))
import lambda_function as api  # noqa: E402


def days(n, err=2.0, naive=1.0):
    return [{"actual_date": f"d{i:03d}", "error": err if i % 2 else -err, "naive_error": naive} for i in range(n)]


class TestHealthSummary(unittest.TestCase):
    def test_no_data(self):
        s = api.health_summary([])
        self.assertEqual(s["verdict"], "insufficient data (0 of 20 scored days)")
        self.assertIsNone(s["beats_baseline"])
        self.assertIsNone(s["all"]["model_mae"])

    def test_insufficient_below_20_even_if_better(self):
        s = api.health_summary(days(19, err=0.1, naive=5))
        self.assertEqual(s["verdict"], "insufficient data (19 of 20 scored days)")
        self.assertIsNone(s["beats_baseline"])
        self.assertEqual(s["all"]["model_mae"], 0.1)  # numbers are still reported, without a verdict

    def test_verdict_at_20(self):
        self.assertEqual(api.health_summary(days(20, err=2, naive=1))["verdict"], "does not beat baseline")
        s = api.health_summary(days(25, err=0.5, naive=1))
        self.assertTrue(s["beats_baseline"])
        self.assertEqual(s["rolling"]["days"], 20)


class TestAlerts(unittest.TestCase):
    def test_per_type_markers_and_test_label(self):
        items = [
            {"trade_date": "2026-10-02", "alerts": [{"type": "PREDICTED_MOVE"}], "alert_sent_at": "t0",
             "alert_execution": "arn:aws:states:x:execution:stock-prediction-pipeline:test-signals-alert-2"},
            {"trade_date": "2026-10-14", "alerts": [{"type": "MACD_CROSS"}, {"type": "BIG_MOVE"}], "alert_sent_at": "t1",
             "alert_sent_MACD_CROSS": "t1", "alert_sent_BIG_MOVE": "t2", "alert_execution": "arn:...:ca6a-scheduled"},
            {"trade_date": "2026-10-15", "alerts": []},
        ]
        with mock.patch.object(api, "_query_all", return_value=items):
            out = api.alerts("AAPL", 10)["alerts"]
        self.assertEqual([a["trade_date"] for a in out], ["2026-10-02", "2026-10-14"])
        self.assertEqual(out[0]["notified_types"], [])  # legacy item: only alert_sent_at
        self.assertTrue(out[0]["test_alert"])
        self.assertEqual(out[1]["notified_types"], ["BIG_MOVE", "MACD_CROSS"])
        self.assertFalse(out[1]["test_alert"])


def ev(path, symbol=None):
    e = {"rawPath": path, "requestContext": {"http": {"method": "GET"}}}
    if symbol:
        e["queryStringParameters"] = {"symbol": symbol}
    return e


class TestWatchlistRouting(unittest.TestCase):
    def test_allow_list(self):
        r = api.lambda_handler(ev("/prices", "TSLA"), None)
        self.assertEqual(r["statusCode"], 400)
        self.assertEqual(sorted(api.SYMBOLS), ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"])

    def test_model_routes_404_without_model(self):
        for route in ("/predictions", "/predictions/latest", "/evaluation", "/model-health"):
            r = api.lambda_handler(ev(route, "nvda"), None)
            self.assertEqual(r["statusCode"], 404, route)
            body = json.loads(r["body"])
            self.assertEqual(body["error"], "no validated model")
            self.assertEqual(body["note"], "Prices and signals only; no validated model")

    def test_non_model_prices_ok_and_labelled(self):
        with mock.patch.object(api, "_real_prices", return_value=[{"trade_date": "d1", "close": 1}]),                 mock.patch.object(api, "_count_synthetic", return_value=0):
            r = api.lambda_handler(ev("/prices", "MSFT"), None)
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(json.loads(r["body"])["model_status"], "Prices and signals only; no validated model")

    def test_aapl_labelled_experimental(self):
        with mock.patch.object(api, "_query_all", return_value=[]), mock.patch.object(api, "_real_prices", return_value=[]):
            r = api.lambda_handler(ev("/predictions", "AAPL"), None)
        self.assertEqual(json.loads(r["body"])["model_status"], "experimental, does not beat baseline")


if __name__ == "__main__":
    unittest.main()
