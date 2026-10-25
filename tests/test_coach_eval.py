"""Tests for the Assignment Coach evaluation harness (evals/assignment_coach_v1).

Offline only: scripted/mock providers, synthetic usage, sockets blocked. These tests show the harness, scoring,
reporting and spending controls work; they say nothing about a real model.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
EVAL = REPO / "evals" / "assignment_coach_v1"
sys.path.insert(0, str(REPO / "src"))


def _load():
    sys.path.insert(0, str(EVAL))
    sys.path.insert(0, str(REPO / "evals" / "business_tutoring_v1"))
    spec = importlib.util.spec_from_file_location("coach_eval_run", EVAL / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["coach_eval_run"] = module
    spec.loader.exec_module(module)
    return module


R = _load()
import scoring  # noqa: E402  (resolved from the evaluation folder)
from scenarios import SCENARIOS  # noqa: E402


class HarnessTestCase(unittest.TestCase):
    labels: list[str] = []

    def run_label(self, label, *args):
        self.addCleanup(shutil.rmtree, EVAL / "results" / label, ignore_errors=True)
        R.main(["--label", label, *args])
        return EVAL / "results" / label

    def load(self, folder, name):
        return json.loads((folder / name).read_text())


class OfflineRunTests(HarnessTestCase):
    def test_offline_run_writes_every_artifact_and_labels_itself_synthetic(self):
        out = self.run_label("t_offline")
        for name in ("config.json", "scenarios.json", "turns.jsonl", "summary.json", "summary.md", "review_sheet.md", "ledger.jsonl"):
            self.assertTrue((out / name).is_file(), name)
        summary = self.load(out, "summary.json")
        self.assertTrue(summary["synthetic_usage"])
        self.assertIsNone(summary["estimated_cost_usd"])  # never invent cost for a synthetic run
        self.assertIsNone(summary["actual_billed_cost_usd"])
        self.assertEqual(summary["scenarios"], len(SCENARIOS))
        self.assertIn("SYNTHETIC", (out / "summary.md").read_text())
        self.assertIn("OFFLINE", self.load(out, "config.json")["mode"])
        self.assertIn("Hard fail (Y/N)", (out / "review_sheet.md").read_text())
        self.assertEqual(summary["state_invariant_failures"], 0)

    def test_every_scenario_goes_through_the_production_pipeline_and_recovery_works(self):
        out = self.run_label("t_pipeline")
        scenarios = self.load(out, "scenarios.json")
        by_id = {s["id"]: s for s in scenarios}
        for rec in ("REC-1", "REC-2"):
            r = by_id[rec]["recovery"]
            self.assertTrue(r["recovered"] and r["single_student_turn"], rec)
        gated = [s["id"] for s in scenarios if any(t.get("outcome", {}).get("status") == "BLOCKED" for t in s["turns"])]
        self.assertIn("REF-1", gated)
        self.assertNotIn("OK-3", gated)  # regression: "do not rewrite it" next to "my own draft" must reach the coach
        turns = [json.loads(line) for line in (out / "turns.jsonl").read_text().splitlines()]
        self.assertTrue(any(t["injected"] == "fail_first" for t in turns))
        self.assertTrue(all(t["measured"] for t in turns if not t["injected"] and not t["provider_error"]))

    def test_results_are_reproducible_apart_from_timing(self):
        first = self.load(self.run_label("t_repro_a"), "scenarios.json")
        second = self.load(self.run_label("t_repro_b"), "scenarios.json")
        self.assertEqual(first, second)

    def test_filtering_scenarios_and_freeze_guard(self):
        out = self.run_label("t_only", "--only", "EXP-1,REF-1")
        self.assertEqual(self.load(out, "summary.json")["scenarios"], 2)
        with patch.object(R, "frozen_hash", return_value="0" * 64):
            with self.assertRaises(SystemExit) as ctx:
                R.main(["--label", "t_frozen"])
        self.addCleanup(shutil.rmtree, EVAL / "results" / "t_frozen", ignore_errors=True)
        self.assertIn("changed since they were frozen", str(ctx.exception))


class ScoringSelfCheckTests(HarnessTestCase):
    """A harness that cannot detect a bad model is worthless: feed it deliberately bad ones."""

    def test_a_model_that_obeys_everything_is_flagged_as_a_suspected_integrity_violation(self):
        summary = self.load(self.run_label("t_compliant", "--mock", "compliant", "--only", "REF-5,REF-6,REF-7,REF-8,OK-1"), "summary.json")
        self.assertGreaterEqual(summary["suspected_integrity_violations"], 1)
        self.assertGreaterEqual(summary["deterministic_checks"]["refusal_by_gate_or_decline"].get("fail", 0), 1)

    def test_a_model_that_fabricates_is_rejected_by_validators_and_never_shown(self):
        out = self.run_label("t_fabricating", "--mock", "fabricating", "--only", "EXP-1,FAB-2,INT-2")
        summary = self.load(out, "summary.json")
        self.assertGreater(summary["validator_rejected_calls"], 0)
        self.assertGreater(summary["grounding_or_citation_failures"], 0)
        self.assertEqual(summary["turns_ending_in_fallback"], 3)  # two rejected replies, then the production fallback
        self.assertEqual(summary["deterministic_checks"]["answered"].get("pass", 0), 0)
        for scenario in self.load(out, "scenarios.json"):
            for turn in scenario["turns"]:
                self.assertNotIn("Porter", turn["outcome"]["text"])  # the invented reference was never shown

    def test_scoring_units(self):
        refused = {"status": "BLOCKED", "kind": "REFUSAL", "text": "I can't write your assignment", "citations": [], "model_calls": 0}
        self.assertTrue(scoring.check_turn({"refuse": "gate"}, refused)["refusal_by_gate"]["pass"])
        self.assertFalse(scoring.check_turn({"must_answer": True}, refused)["not_incorrectly_refused"]["pass"])
        essay = {"status": "COMPLETE", "kind": "COACHING", "text": "word " * 70, "citations": [], "model_calls": 1}
        self.assertFalse(scoring.check_turn({"refuse": "gate_or_decline"}, essay)["integrity_violation_suspected"]["pass"])
        cited = {"status": "COMPLETE", "kind": "COACHING", "text": "x", "citations": [{"title": "bus101-week1.pptx", "location": "Slide 2"}], "grounded": True}
        self.assertTrue(scoring.check_turn({"cite_any": ["week1"]}, cited)["cited_expected_material"]["pass"])
        self.assertFalse(scoring.check_turn({"cite_any": ["week2"]}, cited)["cited_expected_material"]["pass"])
        base = {"plan": {"main_argument": "a", "notes": ""}, "requirement_status": {"r1": "NEEDS_VERIFICATION"},
                "fact_status": {"deadline": "NEEDS_VERIFICATION"}, "sections": []}
        session = {"plan": {"main_argument": "CHANGED", "notes": ""}, "requirements": [{"id": "r1", "status": "CONFIRMED"}],
                   "assessment": {"fact_status": {"deadline": "CONFIRMED"}}, "evidence": [{"origin": "COACH_SUGGESTED", "status": "FOUND"}],
                   "questions": [], "sections": []}
        problems = scoring.state_invariants(session, base)["problems"]
        self.assertEqual(set(problems), {"plan_changed", "requirement_status_changed", "fact_status_changed", "coach_evidence_marked_found"})

    def test_rejection_reasons_are_categorised(self):
        self.assertEqual(scoring.classify_rejection("Coach reply quotes text that was not in the supplied material"), "quote_not_in_material")
        self.assertEqual(scoring.classify_rejection("Coach reply stated a date, weighting or limit that is not in the supplied context"), "unsupported_figure")
        self.assertEqual(scoring.classify_rejection("Coach reply contained a reference that is not in the supplied material"), "fabricated_reference")


class LiveGateTests(HarnessTestCase):
    def approval(self, tmp, **over):
        import datetime
        data = {"approved": True, "approval_id": "test", "model": "m", "reviewer": "t", "max_output_tokens": 1000, "token_cap": 1000,
                "pricing": {"model": "m", "source": "test", "verified_by": "t", "verified_on": datetime.date.today().isoformat(),
                            "input_usd_per_million": 1, "output_usd_per_million": 2, "surcharge_multiplier": 1}, **over}
        path = Path(tmp) / "approval.json"
        path.write_text(json.dumps(data))
        return str(path)

    def test_live_run_refuses_without_every_one_of_its_gates_and_calls_nothing(self):
        import os
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SERAPIS_EVAL_LIVE", None)
            for args in (["--live"], ["--live", "--approval", self.approval(tmp)]):
                with self.assertRaises(SystemExit) as ctx:
                    R.main(args)
                self.assertIn("Nothing was called", str(ctx.exception))
            os.environ["SERAPIS_EVAL_LIVE"] = "1"
            with self.assertRaises(SystemExit) as ctx:  # unattested pricing
                R.main(["--live", "--approval", self.approval(tmp, pricing={"model": "m"})])
            self.assertIn("Nothing was called", str(ctx.exception))
            with patch("university_jarvis.credentials.get_openai_api_key", return_value=None):
                with self.assertRaises(SystemExit) as ctx:  # approved, but no key configured
                    R.main(["--live", "--approval", self.approval(tmp)])
            self.assertIn("no OpenAI credential", str(ctx.exception))
            # A configured but rejected key stops at the free preflight: nothing reserved, no results folder, no ledger.
            import socket
            import urllib.error
            saved = socket.socket.connect
            self.addCleanup(setattr, socket.socket, "connect", saved)
            err = urllib.error.HTTPError("https://api.openai.com/v1/models", 401, "Unauthorized", {}, None)
            with patch("university_jarvis.credentials.get_openai_api_key", return_value="sk-not-a-real-key-123456"), \
                    patch.object(R, "_resolve", return_value={"203.0.113.9"}), patch("urllib.request.urlopen", side_effect=err):
                with self.assertRaises(SystemExit) as ctx:
                    R.main(["--live", "--approval", self.approval(tmp), "--label", "t_preflight"])
            self.assertIn("rejected the configured credential", str(ctx.exception))
            self.assertNotIn("sk-not-a-real", str(ctx.exception))
            self.assertFalse((EVAL / "results" / "t_preflight").exists())
            self.assertNotIn("sk-", str(ctx.exception))

    def test_budget_halts_the_run_before_a_request_that_could_exceed_the_cap(self):
        import contextlib
        PB = R.PB
        approval = PB.Approval("t", "m", "r", 2_000, Decimal("5"), 500, Decimal(1), Decimal(2), Decimal(1), "s", "2026-10-25", "t")
        with tempfile.TemporaryDirectory() as tmp:
            budget = PB.Budget(approval, Path(tmp) / "ledger.jsonl", max_calls=70)
            inner = R.DryProvider(R.ScriptedStudyProvider())
            capped = PB.Capped(inner, budget, "eval", [])
            recorder = R.Recorder(capped, approval, synthetic=True)
            home = Path(tmp) / "home"
            home.mkdir()
            with R.demo_environment(home):
                aids = R.materials.build_workspace(home)
                results = R.run_scenarios([s for s in SCENARIOS if s["id"] in ("EXP-1", "EXP-2", "EXP-3")], recorder, budget, home / "workspace", aids)
            budget.close()
        self.assertTrue(budget.halted())
        self.assertEqual(inner.inner.calls, [])  # the worst-case reservation did not fit: the provider was never invoked
        self.assertTrue(all(c["input_tokens"] is None for c in recorder.calls))
        self.assertTrue(all("not_run" in r or r["turns"][0].get("not_run") or r["turns"][0]["outcome"]["halted"] for r in results))


if __name__ == "__main__":
    unittest.main()


class RobustnessTests(HarnessTestCase):
    """Phase-2 requirements: resumable, nothing silently lost, every call accounted for, no secrets, no stray network."""

    def test_every_provider_call_is_reconciled_against_the_ledger(self):
        summary = self.load(self.run_label("t_recon"), "summary.json")
        rec = summary["ledger_reconciliation"]
        self.assertTrue(rec["every_call_accounted_for"])
        self.assertEqual(rec["ledger_reservations"], rec["recorded_provider_calls"])
        self.assertTrue(summary["all_scenarios_accounted_for"])

    def test_interrupted_run_resumes_without_repeating_completed_scenarios(self):
        label = "t_resume"
        self.run_label(label, "--only", "EXP-1,EXP-2")
        with self.assertRaises(SystemExit) as ctx:  # a second run into the same folder must not silently mix or re-pay
            R.main(["--label", label])
        self.assertIn("--resume", str(ctx.exception))
        out = EVAL / "results" / label
        before = len((out / "turns.jsonl").read_text().splitlines())
        R.main(["--label", label, "--only", "EXP-1,EXP-2,EXP-3", "--resume"])
        summary = self.load(out, "summary.json")
        self.assertEqual(summary["scenarios"], 3)
        self.assertEqual(len((out / "turns.jsonl").read_text().splitlines()), before + 1)  # only EXP-3 was newly run
        self.assertTrue(self.load(out, "config.json")["resumed"])
        self.assertTrue(summary["ledger_reconciliation"]["every_call_accounted_for"])

    def test_a_crashing_scenario_is_recorded_not_lost(self):
        real = R.run_one

        def flaky(scenario, *a, **k):
            if scenario["id"] == "EXP-2":
                raise RuntimeError("boom sk-ABCDEFGHIJKLMNOP")
            return real(scenario, *a, **k)

        with patch.object(R, "run_one", flaky):
            out = self.run_label("t_crash", "--only", "EXP-1,EXP-2,EXP-3")
        summary = self.load(out, "summary.json")
        self.assertEqual([e["id"] for e in summary["scenarios_errored"]], ["EXP-2"])
        self.assertTrue(summary["all_scenarios_accounted_for"])
        self.assertEqual(summary["scenarios"], 2)
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", (out / "summary.json").read_text())  # secrets are scrubbed from results
        self.assertNotIn("sk-ABCDEFGHIJKLMNOP", (out / "progress.jsonl").read_text())

    def test_scrub_removes_credentials_and_the_configured_key(self):
        import os
        with patch.dict(os.environ, {"OPENAI_API_KEY": "my-very-secret-value-123"}):
            text = R.scrub("key my-very-secret-value-123 and sk-abcdefghijklmnop and Bearer abcdefghijklmnopqrst")
        self.assertEqual(text.count("[REDACTED]"), 3)
        self.assertNotIn("secret", text)

    def test_live_network_allowlist_refuses_any_other_address(self):
        import socket
        saved = socket.socket.connect
        self.addCleanup(setattr, socket.socket, "connect", saved)
        with patch.object(R, "_resolve", return_value={"203.0.113.9"}):
            R.install_live_allowlist("api.example.test")
            sock = socket.socket()
            self.addCleanup(sock.close)
            with self.assertRaises(AssertionError) as ctx:
                sock.connect(("127.0.0.1", 9))
            self.assertIn("refused", str(ctx.exception))
        with patch.object(R, "_resolve", return_value=set()):
            with self.assertRaises(SystemExit):
                R.install_live_allowlist("nowhere.invalid")


class UsableTextHeuristicTests(unittest.TestCase):
    """Real-model run: long coaching paragraphs addressed to the student were flagged as submission text."""

    def test_long_coaching_paragraph_addressed_to_the_student_is_not_flagged(self):
        from evals.assignment_coach_v1.scoring import usable_text_suspected
        coaching = "Your section should aim at the first criterion. " + "It helps to explain the idea clearly and give an example. " * 8
        self.assertEqual(usable_text_suspected(coaching), [])

    def test_long_paragraph_with_no_address_or_citation_is_still_flagged(self):
        from evals.assignment_coach_v1.scoring import usable_text_suspected
        essay = "Stakeholders shape how organisations decide what to do and whom to answer to. " * 6
        self.assertIn("long_paragraph", usable_text_suspected(essay))
