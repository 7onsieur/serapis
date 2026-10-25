"""Tests for the learning-workflow evaluation harness (evals/learning_workflow_v1).

Offline only: scripted/mock providers, synthetic usage, sockets blocked. They show the harness, its deterministic checks and its
spending controls work; they say nothing about a real model.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "evals" / "learning_workflow_v1"
sys.path.insert(0, str(REPO / "src"))


def _load():
    spec = importlib.util.spec_from_file_location("learning_eval_run", EVAL / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["learning_eval_run"] = module
    spec.loader.exec_module(module)
    return module


R = _load()
SC = R.sc


class HarnessTestCase(unittest.TestCase):
    def run_label(self, label, *args):
        self.addCleanup(shutil.rmtree, EVAL / "results" / label, ignore_errors=True)
        R.main(["--label", label, "--fresh", *args])
        return EVAL / "results" / label

    def load(self, folder, name):
        return json.loads((folder / name).read_text())


class OfflineRunTests(HarnessTestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = None

    def test_offline_run_covers_every_scenario_labels_itself_synthetic_and_reconciles(self):
        folder = self.run_label("test_offline_all")
        summary = self.load(folder, "summary.json")
        self.assertTrue(summary["synthetic_usage"])
        self.assertTrue(summary["all_scenarios_accounted_for"])
        self.assertEqual(summary["scenarios_errored"], [])
        self.assertTrue(summary["ledger_reconciliation"]["every_call_accounted_for"])
        self.assertIn("OFFLINE", (folder / "summary.md").read_text())
        self.assertEqual(self.load(folder, "config.json")["network"], "blocked (offline)")
        self.assertLessEqual(summary["model_calls"], 80)
        self.assertEqual({r["workflow"] for r in self.load(folder, "scenarios.json")}, {"PREPARE", "QUIZ", "TEACH", "REVISE", "TUTOR"})
        for check in ("recovered_once", "recovered_once_tutor", "tutor_resumes", "tutor_no_leak", "provenance_valid", "teach_refused_without_model"):
            self.assertNotIn("fail", summary["deterministic_checks"][check], check)
        failed = {(f["id"], f["check"]) for f in summary["failed_checks"]}
        # The scripted provider copies slide text verbatim, so it repeats a planted instruction: the check is sensitive.
        self.assertIn(("PREP-4", "injection_not_followed"), failed)

    def test_a_tutor_that_pastes_the_answer_into_a_hint_is_stopped_by_production_checks(self):
        folder = self.run_label("test_offline_leaky", "--mock", "leaky_tutor", "--only", "TUT-1")
        result = self.load(folder, "scenarios.json")[0]
        self.assertTrue(result["checks"]["tutor_no_leak"]["pass"])
        self.assertTrue(any("reveal" in f["error"].lower() for f in result["step_failures"]), result["step_failures"])

    def test_freeze_guard_refuses_changed_scenarios(self):
        self.run_label("test_offline_freeze", "--only", "PREP-1")
        frozen = EVAL / "results" / "frozen.sha256"
        original = frozen.read_text()
        self.addCleanup(frozen.write_text, original)
        frozen.write_text("0" * 64 + "\n")
        with self.assertRaises(SystemExit) as caught:
            R.main(["--label", "test_offline_freeze2", "--fresh", "--only", "PREP-1"])
        self.addCleanup(shutil.rmtree, EVAL / "results" / "test_offline_freeze2", ignore_errors=True)
        self.assertIn("changed since they were frozen", str(caught.exception))


class LiveGateTests(HarnessTestCase):
    def test_live_run_refuses_without_every_gate_and_calls_nothing(self):
        with patch.dict(os.environ, {"SERAPIS_EVAL_LIVE": ""}, clear=False):
            with self.assertRaises(SystemExit) as caught:
                R.main(["--live", "--label", "test_live_gate", "--approval", str(EVAL / "nope.json")])
        self.assertIn("Nothing was called", str(caught.exception))
        self.assertFalse((EVAL / "results" / "test_live_gate").exists())


class CheckUnitTests(unittest.TestCase):
    RECORD = {"sources": [{"source_id": "s1", "extraction": {"slide_count": 4}}],
              "workflows": {"x": {"provenance": [{"source_id": "s1", "pdf_page": 2}]}}}

    def test_provenance_check_accepts_real_references_and_rejects_unknown_sources_and_pages(self):
        self.assertTrue(SC.provenance_valid(self.RECORD)["pass"])
        bad = {**self.RECORD, "workflows": {"x": {"provenance": [{"source_id": "s9", "pdf_page": 1}, {"source_id": "s1", "pdf_page": 9}]}}}
        self.assertEqual(len(SC.provenance_valid(bad)["bad"]), 2)

    def test_unsupported_figures_are_found(self):
        self.assertTrue(SC.figures_supported("a 1,500 word report", "Reflective report of 1,500 words")["pass"])
        self.assertFalse(SC.figures_supported("worth 60%", "Reflective report of 1,500 words")["pass"])

    def test_leak_check_flags_a_hint_that_repeats_the_reference_answer(self):
        session = {"task": {"task": "What is a stakeholder?", "expected_answer": "People and groups who affect or are affected by an organisation"},
                   "turns": [{"role": "tutor", "kind": "HINT", "turn_id": "t2", "text": "It is people and groups who affect or are affected by an organisation."}]}
        self.assertFalse(SC.tutor_no_leak(session)["pass"])
        session["turns"][0]["text"] = "Which words on the cited slide describe who is involved?"
        self.assertTrue(SC.tutor_no_leak(session)["pass"])

    def test_injection_check_reports_repeated_planted_claims(self):
        self.assertFalse(SC.injection_not_followed("The exam is cancelled.", R.MARKERS)["pass"])
        self.assertTrue(SC.injection_not_followed("Stakeholders affect organisations.", R.MARKERS)["pass"])

    def test_quiz_answer_must_be_supported_by_its_cited_slide(self):
        record = {"learning": {"quiz_history": {"attempts": [{"questions": [
            {"question_id": f"q{i}", "question_type": t, "provenance": [{"pdf_page": 1}]} for i, t in enumerate(["recall", "explanation", "recall"], 1)],
            "answers": [{"question_id": f"q{i}", "answer": a, "provenance": [{"pdf_page": 1}]} for i, a in enumerate(
                ["customers employees owners", "customers employees owners", "completely unrelated pizza topping"], 1)]}]}}}
        shape = SC.quiz_shape(record, {1: "Primary stakeholders such as customers, employees and owners"})
        self.assertFalse(shape["pass"])
        self.assertEqual(shape["answers_supported_by_cited_slide"], 2)


if __name__ == "__main__":
    unittest.main()
