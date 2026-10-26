"""Evidence-aware REVISE and TEACH, bounded retry with cost accounting, source aliasing, tutor leak regressions,
and the general-guidance versus source-grounded rule. Offline: fakes only, no network, no spending."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_teach as T  # noqa: E402
from test_reasoning import bounded_context  # noqa: E402

from university_jarvis import generation_retry as G  # noqa: E402
from university_jarvis import hub_service, learning_digest as D, reasoning as R, tutoring  # noqa: E402
from university_jarvis.reasoning import (  # noqa: E402
    OpenAIReasoningProvider, ReasoningError, TokenUsage, generate_prepare_brief, generate_teach_brief)
from university_jarvis.source_alias import AliasingProvider  # noqa: E402
from university_jarvis.tutor_policy import reveals_reference  # noqa: E402
from university_jarvis.workspace import (  # noqa: E402
    record_learning_attempt, save_learning_evaluation, teach_week)

REAL_A = "src-" + "a1" * 16
REAL_B = "src-" + "b2" * 16


# ---------------------------------------------------------------------------------------------------------
# generation_retry
# ---------------------------------------------------------------------------------------------------------
class Boom(Exception):
    def __init__(self, message="x", retryable=False, usage=None):
        super().__init__(message)
        self.retryable, self.usage = retryable, usage


class RunCheckedTests(unittest.TestCase):
    def run_it(self, outputs, check=lambda raw: raw, **kw):
        calls, notes = [], []
        queue = list(outputs)

        def call(note):
            notes.append(note)
            calls.append(1)
            item = queue.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        usage = lambda: {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}  # noqa: E731
        return calls, notes, lambda: G.run_checked(call, check, last_usage=usage, **kw)

    def test_a_retryable_failure_is_retried_once_and_both_calls_are_accounted(self):
        def check(raw):
            if raw == "bad":
                raise Boom("invalid", retryable=True)
            return raw
        calls, notes, go = self.run_it(["bad", "good"], check)
        outcome = go()
        self.assertEqual((outcome.value, len(calls)), ("good", 2))
        self.assertIsNone(notes[0])
        self.assertEqual(notes[1], "invalid")
        self.assertEqual(outcome.usage, {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30})
        self.assertEqual([a.error for a in outcome.attempts], ["invalid", None])

    def test_never_more_than_two_attempts(self):
        calls, _, go = self.run_it([Boom("a", True), Boom("b", True), Boom("c", True)])
        with self.assertRaises(Boom) as caught:
            go()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(caught.exception.attempts), 2)
        self.assertEqual(caught.exception.total_usage["total_tokens"], 30)

    def test_non_retryable_failures_make_exactly_one_call(self):
        for exc in (Boom("auth"), ValueError("unexpected"), Boom("limit", retryable=False)):
            with self.subTest(exc=str(exc)):
                calls, _, go = self.run_it([exc, "never used"])
                with self.assertRaises(type(exc)):
                    go()
                self.assertEqual(len(calls), 1)

    def test_no_retry_once_the_window_has_passed(self):
        times = iter([0.0, 500.0, 501.0, 502.0])
        calls, _, go = self.run_it([Boom("slow", True), "late"], clock=lambda: next(times))
        with self.assertRaises(Boom):
            go()
        self.assertEqual(len(calls), 1)

    def test_a_refused_charge_stops_the_retry_and_reports_the_original_failure(self):
        def refuse():
            raise RuntimeError("limit reached")
        calls, _, go = self.run_it([Boom("original", True), "second"], charge=refuse)
        with self.assertRaises(Boom) as caught:
            go()
        self.assertEqual((str(caught.exception), len(calls)), ("original", 1))

    def test_the_second_attempt_is_charged_but_the_first_is_not(self):
        charged = []
        _, _, go = self.run_it([Boom("a", True), "ok"], charge=lambda: charged.append(1))
        go()
        self.assertEqual(len(charged), 1)

    def test_cancellation_is_never_swallowed(self):
        calls, _, go = self.run_it([KeyboardInterrupt(), "ok"])
        with self.assertRaises(KeyboardInterrupt):
            go()
        self.assertEqual(len(calls), 1)


# ---------------------------------------------------------------------------------------------------------
# provider failure classification
# ---------------------------------------------------------------------------------------------------------
def api_error(name, status, code=None):
    cls = type(name, (Exception,), {})
    exc = cls("provider said something private")
    exc.status_code, exc.code = status, code
    return exc


class ProviderFailureTests(unittest.TestCase):
    def attempts_for(self, error):
        responses = Mock()
        responses.create.side_effect = error
        provider = OpenAIReasoningProvider()
        with tempfile.TemporaryDirectory() as tmp, \
                patch("university_jarvis.reasoning.get_openai_api_key", return_value="test-credential"), \
                patch("openai.OpenAI", return_value=SimpleNamespace(responses=responses)):
            with self.assertRaises(ReasoningError) as caught:
                generate_prepare_brief(bounded_context(), provider, Path(tmp))
        return responses.create.call_count, str(caught.exception)

    def test_authentication_and_billing_errors_are_never_retried(self):
        for error in (api_error("AuthenticationError", 401, "invalid_api_key"),
                      api_error("PermissionDeniedError", 403),
                      api_error("RateLimitError", 429, "insufficient_quota"),
                      api_error("APIStatusError", 402),
                      api_error("BadRequestError", 400)):
            with self.subTest(error=type(error).__name__ + str(error.status_code)):
                count, message = self.attempts_for(error)
                self.assertEqual(count, 1)
                self.assertIn("will not help", message.lower())
                self.assertNotIn("private", message)

    def test_busy_or_unreachable_service_is_retried_exactly_once(self):
        for error in (api_error("RateLimitError", 429, "rate_limit_exceeded"),
                      api_error("InternalServerError", 503), api_error("APITimeoutError", None),
                      api_error("APIConnectionError", None)):
            with self.subTest(error=type(error).__name__):
                count, message = self.attempts_for(error)
                self.assertEqual(count, 2)
                self.assertIn("Serapis tried twice", message)
                self.assertIn("Nothing was saved", message)

    def test_a_refusal_or_content_filter_or_truncation_is_not_retried(self):
        refusal = SimpleNamespace(status="completed", incomplete_details=None, output_text="",
                                  output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")])],
                                  usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2))
        filtered = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="content_filter"),
                                   output=[], output_text="", usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2))
        cut = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                              output=[], output_text="", usage=SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2))
        for response in (refusal, filtered, cut):
            with self.subTest(status=response.status):
                responses = Mock()
                responses.create.return_value = response
                with tempfile.TemporaryDirectory() as tmp, \
                        patch("university_jarvis.reasoning.get_openai_api_key", return_value="test-credential"), \
                        patch("openai.OpenAI", return_value=SimpleNamespace(responses=responses)):
                    with self.assertRaises(ReasoningError):
                        generate_prepare_brief(bounded_context(), OpenAIReasoningProvider(), Path(tmp))
                self.assertEqual(responses.create.call_count, 1)

    def test_every_request_uses_a_bounded_timeout(self):
        responses = Mock()
        responses.create.side_effect = api_error("AuthenticationError", 401)
        with tempfile.TemporaryDirectory() as tmp, \
                patch("university_jarvis.reasoning.get_openai_api_key", return_value="test-credential"), \
                patch("openai.OpenAI", return_value=SimpleNamespace(responses=responses)) as client:
            with self.assertRaises(ReasoningError):
                generate_prepare_brief(bounded_context(), OpenAIReasoningProvider(), Path(tmp))
        self.assertEqual(client.call_args.kwargs["timeout"], R.REQUEST_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------------------------------------
# bounded retry inside the generation pipeline
# ---------------------------------------------------------------------------------------------------------
def good_prepare():
    return T.prepare_brief()


class Scripted:
    """Returns queued outputs; records every context it was sent."""

    def __init__(self, *outputs):
        self.outputs, self.contexts = list(outputs), []
        self.last_usage = TokenUsage(100, 50, 150)

    def cache_identity(self):
        return {"provider": "fake", "model": "m"}

    def generate_structured_output(self, context, instructions, output_format):
        self.contexts.append(copy.deepcopy(context))
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


class PipelineRetryTests(unittest.TestCase):
    def prepare(self, provider):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            try:
                return generate_prepare_brief(T.week_context("PREPARE_ME"), provider, cache), cache, list(cache.iterdir())
            except ReasoningError as exc:
                exc.cache_files = list(cache.iterdir())
                raise

    def test_a_grounding_failure_is_retried_once_and_the_retry_is_validated_identically(self):
        wrong = good_prepare()
        wrong["core_concepts"][0]["provenance"] = [{"source_id": "not-a-supplied-source", "pdf_page": 4}]
        provider = Scripted(wrong, good_prepare())
        result, _, files = self.prepare(provider)
        self.assertEqual(len(provider.contexts), 2)
        self.assertIsNone(provider.contexts[0].get("previous_attempt_refused_because"))
        self.assertIn("not supplied", provider.contexts[1]["previous_attempt_refused_because"])
        self.assertEqual(result.usage, TokenUsage(200, 100, 300))  # both paid calls counted
        self.assertEqual([a["attempt"] for a in result.attempts], [1, 2])
        self.assertEqual(len(files), 1)  # one cache entry, written only for the validated output

    def test_the_retry_cannot_bypass_grounding(self):
        wrong = good_prepare()
        wrong["core_concepts"][0]["provenance"] = [{"source_id": "not-a-supplied-source", "pdf_page": 4}]
        provider = Scripted(wrong, copy.deepcopy(wrong), good_prepare())
        with self.assertRaises(ReasoningError) as caught:
            self.prepare(provider)
        self.assertEqual(len(provider.contexts), 2)  # bounded: the third output was never requested
        self.assertEqual(caught.exception.cache_files, [])
        self.assertEqual(caught.exception.usage, TokenUsage(200, 100, 300))
        self.assertIn("Serapis tried twice", str(caught.exception))
        self.assertIn("Nothing was saved", str(caught.exception))

    def test_an_unexpected_provider_error_is_not_retried(self):
        provider = Scripted(RuntimeError("disk on fire"), good_prepare())
        with self.assertRaises(RuntimeError):
            self.prepare(provider)
        self.assertEqual(len(provider.contexts), 1)

    def test_the_retry_note_never_changes_the_cache_key(self):
        provider = Scripted(good_prepare())
        context = T.week_context("PREPARE_ME")
        first = generate_prepare_brief(context, provider, Path(tempfile.mkdtemp()))
        wrong = good_prepare()
        wrong["core_concepts"] = "oops"
        flaky = Scripted(wrong, good_prepare())
        second = generate_prepare_brief(context, flaky, Path(tempfile.mkdtemp()))
        self.assertEqual(first.cache_key, second.cache_key)

    def test_a_failed_first_attempt_changes_no_student_state_and_teach_records_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir, workspace = T.TeachTests()._workspace(root)
            record_path = workspace / "SYN101" / "week-01" / "academic-record.json"
            bad = T.teach_brief()
            bad["teaching_sequence"][0]["provenance"] = []  # missing provenance: a recoverable model fault
            provider = Scripted(bad, T.teach_brief())
            with patch("university_jarvis.workspace.build_week_context", return_value=T.week_context("TEACH")):
                result = teach_week({}, "SYN101", 1, topic="question framing vs evidence checking",
                                    provider=provider, cache_dir=cache_dir, workspace_root=workspace)
            record = json.loads(record_path.read_text())
            interactions = record["workflows"]["teach"]["interactions"]
            self.assertEqual(len(interactions), 1)
            self.assertEqual(len(provider.contexts), 2)
            self.assertEqual(interactions[0]["generation"]["usage"]["total_tokens"], 300)  # both attempts
            self.assertEqual([a["attempt"] for a in interactions[0]["generation"]["attempts"]], [1, 2])
            self.assertEqual(result.teach_id, "teach-0001")

    def test_two_failed_teach_attempts_leave_the_record_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir, workspace = T.TeachTests()._workspace(root)
            record_path = workspace / "SYN101" / "week-01" / "academic-record.json"
            before = record_path.read_bytes()
            bad = T.teach_brief()
            bad["teaching_sequence"][0]["provenance"] = []
            provider = Scripted(bad, copy.deepcopy(bad))
            with patch("university_jarvis.workspace.build_week_context", return_value=T.week_context("TEACH")):
                with self.assertRaisesRegex(ReasoningError, "no provenance"):
                    teach_week({}, "SYN101", 1, topic="question framing vs evidence checking",
                               provider=provider, cache_dir=cache_dir, workspace_root=workspace)
            self.assertEqual(record_path.read_bytes(), before)


# ---------------------------------------------------------------------------------------------------------
# source aliasing
# ---------------------------------------------------------------------------------------------------------
class Echo:
    """Cites whatever alias it is told is first, plus anything scripted."""

    def __init__(self, reply=None):
        self.seen, self.reply = [], reply
        self.last_usage = TokenUsage(1, 1, 2)

    def cache_identity(self):
        return {"provider": "fake", "model": "echo"}

    def generate_structured_output(self, context, instructions, output_format):
        self.seen.append((copy.deepcopy(context), instructions, copy.deepcopy(output_format)))
        return self.reply(context) if callable(self.reply) else self.reply


def alias_context():
    return {"sources": [{"id": REAL_A, "title": "Week 1 slides.pptx"}, {"id": REAL_B, "title": "Reading.pdf"}],
            "source_contexts": [{"source_id": REAL_A, "excerpts": [{"pdf_page": 1, "text": "Stakeholders matter."}]},
                                {"source_id": REAL_B, "excerpts": []}],
            "prepare_me": {"result": {"x": [{"text": "t", "provenance": [{"source_id": REAL_B, "pdf_page": 2}]}]}}}


SCHEMA = {"type": "json_schema", "name": "n", "strict": True, "schema": {"type": "object", "properties": {
    "items": {"type": "array", "items": {"type": "object", "properties": {
        "text": {"type": "string"}, "source_id": {"type": "string"}}, "required": ["text", "source_id"]}}}}}


class SourceAliasTests(unittest.TestCase):
    def test_the_model_never_sees_a_real_id_and_the_schema_is_restricted_to_the_aliases(self):
        inner = Echo({"items": []})
        AliasingProvider(inner).generate_structured_output(alias_context(), "do it", SCHEMA)
        context, instructions, fmt = inner.seen[0]
        blob = json.dumps(context)
        self.assertNotIn("src-", blob)
        self.assertIn("SRC1", blob)
        enum = fmt["schema"]["properties"]["items"]["items"]["properties"]["source_id"]["enum"]
        self.assertEqual(enum, ["SRC1", "SRC2"])
        self.assertIn("SRC1", instructions)
        self.assertNotIn("enum", json.dumps(SCHEMA))  # the caller's schema object is untouched

    def test_output_is_translated_back_before_any_validator_sees_it(self):
        inner = Echo({"items": [{"text": "x", "source_id": "SRC2"}]})
        out = AliasingProvider(inner).generate_structured_output(alias_context(), "do it", SCHEMA)
        self.assertEqual(out["items"][0]["source_id"], REAL_B)

    def test_an_invented_alias_stays_invalid_and_is_rejected_by_the_citation_check(self):
        inner = Echo({"items": [{"text": "x", "source_id": "SRC9"}]})
        out = AliasingProvider(inner).generate_structured_output(alias_context(), "do it", SCHEMA)
        self.assertEqual(out["items"][0]["source_id"], "SRC9")
        with self.assertRaises(ReasoningError):
            R._validate_citation_ids({"provenance": [{"source_id": "SRC9", "pdf_page": 1}]}, {REAL_A, REAL_B})

    def test_a_miscopied_real_looking_id_is_still_rejected(self):
        miscopied = REAL_A[:-3] + "fff"
        inner = Echo({"items": [{"text": "x", "source_id": miscopied}]})
        out = AliasingProvider(inner).generate_structured_output(alias_context(), "do it", SCHEMA)
        with self.assertRaises(ReasoningError):
            R._validate_citation_ids({"provenance": [{"source_id": out["items"][0]["source_id"], "pdf_page": 1}]},
                                     {REAL_A, REAL_B})

    def test_an_alias_written_in_prose_becomes_the_file_name(self):
        inner = Echo({"items": [{"text": "See SRC1 page 2 and SRC2.", "source_id": "SRC1"}]})
        out = AliasingProvider(inner).generate_structured_output(alias_context(), "do it", SCHEMA)
        self.assertEqual(out["items"][0]["text"], "See Week 1 slides.pptx page 2 and Reading.pdf.")

    def test_usage_identity_and_attributes_pass_through(self):
        inner = Echo({"items": []})
        wrapper = AliasingProvider(inner)
        wrapper.generate_structured_output(alias_context(), "x", SCHEMA)
        self.assertEqual(wrapper.cache_identity(), inner.cache_identity())
        self.assertEqual(wrapper.last_usage, TokenUsage(1, 1, 2))
        self.assertIs(wrapper.seen, inner.seen)

    def test_context_without_sources_is_passed_through_unchanged(self):
        inner = Echo({"items": []})
        AliasingProvider(inner).generate_structured_output({"topic": "x"}, "do it", SCHEMA)
        self.assertEqual(inner.seen[0][0], {"topic": "x"})
        self.assertEqual(inner.seen[0][1], "do it")

    def test_the_live_revise_failure_no_longer_reaches_the_validator(self):
        """A 36-character id changed by one character is impossible when the model only chooses an alias."""
        ctx = T.week_context("REVISE")
        ctx["sources"][0]["id"] = REAL_A
        ctx["source_contexts"][0]["source_id"] = REAL_A
        brief = {f: [{"text": f"{f} text", "provenance": [{"source_id": "SRC1", "pdf_page": 4}]}] for f in
                 [f for f, _ in R.REVISE_WORKFLOW.sections]}
        inner = Echo(brief)
        result = R.generate_sectioned_brief(ctx, inner, R.REVISE_WORKFLOW, Path(tempfile.mkdtemp()))
        self.assertEqual(result.brief.sections["essential_knowledge"][0].provenance[0].source_id, REAL_A)


# ---------------------------------------------------------------------------------------------------------
# TEACH general guidance versus source-grounded
# ---------------------------------------------------------------------------------------------------------
class TeachBasisTests(unittest.TestCase):
    ALLOWED = {T.SOURCE_ID}

    def brief_with(self, **move):
        brief = T.teach_brief()
        brief["teaching_sequence"].append({
            "move_type": "likely_confusion", "title": "A common mix-up",
            "explanation": "Learners often blur the two terms; compare them side by side.",
            "why_it_follows": None, "provenance": [], "basis": "GENERAL_GUIDANCE", **move})
        for m in brief["teaching_sequence"][:-1]:
            m["basis"] = "SOURCE"
        return brief

    def test_the_live_failure_an_unsourced_likely_confusion_is_now_legitimate_but_labelled(self):
        brief = R.TeachBrief.from_dict(self.brief_with(), self.ALLOWED)
        self.assertEqual(brief.teaching_sequence[-1].basis, "GENERAL_GUIDANCE")
        text = R.render_teach_brief(brief, {"topic": "t"}, [], None)
        self.assertIn("General study guidance, not from your course materials", text)

    def test_a_source_move_without_provenance_is_still_rejected(self):
        brief = self.brief_with()
        brief["teaching_sequence"][0]["provenance"] = []
        with self.assertRaisesRegex(ReasoningError, "no provenance"):
            R.TeachBrief.from_dict(brief, self.ALLOWED)

    def test_a_likely_confusion_without_a_basis_must_still_cite(self):
        brief = self.brief_with()
        del brief["teaching_sequence"][-1]["basis"]
        with self.assertRaisesRegex(ReasoningError, "no provenance"):
            R.TeachBrief.from_dict(brief, self.ALLOWED)

    def test_general_guidance_cannot_carry_citations_or_be_any_other_move(self):
        cited = self.brief_with(provenance=[{"source_id": T.SOURCE_ID, "pdf_page": 4}])
        with self.assertRaisesRegex(ReasoningError, "must not carry source provenance"):
            R.TeachBrief.from_dict(cited, self.ALLOWED)
        other = self.brief_with(move_type="worked_example", why_it_follows="because")
        with self.assertRaisesRegex(ReasoningError, "Only a likely_confusion"):
            R.TeachBrief.from_dict(other, self.ALLOWED)
        invalid = self.brief_with(basis="MADE_UP")
        with self.assertRaisesRegex(ReasoningError, "Invalid TEACH move basis"):
            R.TeachBrief.from_dict(invalid, self.ALLOWED)

    def test_the_schema_requires_a_basis_and_the_prompt_explains_it(self):
        move = R.TEACH_FORMAT["schema"]["properties"]["teaching_sequence"]["items"]
        self.assertIn("basis", move["required"])
        self.assertEqual(move["properties"]["basis"]["enum"], ["SOURCE", "GENERAL_GUIDANCE"])
        self.assertIn("GENERAL_GUIDANCE", R.TEACH_INSTRUCTIONS)
        self.assertIn("must not invent deadlines", R.TEACH_INSTRUCTIONS)

    def test_a_legacy_stored_move_without_basis_still_reads_as_a_source_move(self):
        brief = R.TeachBrief.from_dict(T.teach_brief(), self.ALLOWED)
        self.assertTrue(all(m.basis == "SOURCE" for m in brief.teaching_sequence))


class GeneralGuidanceRuleTests(unittest.TestCase):
    def test_every_model_workflow_carries_the_same_rule(self):
        self.assertIn("General study advice (not from your", R.OBJECTIVE_INSTRUCTIONS)
        self.assertIn("never invent deadlines, marking criteria, references, quotations", R.OBJECTIVE_INSTRUCTIONS.replace("\n", " "))
        self.assertIn("do not\nappend a verification disclaimer", R.OBJECTIVE_INSTRUCTIONS)
        from university_jarvis.coach_integrity import COACH_INSTRUCTIONS
        self.assertIn("General\nadvice, not from your course materials:", COACH_INSTRUCTIONS)
        self.assertNotIn("use outside\nknowledge", COACH_INSTRUCTIONS)

    def test_an_uncited_item_is_marked_as_not_from_the_course_materials(self):
        item = R.BriefItem("Space your revision over several days.", [])
        grounded = R.BriefItem("Stakeholders affect the organisation.", [R.SourceReference(T.SOURCE_ID, 4)])
        absence = R.BriefItem("No assessment information was supplied.", [])
        labelled = R.BriefItem("General study advice (not from your course materials): test yourself.", [])
        lines = R._render_items([item, grounded, absence, labelled], None)
        self.assertTrue(lines[0].endswith(R.UNSOURCED_NOTE))
        self.assertFalse(lines[1].endswith(R.UNSOURCED_NOTE))
        self.assertFalse(lines[2].endswith(R.UNSOURCED_NOTE))  # a statement of absence is not an unsourced claim
        self.assertFalse(lines[3].endswith(R.UNSOURCED_NOTE))  # already labelled; no repeated disclaimer
