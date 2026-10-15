"""Offline unit tests for the ingestion parser (no AWS, no network)."""
import datetime as dt
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ingest"))
import lambda_function as ing  # noqa: E402


def payload(series, symbol="AAPL"):
    return {"Meta Data": {"2. Symbol": symbol}, "Time Series (Daily)": series}


DAY = {"1. open": "100.0", "2. high": "105.5", "3. low": "99.0", "4. close": "104.25", "5. volume": "12345"}


class TestCloseTime(unittest.TestCase):
    def test_dst_and_standard(self):
        self.assertEqual(ing.us_close_utc(dt.date(2026, 7, 1)), "2026-07-01T20:00:00Z")
        self.assertEqual(ing.us_close_utc(dt.date(2026, 1, 5)), "2026-01-05T21:00:00Z")
        # 2026: DST starts Sun 8 Mar, ends Sun 1 Nov
        self.assertEqual(ing.us_close_utc(dt.date(2026, 3, 6)), "2026-03-06T21:00:00Z")
        self.assertEqual(ing.us_close_utc(dt.date(2026, 3, 9)), "2026-03-09T20:00:00Z")
        self.assertEqual(ing.us_close_utc(dt.date(2026, 10, 30)), "2026-10-30T20:00:00Z")
        self.assertEqual(ing.us_close_utc(dt.date(2026, 11, 2)), "2026-11-02T21:00:00Z")

    def test_never_collides_with_synthetic_times(self):
        for h in ("T00:00:00Z", "T10:19:39Z", "T10:24:2"):
            self.assertNotIn(h, ing.us_close_utc(dt.date(2026, 6, 8)))


class TestParse(unittest.TestCase):
    def test_numbers_are_decimal_and_tagged(self):
        rows = ing.parse_daily(payload({"2026-10-02": DAY, "2026-10-01": DAY}), "AAPL")
        self.assertEqual([r["trade_date"] for r in rows], ["2026-10-01", "2026-10-02"])
        r = rows[0]
        self.assertIsInstance(r["close"], Decimal)
        self.assertEqual(r["close"], Decimal("104.25"))
        self.assertEqual(r["volume"], 12345)
        self.assertEqual((r["source"], r["data_type"], r["adjusted"]), ("alphavantage", "real", False))

    def test_rate_limit(self):
        with self.assertRaises(ing.RateLimitError):
            ing.parse_daily({"Information": "rate limit reached"}, "AAPL")
        with self.assertRaises(ing.RateLimitError):
            ing.parse_daily({"Note": "Thank you for using Alpha Vantage"}, "AAPL")

    def test_errors(self):
        with self.assertRaises(ing.IngestError):
            ing.parse_daily({"Error Message": "Invalid API call"}, "AAPL")
        with self.assertRaises(ing.IngestError):
            ing.parse_daily(payload({}), "AAPL")
        with self.assertRaises(ing.IngestError):
            ing.parse_daily(payload({"2026-10-01": DAY}, symbol="MSFT"), "AAPL")
        with self.assertRaises(ing.IngestError):
            ing.parse_daily(payload({"2026-10-01": dict(DAY, **{"4. close": "abc"})}), "AAPL")
        with self.assertRaises(ing.IngestError):
            ing.parse_daily(payload({"2026-10-01": dict(DAY, **{"2. high": "50"})}), "AAPL")

    def test_bad_symbol_rejected_before_any_aws_call(self):
        for ev in ({}, {"symbol": "aapl"}, {"symbol": "TOOLONG"}, {"symbol": 5}, None):
            with self.assertRaises(ing.IngestError):
                ing.lambda_handler(ev, None)


if __name__ == "__main__":
    unittest.main()
