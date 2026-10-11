"""Business Tutoring Evaluation V1: the harness is offline, frozen, reproducible and honest about what it measures.

These tests do not assert that Serapis teaches well (nothing offline can). They assert that the evaluation
framework is well formed and that the deterministic safeguards it exercises behave as recorded.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1] / "evals" / "business_tutoring_v1"
sys.path.insert(0, str(EVAL))

import packs as P  # noqa: E402
import rubrics as RB  # noqa: E402
import tasks as T  # noqa: E402

SUBJECTS = {"Accounting", "Finance", "Economics", "Marketing", "Management"}


def run(out: Path) -> dict:
    subprocess.run([sys.executable, str(EVAL / "run_eval.py"), "--out", str(out)], check=True, capture_output=True)
    return json.loads((out / "results.json").read_text())


class FrameworkShape(unittest.TestCase):
    def test_packs_cover_five_subjects_two_each(self):
        counts = {s: sum(p["subject"] == s for p in P.PACKS.values()) for s in SUBJECTS}
        self.assertEqual(counts, {s: 2 for s in SUBJECTS})
        self.assertEqual(len(P.PACKS), 10)
        for pack in P.PACKS.values():
            self.assertEqual(len(pack["pages"]), 3)

    def test_task_count_and_coverage(self):
        self.assertTrue(20 <= len(T.TASKS) <= 30)
        self.assertEqual(len({t["id"] for t in T.TASKS}), len(T.TASKS))
        for subject in SUBJECTS:
            caps = {t["capability"] for t in T.TASKS if P.PACKS[t["pack"]]["subject"] == subject}
            self.assertEqual(caps, set(T.CAPABILITIES), subject)

    def test_every_task_is_frozen_with_reference_misconceptions_and_responses(self):
        for t in T.TASKS:
            self.assertTrue(t["reference"] and t["reference_explanation"] and t["common_misconceptions"], t["id"])
            self.assertTrue(set(t["cite_pages"]) <= {1, 2}, t["id"])
            kinds = {r["kind"] for r in t["responses"]}
            self.assertTrue(kinds <= set(T.EXPECTED_BY_KIND), t["id"])
            self.assertIn("correct", kinds | {"correct_hedged"}, t["id"])
            for r in t["responses"]:
                if r["kind"] == "misconception":
                    self.assertIn(r["quote"].lower(), r["text"].lower(), t["id"])

    def test_scripted_kinds_include_all_required_student_types(self):
        kinds = {r["kind"] for t in T.TASKS for r in t["responses"]}
        self.assertEqual(kinds, set(T.EXPECTED_BY_KIND))

    def test_rubrics_cover_all_four_capabilities_and_claim_no_scores(self):
        self.assertEqual(set(RB.RUBRICS), set(T.CAPABILITIES))
        self.assertEqual(RB.STATUS, "NOT YET EVALUATED")
        for rubric in RB.RUBRICS.values():
            self.assertTrue(rubric["dimensions"] and rubric["hard_fails"] and rubric["assessor"])


class Run(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.first = run(Path(cls.tmp.name) / "a")
        cls.second = run(Path(cls.tmp.name) / "b")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reproducible_and_matches_committed_results(self):
        self.assertEqual(self.first, self.second)
        committed = json.loads((EVAL / "results" / "after_triage" / "results.json").read_text())
        outcomes = lambda r: {c["case_id"]: c["outcome"] for c in r["cases"]}  # noqa: E731
        self.assertEqual(outcomes(self.first), outcomes(committed),
                         "production behaviour changed: re-run run_eval.py and review the diff in results/")

    def test_first_run_baseline_is_preserved(self):
        base = json.loads((EVAL / "results" / "results.json").read_text())
        self.assertEqual((base["totals"]["pass"], base["totals"]["fail"]), (309, 20))
        self.assertEqual((EVAL / "results" / "frozen.sha256").read_text().strip(), base["fingerprints"]["frozen_inputs_sha256"])

    def test_frozen_inputs_unchanged(self):
        self.assertTrue(self.first["fingerprints"]["frozen_inputs_unchanged_since_freeze"])

    def test_results_are_labelled_and_teaching_quality_is_not_scored(self):
        self.assertIn("NOT teaching quality", self.first["label"])
        for cap, v in self.first["not_yet_evaluated"].items():
            self.assertEqual(v["status"], "NOT YET EVALUATED", cap)
        text = json.dumps(self.first).lower()
        for banned in ("teaching_quality_score", "improvement", "mastery"):
            self.assertNotIn(banned, text)

    def test_safeguards_hold_on_every_authored_case(self):
        """Invariants the harness expects production to keep. A regression here is a real safety regression."""
        must_pass = {"leak_verbatim", "leak_verbatim_explanation", "legit_feedback_shown", "citation_to_unsupplied_page",
                     "false_accusation_fabricated_quote", "teach_me_opens", "adaptive_request", "question_reworded",
                     "question_leaky"}
        for c in self.first["cases"]:
            if c["probe"] in must_pass:
                self.assertEqual(c["outcome"], "PASS", c["case_id"])

    def test_known_gaps_are_recorded_not_hidden(self):
        fails = {c["probe"] for c in self.first["cases"] if c["outcome"] == "FAIL"}
        self.assertIn("leak_paraphrase", fails)
        self.assertIn("false_accusation_real_quote", fails)
        self.assertEqual(self.first["totals"]["fail"], sum(self.first["failures_by_class"].values()))

    def test_no_case_uses_the_network_or_a_live_provider(self):
        for c in self.first["cases"]:
            self.assertNotIn("openai", json.dumps(c).lower())


class PilotMachinery(unittest.TestCase):
    """The live pilot is prepared, not run. These tests use only the scripted dry run."""

    def run_py(self, *args, env=None):
        import os
        return subprocess.run([sys.executable, str(EVAL / "pilot_runner.py"), *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})})

    def test_live_refuses_without_flag_env_and_approval(self):
        for args, env in ((("--live",), {}), (("--live",), {"SERAPIS_PILOT_LIVE": "1"})):
            r = self.run_py(*args, env=env)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Nothing was called", r.stderr + r.stdout)

    def test_live_refuses_unapproved_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.json"
            f.write_text(json.dumps({"approved": False, "model": "m", "reviewer": "r"}))
            r = self.run_py("--live", "--approval", str(f), env={"SERAPIS_PILOT_LIVE": "1"})
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Nothing was called", r.stderr + r.stdout)

    def test_dry_run_measures_tokens_and_cap_halts(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_py("--dry-run", "--token-cap", "1000", "--out", d)
            self.assertEqual(r.returncode, 0, r.stderr)
            summary = json.loads(r.stdout)
            self.assertTrue(summary["mode"].startswith("DRY RUN"))
            self.assertEqual(summary["unmeasured_calls"], 0)
            self.assertEqual(len(summary["tasks"]), 8)
            self.assertTrue(summary["halted"], "the cap must halt the run")
            self.assertLessEqual(summary["token_cap"], 600_000)


if __name__ == "__main__":
    unittest.main()
