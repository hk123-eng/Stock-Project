"""Offline unit tests for signal math and alert rules."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "signals"))
import lambda_function as sig  # noqa: E402


class TestIndicators(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(sig.sma([1, 2, 3, 4], 2), 3.5)
        self.assertIsNone(sig.sma([1], 2))

    def test_rsi_extremes(self):
        self.assertEqual(sig.rsi(list(range(1, 30))), 100.0)
        self.assertAlmostEqual(sig.rsi(list(range(30, 1, -1))), 0.0)
        self.assertIsNone(sig.rsi([1, 2, 3]))

    def test_rsi_known_value(self):
        # Wilder example closes: gains 3.34/14, losses 1.40/14 -> RS 2.386 -> RSI 70.46
        # (textbooks quote 70.53 because they round the average loss to 0.0996)
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        self.assertAlmostEqual(sig.rsi(closes), 70.464, delta=0.001)


class TestRules(unittest.TestCase):
    base = {"change_pct": 0.5, "sma_20": 100, "sma_50": 99, "rsi_14": 50}

    def test_quiet_day_no_alert(self):
        self.assertEqual(sig.evaluate_rules(self.base, self.base, {"predicted_change_pct": 0.3}), [])

    def test_big_move(self):
        t = dict(self.base, change_pct=-3.2)
        self.assertEqual([a["type"] for a in sig.evaluate_rules(t, self.base, {})], ["BIG_MOVE"])

    def test_cross_only_on_transition(self):
        y = dict(self.base, sma_20=98)
        self.assertEqual([a["type"] for a in sig.evaluate_rules(self.base, y, {})], ["SMA_CROSS"])
        self.assertEqual(sig.evaluate_rules(self.base, self.base, {}), [])  # still above: no repeat

    def test_rsi_zone_only_on_entry(self):
        t, y = dict(self.base, rsi_14=72), dict(self.base, rsi_14=68)
        self.assertEqual([a["type"] for a in sig.evaluate_rules(t, y, {})], ["RSI_ZONE"])
        self.assertEqual(sig.evaluate_rules(t, dict(self.base, rsi_14=71), {}), [])

    def test_predicted_move_with_caveat(self):
        a = sig.evaluate_rules(self.base, self.base, {"predicted_change_pct": -2.5, "prediction": 1, "inputs_outside_scaler_range": True})
        self.assertEqual(a[0]["type"], "PREDICTED_MOVE")
        self.assertIn("low confidence", a[0]["detail"])


if __name__ == "__main__":
    unittest.main()
