"""Offline tests for stock-stream-handler (no AWS calls; the EventBridge client is mocked)."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "stream_handler"))
import lambda_function as sh  # noqa: E402


def rec(name="INSERT", source="alphavantage", sym="AAPL", eid="e1"):
    img = {"symbol": {"S": sym}, "timestamp": {"S": "2026-10-21T20:00:00Z"}, "trade_date": {"S": "2026-10-21"},
           "close": {"N": "343.99"}, "volume": {"N": "41000000"}, "adjusted": {"BOOL": False}}
    if source:
        img["source"] = {"S": source}
    return {"eventID": eid, "eventName": name, "dynamodb": {"NewImage": img}}


class TestStreamHandler(unittest.TestCase):
    def test_only_alphavantage_inserts_become_events(self):
        recs = [rec(), rec("MODIFY"), rec("REMOVE"), rec(source=None), rec(source="synthetic"), rec(sym="NVDA", eid="e2")]
        entries = sh.price_events(recs)
        self.assertEqual(len(entries), 2)
        d = json.loads(entries[0]["Detail"])
        self.assertEqual(entries[0]["DetailType"], "PriceIngested")
        self.assertEqual(entries[0]["Source"], "stock.pipeline")
        self.assertEqual(entries[0]["EventBusName"], "stock-events")
        self.assertEqual((d["symbol"], d["trade_date"], d["close"], d["volume"], d["adjusted"], d["stream_event_id"]),
                         ("AAPL", "2026-10-21", 343.99, 41000000, False, "e1"))

    def test_batches_of_ten_and_no_other_aws_calls(self):
        client = mock.Mock()
        client.put_events.return_value = {"FailedEntryCount": 0}
        with mock.patch.object(sh, "_client", return_value=client), mock.patch("builtins.print"):
            r = sh.lambda_handler({"Records": [rec(eid=str(i)) for i in range(23)]}, None)
        self.assertEqual(r, {"records": 23, "published": 23})
        self.assertEqual([len(c.kwargs["Entries"]) for c in client.put_events.call_args_list], [10, 10, 3])
        self.assertEqual([c[0] for c in client.method_calls], ["put_events"] * 3)

    def test_failed_entries_raise_for_retry(self):
        client = mock.Mock()
        client.put_events.return_value = {"FailedEntryCount": 1}
        with mock.patch.object(sh, "_client", return_value=client):
            with self.assertRaises(RuntimeError):
                sh.lambda_handler({"Records": [rec()]}, None)

    def test_nothing_to_publish_makes_no_call(self):
        client = mock.Mock()
        with mock.patch.object(sh, "_client", return_value=client), mock.patch("builtins.print"):
            self.assertEqual(sh.lambda_handler({"Records": [rec("MODIFY")]}, None)["published"], 0)
        client.put_events.assert_not_called()


if __name__ == "__main__":
    unittest.main()
