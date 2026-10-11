"""Live-pilot spending controls. Offline only: scripted providers, no network, no credentials, no model."""

from __future__ import annotations

import datetime
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

EVAL = Path(__file__).resolve().parents[1] / "evals" / "business_tutoring_v1"
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pilot_budget as PB  # noqa: E402

TODAY = datetime.date(2026, 10, 11)


def approval_data(**over):
    d = {"approved": True, "approval_id": "pilot-1", "model": "m-1", "reviewer": "owner", "max_output_tokens": 1_000,
         "token_cap": 100_000, "usd_cap": 1,
         "pricing": {"model": "m-1", "input_usd_per_million": 2, "output_usd_per_million": 8, "surcharge_multiplier": 1,
                     "source": "owner-checked pricing page", "verified_on": "2026-10-01", "verified_by": "owner"}}
    d.update(over)
    return d


def parse(**over):
    return PB.parse_approval(approval_data(**over), today=TODAY)


class Usage:
    def __init__(self, i, o):
        self.i, self.o = i, o

    def to_dict(self):
        return {"input_tokens": self.i, "output_tokens": self.o, "total_tokens": self.i + self.o}


class Provider:
    """Scripted provider. usage: Usage | None | Exception; records how often it was really called."""

    def __init__(self, usage=Usage(100, 50)):
        self.usage, self.calls, self.max_output_tokens, self.last_usage = usage, 0, None, None

    def cache_identity(self):
        return {"provider": "scripted", "model": "m-1"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls += 1
        if isinstance(self.usage, BaseException):
            raise self.usage
        self.last_usage = self.usage
        return {"ok": True}


def call(budget, provider, text="hello"):
    return PB.Capped(provider, budget, "t", []).generate_structured_output({"q": text}, "instr", {"type": "json_schema"})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "ledger.jsonl"
        self.addCleanup(self.tmp.cleanup)
        self.opened = []

    def budget(self, a=None, **kw):
        b = PB.Budget(a or parse(), self.ledger, **kw)
        self.opened.append(b)
        return b

    def tearDown(self):
        for b in self.opened:
            try:
                b.close()
            except OSError:
                pass


class ApprovalTests(Base):
    def test_caps_can_only_be_lowered(self):
        a = parse(token_cap=10_000_000, usd_cap=100)
        self.assertEqual((a.token_cap, a.usd_cap), (PB.HARD_TOKEN_CAP, PB.HARD_USD_CAP))
        a = parse(token_cap=1_000, usd_cap="0.5")
        self.assertEqual((a.token_cap, a.usd_cap), (1_000, Decimal("0.5")))

    def test_reopened_ledger_cannot_be_raised_by_a_new_approval_file(self):
        self.budget(parse(token_cap=5_000, usd_cap="0.5")).close()
        again = self.budget(parse(token_cap=500_000, usd_cap=4))
        self.assertEqual((again.token_cap, again.usd_cap), (5_000, Decimal("0.5")))

    def test_unknown_or_unverified_pricing_is_refused(self):
        bad_pricing = [None, {}, {**approval_data()["pricing"], "model": "other"},
                       {**approval_data()["pricing"], "verified_on": "2026-01-01"},
                       {**approval_data()["pricing"], "verified_on": "2027-01-01"},
                       {**approval_data()["pricing"], "input_usd_per_million": 0},
                       {**approval_data()["pricing"], "output_usd_per_million": "x"},
                       {**approval_data()["pricing"], "surcharge_multiplier": 0.5},
                       {**approval_data()["pricing"], "source": ""}, {**approval_data()["pricing"], "verified_by": ""}]
        for p in bad_pricing:
            with self.subTest(p=p), self.assertRaises(PB.ApprovalError):
                PB.parse_approval(approval_data(pricing=p), today=TODAY)

    def test_other_required_fields(self):
        for key in ("approval_id", "model", "reviewer", "max_output_tokens"):
            d = approval_data()
            del d[key]
            with self.subTest(key=key), self.assertRaises(PB.ApprovalError):
                PB.parse_approval(d, today=TODAY)
        for over in ({"approved": False}, {"approved": "yes"}, {"max_output_tokens": PB.HARD_MAX_OUTPUT_TOKENS + 1},
                     {"max_output_tokens": True}, {"token_cap": -1}):
            with self.subTest(over=over), self.assertRaises(PB.ApprovalError):
                PB.parse_approval(approval_data(**over), today=TODAY)


class GateTests(Base):
    def test_request_refused_before_sending_when_max_cost_exceeds_remaining_budget(self):
        b = self.budget(parse(usd_cap="0.001"))  # worst case of one call: 1000 output tokens alone = $0.008
        p = Provider()
        with self.assertRaises(PB.HaltedError):
            call(b, p)
        self.assertEqual(p.calls, 0)
        self.assertIsNotNone(b.halted())

    def test_token_cap_is_enforced_separately_from_dollars(self):
        b = self.budget(parse(token_cap=1_500))  # output limit 1000 + input overhead 1000 > 1500
        p = Provider()
        with self.assertRaises(PB.HaltedError):
            call(b, p)
        self.assertEqual(p.calls, 0)

    def test_cap_is_checked_cumulatively_before_every_request(self):
        b = self.budget(parse(token_cap=4_500))
        p = Provider(Usage(10, 10))
        call(b, p)                      # reserves ~2k, settles at 20
        call(b, p)
        spent_before = b.spent()[0]
        self.assertEqual(spent_before, 40)
        # an unsettled worst-case reservation (as after a crash) leaves too little room for the next one
        b.reserve("crashed", "i", {"q": 1}, {})
        with self.assertRaises(PB.BudgetRefused):
            for _ in range(5):
                b.reserve("next", "i", {"q": 1}, {})

    def test_every_request_carries_the_explicit_output_limit(self):
        b = self.budget()
        p = Provider()
        call(b, p)
        self.assertEqual(p.max_output_tokens, 1_000)

    def test_provider_without_hard_output_limit_is_refused(self):
        class Bare:
            def cache_identity(self): return {}
            def generate_structured_output(self, *a): return {}
        with self.assertRaises(PB.BudgetRefused):
            PB.Capped(Bare(), self.budget(), "t", [])

    def test_worst_case_input_bounds_multibyte_text(self):
        text = "é€😀" * 100
        self.assertGreaterEqual(PB.worst_case_input_tokens("", {"q": text}, {}), len(text.encode()) )


class HaltTests(Base):
    def test_missing_usage_stops_execution_and_charges_worst_case(self):
        b = self.budget()
        p = Provider(usage=None)
        call(b, p)
        self.assertIn("usage missing", b.halted())
        tokens, usd = b.spent()
        self.assertGreaterEqual(tokens, 1_000 + 1_000)  # worst case, not zero
        with self.assertRaises(PB.HaltedError):
            call(b, p)
        self.assertEqual(p.calls, 1)
        self.assertEqual(b.summary()["unmeasured_calls"], 1)

    def test_malformed_usage_is_treated_as_missing(self):
        b = self.budget()
        call(b, Provider(usage=SimpleNamespace(to_dict=lambda: {"input_tokens": "x", "output_tokens": 1})))
        self.assertIsNotNone(b.halted())

    def test_usage_above_reservation_halts(self):
        b = self.budget()
        call(b, Provider(usage=Usage(10**6, 5)))
        self.assertIn("exceeded", b.halted())

    def test_error_without_usage_is_charged_worst_case_and_halts(self):
        b = self.budget()
        p = Provider(usage=RuntimeError("network error after the request left"))
        with self.assertRaises(RuntimeError):
            call(b, p)
        self.assertGreaterEqual(b.spent()[0], 2_000)
        self.assertIsNotNone(b.halted())

    def test_error_with_reported_usage_is_charged_actual(self):
        b = self.budget()
        err = RuntimeError("truncated")
        err.usage = Usage(200, 1_000)
        with self.assertRaises(RuntimeError):
            call(b, Provider(usage=err))
        self.assertEqual(b.spent()[0], 1_200)
        self.assertIsNone(b.halted())

    def test_keyboard_interrupt_is_recorded(self):
        b = self.budget()
        with self.assertRaises(KeyboardInterrupt):
            call(b, Provider(usage=KeyboardInterrupt()))
        self.assertGreater(b.spent()[0], 0)
        self.assertIsNotNone(b.halted())


class PersistenceTests(Base):
    def test_restart_cannot_reset_spent_budget(self):
        b = self.budget()
        call(b, Provider(Usage(300, 100)))
        before = b.spent()
        b.close()
        again = self.budget()
        self.assertEqual(again.spent(), before)
        self.assertEqual(again.calls(), 1)

    def test_interrupted_run_counts_unsettled_reservation_at_worst_case(self):
        b = self.budget()
        r = b.reserve("t", "i", {"q": 1}, {})  # then the process dies: no settle
        b.close()
        again = self.budget()
        self.assertEqual(again.spent()[0], r["worst_tokens"])
        self.assertEqual(again.summary()["unsettled_reservations"], 1)

    def test_halt_survives_restart(self):
        b = self.budget()
        call(b, Provider(usage=None))
        b.close()
        again = self.budget()
        with self.assertRaises(PB.HaltedError):
            call(again, Provider())

    def test_retries_are_each_reserved_and_counted(self):
        b = self.budget(parse(token_cap=6_000))
        p = Provider(Usage(10, 10))
        n = 0
        with self.assertRaises(PB.HaltedError):
            while True:  # a retry loop cannot spend past the cap
                call(b, p)
                n += 1
        self.assertEqual(p.calls, n)
        self.assertLessEqual(b.spent()[0], 6_000)
        self.assertEqual(b.calls(), n)

    def test_ledger_of_another_approval_is_refused_not_reused(self):
        self.budget(parse(approval_id="a")).close()
        with self.assertRaises(PB.BudgetRefused):
            self.budget(parse(approval_id="b"))

    def test_concurrent_runs_on_one_ledger_are_refused(self):
        self.budget()
        with self.assertRaises(PB.BudgetRefused):
            PB.Budget(parse(), self.ledger)

    def test_corrupt_ledger_is_refused(self):
        self.ledger.write_text("{not json\n")
        with self.assertRaises(PB.BudgetRefused):
            PB.Budget(parse(), self.ledger)

    def test_call_limit(self):
        b = self.budget(max_calls=2)
        p = Provider(Usage(1, 1))
        call(b, p); call(b, p)
        with self.assertRaises(PB.HaltedError):
            call(b, p)


class ProviderTests(unittest.TestCase):
    """The only production change: an optional hard output limit. Default behaviour is unchanged."""

    def run_provider(self, limit, workflow="TUTOR_TURN"):
        from university_jarvis.reasoning import OpenAIReasoningProvider
        responses = MagicMock()
        responses.create.return_value = SimpleNamespace(
            status="completed", incomplete_details=None, output=[], output_text='{"a": 1}',
            usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2))
        provider = OpenAIReasoningProvider("m-1")
        if limit is not None:
            provider.max_output_tokens = limit
        with patch("university_jarvis.reasoning.get_openai_api_key", return_value="test-credential"), \
                patch("openai.OpenAI", return_value=SimpleNamespace(responses=responses)):
            provider.generate_structured_output({"workflow": workflow}, "i", {"type": "json_schema"})
        return responses.create.call_args.kwargs

    def test_default_sends_no_output_limit_for_tutor_workflows(self):
        self.assertNotIn("max_output_tokens", self.run_provider(None))

    def test_limit_is_sent_when_set(self):
        self.assertEqual(self.run_provider(1_000)["max_output_tokens"], 1_000)
        self.assertEqual(self.run_provider(1_000, "PREPARE_ME")["max_output_tokens"], 1_000)


if __name__ == "__main__":
    unittest.main()
