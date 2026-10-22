"""Structural tests for the final-run definition (parallel Signals/Score, skip on no new data). No AWS."""
import json
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "infra", "stepfunctions"))
sys.path.insert(0, os.path.join(HERE, "..", "src", "digest"))
import build_definition as bd  # noqa: E402
import lambda_function as digest  # noqa: E402


def scopes(states):
    """Yield every state dict-of-states scope (top level, Map processors, Parallel branches)."""
    yield states
    for st in states.values():
        if st["Type"] == "Map":
            yield from scopes(st["ItemProcessor"]["States"])
        if st["Type"] == "Parallel":
            for b in st["Branches"]:
                yield from scopes(b["States"])


def targets(st):
    out = [st.get("Next"), st.get("Default")] + [c.get("Next") for c in st.get("Choices", [])]
    out += [c.get("Next") for c in st.get("Catch", [])]
    return [t for t in out if t]


class TestParallelDefinition(unittest.TestCase):
    d = bd.build_parallel()
    w = bd.build_watchlist()
    inner = d["States"]["ProcessWatchlist"]["ItemProcessor"]["States"]

    def test_committed_file_matches_generator(self):
        with open(os.path.join(HERE, "..", "infra", "stepfunctions", "stock-prediction-pipeline.parallel.asl.json")) as f:
            self.assertEqual(json.load(f), json.loads(json.dumps(self.d)))

    def test_transitions_stay_in_scope_and_names_unique(self):
        names = []
        for sc in scopes(self.d["States"]):
            names += list(sc)
            for name, st in sc.items():
                for t in targets(st):
                    self.assertIn(t, sc, f"{name} -> {t}")
        self.assertEqual(len(names), len(set(names)))

    def test_alert_path_unchanged(self):
        for name in ("ValidateInput", "LegacyInput", "InvalidInput", "BuildDigest", "CheckDigest", "DigestFailed",
                     "DigestNeeded", "PublishDigest", "PublishFailure", "Failed", "Done"):
            self.assertEqual(self.d["States"][name], self.w["States"][name], name)
        pm, wm = dict(self.d["States"]["ProcessWatchlist"]), dict(self.w["States"]["ProcessWatchlist"])
        pm.pop("ItemProcessor"); wm.pop("ItemProcessor")
        self.assertEqual(pm, wm)
        for name in ("CheckSymbol", "TickerInvalid", "SpaceOutCalls", "WaitBetweenTickers", "IngestPrices", "Predict",
                     "TickerDone", "TickerIngestFailed", "TickerPredictionFailed", "TickerSignalsFailed", "TickerScoreFailed"):
            self.assertEqual(self.inner[name], self.w["States"]["ProcessWatchlist"]["ItemProcessor"]["States"][name], name)

    def test_skip_only_when_inserted_and_updated_are_both_zero(self):
        ch = self.inner["CheckNewData"]
        self.assertEqual(self.inner["CheckIngest"]["Choices"][0]["Next"], "CheckNewData")
        self.assertEqual(ch["Default"], "RouteModel")
        rule = ch["Choices"][0]
        self.assertEqual(rule["Next"], "NoNewData")
        conds = {(c["Variable"], k) for c in rule["And"] for k in c if k != "Variable"}
        for f in ("inserted", "updated"):
            for k in ("IsPresent", "IsNumeric", "NumericEquals"):
                self.assertIn((f"$.ingest.result.{f}", k), conds)
        self.assertNotIn("Or", json.dumps(rule))

    def test_skip_path_runs_no_prediction_and_no_signals(self):
        reach, todo = set(), ["NoNewData"]
        while todo:
            n = todo.pop()
            if n not in reach:
                reach.add(n)
                todo += targets(self.inner[n])
        self.assertNotIn("Predict", reach)
        self.assertNotIn("SignalsAndScore", reach)
        fns = {self.inner[n]["Parameters"]["FunctionName"].rsplit(":", 1)[1] for n in reach if self.inner[n]["Type"] == "Task"}
        self.assertEqual(fns, {"stock-evaluate"})

    def test_parallel_branches_catch_their_own_errors(self):
        par = self.inner["SignalsAndScore"]
        self.assertEqual(par["Type"], "Parallel")
        self.assertEqual(self.inner["RouteModel"]["Default"], "SignalsAndScore")
        self.assertEqual(self.inner["CheckPrediction"]["Choices"][0]["Next"], "SignalsAndScore")
        for b in par["Branches"]:
            for name, st in b["States"].items():
                if st["Type"] == "Task":
                    self.assertEqual(st["Catch"][0]["ErrorEquals"], ["States.ALL"])
                    self.assertTrue(b["States"][st["Catch"][0]["Next"]].get("End"), name)
        fns = [st["Parameters"]["FunctionName"].rsplit(":", 1)[1] for b in par["Branches"] for st in b["States"].values()
               if st["Type"] == "Task"]
        self.assertEqual(sorted(fns), ["stock-evaluate", "stock-signals"])
        route = self.inner["RouteAfterBranches"]["Choices"]
        self.assertEqual([c["Next"] for c in route], ["TickerSignalsFailed", "TickerScoreFailed"])

    def test_only_model_symbols_predict_or_score(self):
        self.assertIn('"StringEquals": "AAPL"', json.dumps(self.inner["RouteModel"]["Choices"]))
        score_route = json.dumps(self.d["States"]["ProcessWatchlist"]["ItemProcessor"]["States"]["SignalsAndScore"]["Branches"][1]["States"]["RouteScoreBranch"])
        self.assertIn('"StringEquals": "AAPL"', score_route)
        for s in ("MSFT", "GOOGL", "AMZN", "NVDA"):
            self.assertNotIn(s, score_route)
            self.assertNotIn(s, json.dumps(self.inner["NoNewData"]))

    def test_skipped_ticker_gives_no_misleading_digest_note_and_no_email(self):
        p = self.inner["TickerNoNewData"]["Parameters"]
        t = {"symbol": "AAPL", "ok": True, "ingest": {"inserted": 0, "updated": 0}, "prediction": p["prediction"],
             "signals": p["signals"], "score": {}}
        out = digest.build_digest([t], "x")
        self.assertFalse(out["send"])
        self.assertNotIn("suspicious", out["message"])


if __name__ == "__main__":
    unittest.main()
