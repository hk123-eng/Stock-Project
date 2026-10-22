"""Offline tests for stock-event-logger."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "event_logger"))
import lambda_function as el  # noqa: E402

EVENT = {"id": "e1", "source": "stock.pipeline", "detail-type": "PriceIngested", "time": "2026-10-22T00:00:00Z",
         "detail": {"symbol": "AAPL", "trade_date": "2026-10-21", "close": 343.99}}


class TestEventLogger(unittest.TestCase):
    def test_logs_the_whole_event_as_one_json_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = el.lambda_handler(EVENT, None)
        logged = json.loads(buf.getvalue())
        self.assertEqual(logged["stock_event"], EVENT)
        self.assertEqual(r["logged"], {"source": "stock.pipeline", "detail_type": "PriceIngested", "id": "e1",
                                       "time": "2026-10-22T00:00:00Z"})
        self.assertFalse(r["truncated"])

    def test_huge_event_is_truncated(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            r = el.lambda_handler(dict(EVENT, detail={"x": "y" * 20000}), None)
        self.assertTrue(r["truncated"])
        self.assertLessEqual(len(buf.getvalue().strip()), el.MAX_LOG_CHARS)


if __name__ == "__main__":
    unittest.main()
