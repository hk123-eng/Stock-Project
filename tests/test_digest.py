"""Offline tests for the combined per-run alert email."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "digest"))
import lambda_function as dg  # noqa: E402


def ok(sym, alerts=(), jumps=(), pred=True):
    return {"symbol": sym, "ok": True,
            "ingest": {"statusCode": 200, "data_quality": {"jumps": list(jumps)}},
            "prediction": {"statusCode": 200} if pred else {},
            "signals": {"statusCode": 200, "trade_date": "2026-10-15", "alerts": list(alerts)}, "score": {}}


class TestDigest(unittest.TestCase):
    def test_quiet_run_sends_nothing(self):
        d = dg.build_digest([ok("AAPL"), ok("MSFT", pred=False)])
        self.assertFalse(d["send"])
        self.assertEqual((d["ok"], d["failed"], d["alerts"]), (2, 0, 0))

    def test_all_alerts_across_tickers_in_one_message(self):
        d = dg.build_digest([
            ok("AAPL", [{"type": "MACD_CROSS", "detail": "x"}, {"type": "BIG_MOVE", "detail": "y"}]),
            ok("NVDA", [{"type": "BOLLINGER_BREAK", "detail": "z"}], pred=False),
        ], "exec-1")
        self.assertTrue(d["send"])
        self.assertEqual(d["alerts"], 3)
        for s in ("AAPL 2026-10-15: MACD_CROSS: x", "AAPL 2026-10-15: BIG_MOVE: y", "NVDA 2026-10-15: BOLLINGER_BREAK: z"):
            self.assertIn(s, d["message"])
        self.assertEqual(d["subject"], "Stock watchlist: AAPL BIG_MOVE/MACD_CROSS; NVDA BOLLINGER_BREAK")
        self.assertIn("does not beat a naive baseline", d["message"])

    def test_failures_isolated_and_reported(self):
        cause = json.dumps({"errorType": "DailyLimitError", "errorMessage": "Alpha Vantage Information: 25 requests per day"})
        err = {"Error": "DailyLimitError", "Cause": cause}
        d = dg.build_digest([ok("AAPL"), {"symbol": "MSFT", "ok": False, "failed_step": "ingest", "error": err},
                             {"symbol": "ZZZZ", "ok": False, "failed_step": "validate", "error": "not in the watchlist"}])
        self.assertTrue(d["send"])
        self.assertEqual(d["failed"], 2)
        self.assertTrue(d["subject"].startswith("Stock watchlist: 2 FAILED"))
        self.assertIn("MSFT: failed at ingest: DailyLimitError: Alpha Vantage Information: 25 requests per day", d["message"])
        self.assertIn("ZZZZ: failed at validate: not in the watchlist", d["message"])
        self.assertIn("1 of 3 tickers OK", d["message"])

    def test_bad_status_result_as_error(self):
        # status != 200: the state machine passes the Lambda result JSON string as the error
        d = dg.build_digest([{"symbol": "AAPL", "ok": False, "failed_step": "signals",
                              "error": json.dumps({"statusCode": 400, "error": "need >= 2 real prices, have 0"})}])
        self.assertIn("AAPL: failed at signals: need >= 2 real prices, have 0", d["message"])

    def test_new_jump_warning_and_skipped_prediction(self):
        j = {"new": True, "trade_date": "2026-10-15", "prev_trade_date": "2026-10-14", "prev_close": 400.0,
             "close": 100.0, "change_pct": -75.0, "split_hint": "4-for-1 split?"}
        old = dict(j, new=False)
        d = dg.build_digest([ok("AAPL", jumps=[j], pred=False), ok("MSFT", jumps=[old], pred=False)])
        self.assertTrue(d["send"])
        self.assertEqual(d["warnings"], 1)  # only the jump on new data
        self.assertIn("4-for-1 split?", d["message"])
        self.assertIn("AAPL: model prediction skipped", d["message"])
        self.assertNotIn("MSFT: model prediction skipped", d["message"])

    def test_subject_limit_and_bad_input(self):
        many = [ok(f"T{i}", [{"type": "BOLLINGER_BREAK", "detail": "d"}, {"type": "MACD_CROSS", "detail": "d"}], pred=False)
                for i in range(10)]
        self.assertLessEqual(len(dg.build_digest(many)["subject"]), 100)
        self.assertFalse(dg.build_digest(None)["send"])
        self.assertEqual(dg.build_digest(["junk", 3])["tickers"], 0)


if __name__ == "__main__":
    unittest.main()
