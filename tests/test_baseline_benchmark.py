import pathlib
import random
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "infra" / "ml"))
import baseline_benchmark as bb  # noqa: E402


class TestPredict(unittest.TestCase):
    def test_naive_mean5_drift(self):
        c = [10.0, 11, 12, 13, 14, 15]
        self.assertEqual(bb.predict(c, "naive"), 15)
        self.assertEqual(bb.predict(c, "mean5"), 13)
        self.assertEqual(bb.predict(c, "drift"), 16)   # 15 + (15 - 10) / 5

    def test_ar5_recovers_known_process(self):
        # r[i] = 0.001 + 0.5 r[i-1] - 0.2 r[i-2] + seeded white noise
        rng = random.Random(1)
        r = [0.01, -0.02, 0.015, 0.0, 0.005]
        for _ in range(2000):
            r.append(0.001 + 0.5 * r[-1] - 0.2 * r[-2] + rng.gauss(0, 0.01))
        coef = bb.fit_ar(r)
        self.assertAlmostEqual(coef[0], 0.001, delta=0.002)
        self.assertAlmostEqual(coef[1], 0.5, delta=0.1)
        self.assertAlmostEqual(coef[2], -0.2, delta=0.1)

    def test_no_lookahead(self):
        rows = [(f"d{i:03d}", 100 + i + (i % 3)) for i in range(70)]
        pts = bb.walk_forward(rows, min_history=60)
        self.assertEqual(len(pts), 10)
        # changing a future close never changes an earlier prediction
        rows2 = rows[:65] + [(d, c * 3) for d, c in rows[65:]]
        pts2 = bb.walk_forward(rows2, min_history=60)
        for a, b in zip(pts[:6], pts2[:6]):
            for m in bb.MODELS:
                self.assertEqual(a[m], b[m])


class TestMetrics(unittest.TestCase):
    def test_metrics_and_direction(self):
        pts = [
            {"actual": 102, "previous_close": 100, "naive": 100, "x": 101},
            {"actual": 98, "previous_close": 100, "naive": 100, "x": 101},
        ]
        m = bb.metrics(pts, "x")
        self.assertEqual(m["n"], 2)
        self.assertAlmostEqual(m["mae"], 2.0)
        self.assertAlmostEqual(m["bias"], 1.0)
        self.assertEqual(m["directional_days"], 2)
        self.assertEqual(m["directional_accuracy_pct"], 50.0)
        naive = bb.metrics(pts, "naive")
        self.assertEqual(naive["directional_days"], 0)
        self.assertIsNone(naive["directional_accuracy_pct"])


class TestLive(unittest.TestCase):
    def test_live_comparison_uses_history_before_target(self):
        rows = [(f"d{i:03d}", 100.0 + i + (i % 3)) for i in range(80)]
        out = bb.live_comparison(rows, [{"actual_date": "d070", "last_close": 169.0, "predicted_close": 172.0}])
        self.assertEqual(out["days"], 1)
        self.assertEqual(out["metrics"]["lstm"]["mae"], 1.0)    # 172 - 171 (d070 close = 100 + 70 + 1)
        self.assertEqual(out["metrics"]["naive"]["mae"], 2.0)   # 171 - 169 (d069 close)

    def test_live_comparison_rejects_mismatched_last_close(self):
        rows = [(f"d{i:03d}", 100.0 + i + (i % 3)) for i in range(80)]
        with self.assertRaises(ValueError):
            bb.live_comparison(rows, [{"actual_date": "d070", "last_close": 50.0, "predicted_close": 1.0}])


if __name__ == "__main__":
    unittest.main()
