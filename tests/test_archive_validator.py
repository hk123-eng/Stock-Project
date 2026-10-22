"""Offline tests for stock-archive-validator (S3 client mocked)."""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "archive_validator"))
import lambda_function as av  # noqa: E402

KEY = "raw/alphavantage/AAPL/2026-10-21/TIME_SERIES_DAILY_20261021T223011Z.json"


def archive(symbol="AAPL", extra=None, bad_day=False):
    ts = {"2026-10-20": {"1. open": "340.0", "2. high": "341.0", "3. low": "338.0", "4. close": "339.5", "5. volume": "100"},
          "2026-10-21": {"1. open": "339.5", "2. high": "345.25", "3. low": "338.83", "4. close": "343.99", "5. volume": "35586054"}}
    if bad_day:
        ts["2026-10-21"]["4. close"] = "n/a"
    d = {"Meta Data": {"2. Symbol": symbol, "3. Last Refreshed": "2026-10-21"}, "Time Series (Daily)": ts}
    d.update(extra or {})
    return json.dumps(d, indent=4).encode()


class TestValidate(unittest.TestCase):
    def test_good_archive(self):
        m = av.validate(KEY, archive())
        self.assertEqual(m["status"], "ok")
        self.assertEqual((m["symbol"], m["n_days"], m["first_date"], m["last_date"]), ("AAPL", 2, "2026-10-20", "2026-10-21"))
        self.assertEqual(m["rows"][-1], {"trade_date": "2026-10-21", "open": 339.5, "high": 345.25, "low": 338.83,
                                         "close": 343.99, "volume": 35586054})
        self.assertEqual(m["findings"], [])

    def test_key_or_url_is_a_finding_and_never_echoed(self):
        secretish = "apikey=" + "Q" * 16
        m = av.validate(KEY, archive(extra={"Note": f"see https://www.alphavantage.co/query?{secretish}"}))
        self.assertEqual(m["status"], "failed")
        self.assertFalse(m["checks"]["no_key_or_url"])
        self.assertEqual(set(m["findings"]), {"apikey parameter", "URL", "alphavantage.co host"})
        self.assertNotIn("Q" * 16, json.dumps({k: v for k, v in m.items() if k != "rows"}))

    def test_symbol_mismatch_bad_number_and_throttle_message(self):
        self.assertFalse(av.validate(KEY, archive(symbol="MSFT"))["checks"]["symbol_matches_key"])
        self.assertEqual(av.validate(KEY, archive(bad_day=True))["status"], "failed")
        m = av.validate(KEY, json.dumps({"Information": "rate limit"}).encode())
        self.assertEqual(m["status"], "failed")
        self.assertFalse(m["checks"]["has_time_series"])
        self.assertEqual(av.validate(KEY, b"not json")["status"], "failed")

    def test_test_prefix_has_no_symbol_check(self):
        self.assertIsNone(av.validate("raw/_test/x.json", archive())["checks"]["symbol_matches_key"])

    def test_manifest_key_never_under_raw(self):
        self.assertEqual(av.manifest_key(KEY), "manifests/alphavantage/AAPL/2026-10-21/TIME_SERIES_DAILY_20261021T223011Z.json.manifest.json")
        with self.assertRaises(ValueError):
            av.manifest_key("manifests/x.json")


class TestHandler(unittest.TestCase):
    def _s3(self, body):
        s3 = mock.Mock()
        s3.get_object.return_value = {"ContentLength": len(body), "Body": io.BytesIO(body), "ETag": '"abc"'}
        return s3

    def test_s3_event_writes_one_single_line_manifest_outside_raw(self):
        s3 = self._s3(archive())
        ev = {"Records": [{"eventSource": "aws:s3", "s3": {"bucket": {"name": av.BUCKET}, "object": {"key": KEY.replace(":", "%3A")}}}]}
        with mock.patch.object(av, "_client", return_value=s3), mock.patch("builtins.print"):
            r = av.lambda_handler(ev, None)
        self.assertEqual((r["validated"], r["failed"]), (1, 0))
        put = s3.put_object.call_args.kwargs
        self.assertTrue(put["Key"].startswith("manifests/"))
        self.assertEqual(put["Body"].decode().count("\n"), 1)
        self.assertEqual(json.loads(put["Body"])["source_etag"], "abc")
        self.assertEqual([c[0] for c in s3.method_calls], ["get_object", "put_object"])

    def test_other_buckets_and_prefixes_are_ignored(self):
        s3 = self._s3(archive())
        ev = {"Records": [{"eventSource": "aws:s3", "s3": {"bucket": {"name": "other"}, "object": {"key": KEY}}},
                          {"eventSource": "aws:s3", "s3": {"bucket": {"name": av.BUCKET}, "object": {"key": "manifests/a.json"}}}]}
        with mock.patch.object(av, "_client", return_value=s3):
            self.assertEqual(av.lambda_handler(ev, None)["validated"], 0)
        s3.put_object.assert_not_called()


if __name__ == "__main__":
    unittest.main()
