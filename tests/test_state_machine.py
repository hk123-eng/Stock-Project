"""Structural tests for the generated Step Functions definitions (no AWS)."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "infra", "stepfunctions"))
import build_definition as bd  # noqa: E402


def all_states(states):
    """Yield (name, state) for every state, including those inside Map processors."""
    for name, st in states.items():
        yield name, st
        if st["Type"] == "Map":
            yield from all_states(st["ItemProcessor"]["States"])


def targets(st):
    out = [st.get("Next"), st.get("Default")]
    out += [c.get("Next") for c in st.get("Choices", [])]
    out += [c.get("Next") for c in st.get("Catch", [])]
    return [t for t in out if t]


class TestWatchlistDefinition(unittest.TestCase):
    d = bd.build_watchlist()

    def test_committed_file_matches_generator(self):
        with open(os.path.join(HERE, "..", "infra", "stepfunctions", "stock-prediction-pipeline.watchlist.asl.json")) as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(self.d)))

    def test_every_transition_exists_in_its_scope(self):
        def check(states):
            for name, st in states.items():
                for t in targets(st):
                    self.assertIn(t, states, f"{name} -> {t}")
                if st["Type"] == "Map":
                    check(st["ItemProcessor"]["States"])
        check(self.d["States"])

    def test_map_one_at_a_time_with_wait(self):
        m = self.d["States"]["ProcessWatchlist"]
        self.assertEqual(m["MaxConcurrency"], 1)
        inner = m["ItemProcessor"]["States"]
        self.assertEqual(inner["WaitBetweenTickers"]["Seconds"], 15)
        self.assertEqual(inner["SpaceOutCalls"]["Choices"][0]["NumericGreaterThan"], 0)  # no wait before the first

    def test_per_ticker_failure_isolation(self):
        inner = self.d["States"]["ProcessWatchlist"]["ItemProcessor"]["States"]
        for name, st in inner.items():
            if st["Type"] == "Task":
                catch = st["Catch"]
                self.assertEqual(catch[0]["ErrorEquals"], ["States.ALL"], name)
                self.assertTrue(catch[0]["Next"].startswith("Ticker"), name)  # stays inside the Map
                self.assertTrue(inner[catch[0]["Next"]].get("End"), name)

    def test_daily_limit_not_retried_and_retry_bounded(self):
        ing = self.d["States"]["ProcessWatchlist"]["ItemProcessor"]["States"]["IngestPrices"]
        names = [e for r in ing["Retry"] for e in r["ErrorEquals"]]
        self.assertNotIn("DailyLimitError", names)
        self.assertNotIn("States.ALL", names)
        shared = [r for r in ing["Retry"] if "IngestError" in r["ErrorEquals"]]
        self.assertEqual(len(shared), 1)
        self.assertIn("RateLimitError", shared[0]["ErrorEquals"])
        self.assertEqual(shared[0]["MaxAttempts"], 1)  # at most 2 Alpha Vantage calls per ticker per run

    def test_only_model_symbols_predict(self):
        inner = self.d["States"]["ProcessWatchlist"]["ItemProcessor"]["States"]
        route = json.dumps(inner["RouteModel"]["Choices"])
        self.assertIn('"StringEquals": "AAPL"', route)
        for s in ("MSFT", "GOOGL", "AMZN", "NVDA"):
            self.assertNotIn(s, route)
        self.assertIn("new_jumps_count", route)  # suspicious jump -> no prediction
        self.assertEqual(inner["RouteModel"]["Default"], "ComputeSignals")

    def test_one_email_publish_per_run(self):
        sns = [n for n, st in all_states(self.d["States"]) if st.get("Resource") == "arn:aws:states:::sns:publish"]
        self.assertEqual(sorted(sns), ["PublishDigest", "PublishFailure"])
        # nothing inside the Map publishes
        inner = self.d["States"]["ProcessWatchlist"]["ItemProcessor"]["States"]
        self.assertFalse([n for n, st in inner.items() if "sns" in st.get("Resource", "")])

    def test_failure_message_never_needs_single_symbol(self):
        msg = self.d["States"]["PublishFailure"]["Parameters"]["Message.$"]
        self.assertNotIn("$.symbol,", msg)
        self.assertIn("$.symbols", msg)

    def test_paths_referenced_after_failures_always_exist(self):
        sel = self.d["States"]["ProcessWatchlist"]["ItemSelector"]
        for step in ("ingest", "prediction", "signals", "score"):
            self.assertEqual(sel[step], {"result": {}})

    def test_previous_definition_still_reproducible(self):
        with open(os.path.join(HERE, "..", "infra", "stepfunctions", "stock-prediction-pipeline.asl.json")) as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(bd.build(True))))


if __name__ == "__main__":
    unittest.main()
