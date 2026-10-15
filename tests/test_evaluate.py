"""Offline unit tests for prediction scoring (fake DynamoDB / CloudWatch)."""
import os
import sys
import unittest
from decimal import Decimal
from unittest import mock

from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "evaluate"))
import lambda_function as ev  # noqa: E402


class FakeTable:
    def __init__(self, items, key):
        self.items, self.key, self.updates = items, key, []

    def query(self, **kwargs):
        return {"Items": [dict(i) for i in self.items]}

    def update_item(self, Key, ConditionExpression=None, ExpressionAttributeValues=None, **_):
        item = next(i for i in self.items if i[self.key] == Key[self.key])
        if "scored_at" in item:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
        vals = ExpressionAttributeValues
        item.update(actual_date=vals[":ad"], actual_close=vals[":ac"], error=vals[":e"],
                    naive_error=vals[":ne"], scored_at=vals[":now"])
        self.updates.append(Key)


def price(day, close, source="alphavantage"):
    row = {"symbol": "AAPL", "timestamp": f"{day}T20:00:00Z", "trade_date": day, "close": Decimal(str(close))}
    if source:
        row["source"] = source
    return row


def pred(as_of, predicted, last):
    return {"symbol": "AAPL", "as_of_date": as_of, "predicted_close": Decimal(str(predicted)), "last_close": Decimal(str(last))}


class TestPure(unittest.TestCase):
    def test_next_real_day_skips_holiday_gap(self):
        rows = [("2026-07-02", 1.0), ("2026-07-06", 2.0)]  # 2026-07-03 holiday: no row
        self.assertEqual(ev.next_real_day(rows, "2026-07-02"), ("2026-07-06", 2.0))
        self.assertIsNone(ev.next_real_day(rows, "2026-07-06"))

    def test_score_model_and_naive(self):
        s = ev.score(pred("2026-10-02", 334.7775, 333.69), "2026-10-05", 332.89)
        self.assertAlmostEqual(s["error"], 1.8875, places=4)
        self.assertAlmostEqual(s["naive_error"], 0.80, places=4)
        self.assertAlmostEqual(s["abs_pct_error"], 1.8875 / 332.89 * 100, places=6)


class TestHandler(unittest.TestCase):
    def run_handler(self, prices, preds):
        ptab = FakeTable(prices, "timestamp")
        dtab = FakeTable(preds, "as_of_date")
        cw = mock.Mock()
        res = mock.Mock()
        # The real query filters on source; the fake returns everything, so pre-filter like DynamoDB would.
        ptab.query = lambda **k: {"Items": [dict(i) for i in prices if i.get("source") == "alphavantage"]}
        res.Table.side_effect = lambda name: ptab if name == ev.PRICES_TABLE else dtab
        with mock.patch.object(ev.boto3, "resource", return_value=res), mock.patch.object(ev.boto3, "client", return_value=cw):
            out = ev.lambda_handler({"symbol": "AAPL"}, None)
        return out, dtab, cw

    def test_scores_once_and_leaves_latest_pending(self):
        prices = [price("2026-10-01", 330.32), price("2026-10-02", 333.69), price("2026-10-05", 332.89),
                  price("2026-10-03", 999, source=None)]  # synthetic row must be ignored
        preds = [pred("2026-10-02", 334.7775, 333.69), pred("2026-10-05", 334.1336, 332.89)]
        out, dtab, cw = self.run_handler(prices, preds)
        self.assertEqual((out["newly_scored"], out["pending"], out["already_scored"]), (1, 1, 0))
        self.assertEqual(out["scored"][0]["actual_date"], "2026-10-05")
        self.assertEqual(cw.put_metric_data.call_count, 1)
        names = [m["MetricName"] for m in cw.put_metric_data.call_args.kwargs["MetricData"]]
        self.assertEqual(names, ["ModelAbsError", "NaiveAbsError"])

        out2, _, cw2 = self.run_handler(prices, dtab.items)  # idempotent re-run
        self.assertEqual((out2["newly_scored"], out2["already_scored"], out2["pending"]), (0, 1, 1))
        cw2.put_metric_data.assert_not_called()

    def test_bad_symbol(self):
        self.assertEqual(ev.lambda_handler({"symbol": "aapl!"}, None)["statusCode"], 400)


if __name__ == "__main__":
    unittest.main()
