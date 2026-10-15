"""Known-value tests for MACD, Bollinger, the new alert rules and per-type dedup.

All expected numbers are hand-computed (shown in comments), not produced by the code under test.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "signals"))
import lambda_function as sig  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402


class TestEMA(unittest.TestCase):
    def test_ema_hand_computed(self):
        # n=3, alpha=0.5, seed = (10+11+12)/3 = 11; then 0.5*10+0.5*11 = 10.5; 0.5*8+0.5*10.5 = 9.25
        self.assertEqual(sig.ema_series([10, 11, 12, 10, 8], 3), [None, None, 11, 10.5, 9.25])

    def test_ema_too_short(self):
        self.assertEqual(sig.ema_series([1, 2], 3), [None, None])


class TestMACD(unittest.TestCase):
    def test_linear_series(self):
        # For x_t = t an SMA-seeded EMA(n) lags by exactly (n-1)/2 forever:
        # EMA12 = t - 5.5, EMA26 = t - 12.5, so MACD = 7 on every day; signal = EMA9(7,...) = 7; hist = 0.
        line, signal, hist = sig.macd([float(t) for t in range(1, 61)])
        self.assertAlmostEqual(line, 7.0, places=9)
        self.assertAlmostEqual(signal, 7.0, places=9)
        self.assertAlmostEqual(hist, 0.0, places=9)

    def test_small_params_hand_computed(self):
        # fast=2 (alpha 2/3), slow=3 (alpha 1/2), signal=2 (alpha 2/3) on [1, 2, 4, 8]
        # EMA2: seed 1.5 @i1; i2: 2/3*4+1/3*1.5 = 3.1666667; i3: 2/3*8+1/3*3.1666667 = 6.3888889
        # EMA3: seed 7/3 = 2.3333333 @i2; i3: 0.5*8+0.5*2.3333333 = 5.1666667
        # MACD line: i2 0.8333333, i3 1.2222222; signal seed = mean = 1.0277778; hist = 0.1944444
        line, signal, hist = sig.macd([1, 2, 4, 8], fast=2, slow=3, signal=2)
        self.assertAlmostEqual(line, 1.2222222, places=6)
        self.assertAlmostEqual(signal, 1.0277778, places=6)
        self.assertAlmostEqual(hist, 0.1944444, places=6)

    def test_needs_34_closes(self):
        # 26 closes for the first MACD value, 8 more for the 9-value signal seed
        self.assertEqual(sig.macd([1.0] * 33), (None, None, None))
        self.assertIsNotNone(sig.macd([float(i) for i in range(34)])[1])


class TestBollinger(unittest.TestCase):
    def test_population_sigma_classic(self):
        # [2,4,4,4,5,5,7,9]: mean 5, population variance 32/8 = 4, sigma 2 -> bands 1 and 9; last close 9 -> %B 1.0
        mid, up, lo, pb = sig.bollinger([2, 4, 4, 4, 5, 5, 7, 9], n=8, k=2)
        self.assertEqual((mid, up, lo, pb), (5.0, 9.0, 1.0, 1.0))

    def test_20_day_default(self):
        # 1..20: mean 10.5, population variance (20^2-1)/12 = 33.25, sigma 5.7662813
        # upper 22.0325626, lower -1.0325626, %B(20) = 21.0325626/23.0651252 = 0.9118773
        mid, up, lo, pb = sig.bollinger([float(i) for i in range(1, 21)])
        self.assertAlmostEqual(mid, 10.5)
        self.assertAlmostEqual(up, 22.0325626, places=6)
        self.assertAlmostEqual(lo, -1.0325626, places=6)
        self.assertAlmostEqual(pb, 0.9118773, places=6)

    def test_flat_series(self):
        self.assertEqual(sig.bollinger([5.0] * 20), (5.0, 5.0, 5.0, None))
        self.assertEqual(sig.bollinger([5.0] * 19), (None, None, None, None))


class TestNewRules(unittest.TestCase):
    base = {"close": 100, "change_pct": 0.5, "sma_20": 100, "sma_50": 99, "rsi_14": 50,
            "macd": 1.0, "macd_signal": 0.5, "bb_upper": 105, "bb_lower": 95}

    def types(self, t, y):
        return [a["type"] for a in sig.evaluate_rules(t, y, {})]

    def test_macd_cross_only_on_transition(self):
        y = dict(self.base, macd=0.4)  # was below the signal line
        self.assertEqual(self.types(self.base, y), ["MACD_CROSS"])
        self.assertIn("bullish", sig.evaluate_rules(self.base, y, {})[0]["detail"])
        self.assertEqual(self.types(self.base, self.base), [])  # still above: no repeat
        self.assertIn("bearish", sig.evaluate_rules(y, self.base, {})[0]["detail"])

    def test_bollinger_break_only_on_entry(self):
        up = dict(self.base, close=106)
        self.assertEqual(self.types(up, self.base), ["BOLLINGER_BREAK"])
        self.assertIn("above", sig.evaluate_rules(up, self.base, {})[0]["detail"])
        self.assertEqual(self.types(up, up), [])  # was already outside yesterday
        down = dict(self.base, close=94)
        self.assertIn("below", sig.evaluate_rules(down, self.base, {})[0]["detail"])

    def test_missing_values_no_alert(self):
        t = dict(self.base, macd=None, bb_upper=None)
        self.assertEqual(self.types(t, self.base), [])

    def test_disable_flag(self):
        y = dict(self.base, macd=0.4)
        with mock.patch.dict(os.environ, {"ENABLE_MACD_CROSS": "false"}):
            self.assertEqual(self.types(self.base, y), [])


class FakeTable:
    """Minimal DynamoDB table honouring attribute_not_exists(#m) on update_item."""

    def __init__(self):
        self.items = {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ExpressionAttributeNames=None,
                    ConditionExpression=None):
        item = self.items.setdefault((Key["symbol"], Key["trade_date"]), {})
        names = ExpressionAttributeNames or {}
        if ConditionExpression:
            marker = names["#m"]
            if marker in item:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem")
            item[marker] = ExpressionAttributeValues[":now"]
            item.setdefault("alert_sent_at", ExpressionAttributeValues[":now"])
        else:
            for part in UpdateExpression[4:].split(", "):
                n, v = part.split(" = ")
                item[names[n]] = ExpressionAttributeValues[v]


class TestPerTypeDedup(unittest.TestCase):
    def run_handler(self, table, closes):
        rows = [(f"2026-01-{i + 1:02d}", c) for i, c in enumerate(closes)]
        res = mock.MagicMock()
        res.Table.return_value = table
        with mock.patch.object(sig, "_real_rows", return_value=rows), mock.patch.object(sig.boto3, "resource", return_value=res):
            return sig.lambda_handler({"symbol": "TEST", "execution_id": "x"}, None)

    def test_second_type_same_day_is_sent_repeat_is_not(self):
        table = FakeTable()
        flat = [100.0] * 25 + [100.5, 99.5] * 5 + [100.0]
        big = flat + [104.0]  # +4%: BIG_MOVE and a Bollinger break on the same day
        r1 = self.run_handler(table, big)
        types1 = sorted(a["type"] for a in r1["alerts"])
        self.assertIn("BIG_MOVE", types1)
        self.assertIn("BOLLINGER_BREAK", types1)
        self.assertTrue(r1["alert"])
        r2 = self.run_handler(table, big)  # same day re-run: everything already sent
        self.assertEqual(r2["alerts"], [])
        self.assertFalse(r2["alert"])
        self.assertTrue(r2["deduplicated"])
        self.assertEqual(sorted(r2["already_sent"]), types1)
        # a different rule on the same trading day still goes through
        table.items[("TEST", r1["trade_date"])].pop("alert_sent_BOLLINGER_BREAK")
        r3 = self.run_handler(table, big)
        self.assertEqual([a["type"] for a in r3["alerts"]], ["BOLLINGER_BREAK"])
        self.assertEqual(r3["already_sent"], sorted(t for t in types1 if t != "BOLLINGER_BREAK"))
        self.assertIn("BOLLINGER_BREAK", r3["subject"])


if __name__ == "__main__":
    unittest.main()
