"""Phase 2 review: citation pages, unsupported questions and evaluation bias.

Synthetic data only; no provider, network or real student material.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_retrieval import _Fixture, _lecture_pages  # noqa: E402
from test_teach import TeachProvider, TeachTests, week_context  # noqa: E402

from university_jarvis import hub_service  # noqa: E402
from university_jarvis import sources as sources_module  # noqa: E402
from university_jarvis.reasoning import (  # noqa: E402
    ReasoningError,
    _validate_citation_pages,
    build_reasoning_context,
    supplied_units,
)
from university_jarvis.state import StateError  # noqa: E402
from university_jarvis.workflows import _load_sources  # noqa: E402
from university_jarvis.workspace import teach_week  # noqa: E402


class CitationPageTests(unittest.TestCase):
    UNITS = {"LEC": {37}, "DECK": {2}}

    def _cite(self, source_id, page):
        return {"x": [{"provenance": [{"source_id": source_id, "pdf_page": page}]}]}

    def test_supplied_page_and_slide_are_accepted(self) -> None:
        _validate_citation_pages(self._cite("LEC", 37), self.UNITS)
        _validate_citation_pages(self._cite("DECK", 2), self.UNITS)

    def test_unsupplied_page_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReasoningError, "not supplied"):
            _validate_citation_pages(self._cite("LEC", 12), self.UNITS)

    def test_page_from_another_source_is_rejected(self) -> None:
        with self.assertRaises(ReasoningError):
            _validate_citation_pages(self._cite("DECK", 37), self.UNITS)

    def test_null_page_keeps_existing_format(self) -> None:
        _validate_citation_pages(self._cite("LEC", None), self.UNITS)

    def test_supplied_units_come_from_retrieved_excerpts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fx = _Fixture(Path(directory))
            _, contexts = fx.load("kinked demand curve")
        units = supplied_units(contexts)
        self.assertIn(37, units["LEC"])
        self.assertIn(2, units["DECK"])
        self.assertNotIn(1, units["DECK"])
        self.assertNotIn(12, units["LEC"])

    def test_truth_safeguards_and_no_locator_survive_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fx = _Fixture(Path(directory))
            prepared, contexts = fx.load("kinked demand curve")
            context = week_context("TEACH")
            context["sources"] = prepared
            context["source_contexts"] = contexts
            context["truth_sources"] = prepared
            reasoning = build_reasoning_context(context)
            self.assertIn("module_facts", reasoning)
            self.assertTrue(reasoning["module_facts"]["unknown"])
            self.assertTrue(all("locator" not in s for s in reasoning["sources"]))
            self.assertNotIn(directory, json.dumps(reasoning))


class TeachNoMatchTests(unittest.TestCase):
    def _run(self, status, topic):
        context = week_context("TEACH")
        for source_context in context["source_contexts"]:
            source_context["retrieval"] = {"status": status}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir, workspace_root = TeachTests(
                "test_explicit_topic_is_grounded_adaptive_cached_and_state_neutral"
            )._workspace(root)
            record_path = workspace_root / "SYN101" / "week-01" / "academic-record.json"
            before = record_path.read_text(encoding="utf-8")
            provider = TeachProvider()
            error = None
            with patch("university_jarvis.workspace.build_week_context", return_value=context) as build:
                try:
                    teach_week({}, "SYN101", 1, topic=topic, provider=provider,
                               cache_dir=cache_dir, workspace_root=workspace_root)
                except StateError as exc:
                    error = exc
            return error, provider, build, before == record_path.read_text(encoding="utf-8")

    def test_unsupported_topic_refuses_without_model_call_or_record_change(self) -> None:
        error, provider, _build, unchanged = self._run("no_match", "photosynthesis")
        self.assertIsNotNone(error)
        self.assertIn("photosynthesis", str(error))
        self.assertIn("lecturer", str(error))
        self.assertEqual(provider.calls, [])
        self.assertTrue(unchanged)

    def test_matched_retrieval_proceeds_and_query_carries_the_topic(self) -> None:
        error, provider, build, _ = self._run("matched", "question framing vs evidence checking")
        self.assertIsNone(error)
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("question framing", build.call_args.kwargs["query"])


class _EvalProvider:
    def __init__(self, location="Slide 2 (Kinked demand)") -> None:
        self.calls = []
        self.location = location

    def cache_identity(self):
        return {"provider": "fake", "model": "fake"}

    def generate_structured_output(self, context, instructions, output_format):
        self.calls.append(context)
        return {"outcome": "NOT_SUPPORTED", "reason": "x",
                "evidence_references": [{"source_id": "DECK", "location": self.location}]}


class EvaluationTests(unittest.TestCase):
    TASK = "Why is the kinked demand curve associated with sticky prices?"
    EXPECTED = "Rivals match price cuts but not rises, so demand is kinked."
    MISLEADING = "Firms are price takers and face a flat demand curve under perfect competition."

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = _Fixture(Path(self._tmp.name))
        self.digest = hashlib.sha256(self.fx.deck_path.read_bytes()).hexdigest()
        self.fingerprint = {"algorithm": "sha256", "value": self.digest}

    def _attempt(self, refs=None, task=None, expected=None):
        return {"attempt_id": "a1", "task": task or self.TASK,
                "expected_answer": expected or self.EXPECTED,
                "student_response": self.MISLEADING, "assistance_status": "UNAIDED",
                "prompt_help": [], "evaluation": None,
                "source_references": refs if refs is not None else [
                    {"source_id": "DECK", "pdf_page": 2, "fingerprint": self.fingerprint}]}

    def _build(self, state, module, week, workflow, *, query, source_ids, pinned):
        with mock.patch.object(sources_module, "extract_pdf_text", return_value={
                "method": sources_module.PDF_EXTRACTION_METHOD, "page_count": 40,
                "pages": _lecture_pages()}):
            prepared, contexts = _load_sources(self.fx.state, source_ids, query, pinned)
        return {"sources": prepared, "source_contexts": contexts}

    def _evaluate(self, attempt, provider):
        saved = {}

        def save(module, week, attempt_id, evaluation, root=None):
            saved.update(evaluation)
            return {"evaluation": evaluation}

        record = {"learning": {"evidence": [copy.deepcopy(attempt)]}}
        error = None
        with patch.object(hub_service, "_learning_record", return_value=(record, None, None, None)), \
             patch.object(hub_service, "build_week_context", side_effect=self._build) as builder, \
             patch.object(hub_service, "save_learning_evaluation", side_effect=save):
            try:
                hub_service.evaluate_learning_attempt("SYN101", 1, "a1", state={}, provider=provider)
            except (StateError, ReasoningError) as exc:
                error = exc
        return saved, error, builder

    def test_misleading_response_does_not_steer_retrieval(self) -> None:
        provider = _EvalProvider()
        _, error, builder = self._evaluate(self._attempt(), provider)
        self.assertIsNone(error)
        self.assertNotIn("price takers", builder.call_args.kwargs["query"])
        pages = [e["pdf_page"] for c in provider.calls[0]["source_contexts"] for e in c["excerpts"]]
        self.assertIn(2, pages)

    def test_cited_slide_and_fingerprint_survive_even_if_query_misses(self) -> None:
        provider = _EvalProvider()
        attempt = self._attempt(task="Explain the idea in your own words.", expected="An idea.")
        _, error, builder = self._evaluate(attempt, provider)
        self.assertIsNone(error)
        context = provider.calls[0]["source_contexts"][0]
        self.assertIn(2, [e["pdf_page"] for e in context["excerpts"]])
        self.assertEqual(context["source_fingerprint"], self.digest)
        self.assertEqual(builder.call_args.kwargs["pinned"], [("DECK", 2)])

    def test_changed_source_fingerprint_is_still_refused(self) -> None:
        attempt = self._attempt(refs=[{"source_id": "DECK", "pdf_page": 2, "fingerprint": {"algorithm": "sha256", "value": "0" * 64}}])
        provider = _EvalProvider()
        _, error, _ = self._evaluate(attempt, provider)
        self.assertIsInstance(error, StateError)
        self.assertEqual(provider.calls, [])

    def test_missing_evidence_gives_unclear_without_model_call(self) -> None:
        provider = _EvalProvider()
        attempt = self._attempt(
            refs=[{"source_id": "DECK", "pdf_page": None, "fingerprint": self.fingerprint}],
            task="Describe photosynthesis.", expected="Chloroplasts.",
        )
        saved, error, _ = self._evaluate(attempt, provider)
        self.assertIsNone(error)
        self.assertEqual(provider.calls, [])
        self.assertEqual((saved["outcome"], saved["basis"]), ("UNCLEAR", "NO_EVIDENCE_RETRIEVED"))

    def test_evidence_location_must_be_a_supplied_slide(self) -> None:
        _, error, _ = self._evaluate(self._attempt(), _EvalProvider("Slide 1 (Course admin)"))
        self.assertIsInstance(error, ReasoningError)

    def test_correct_citation_after_retrieval_is_saved(self) -> None:
        saved, error, _ = self._evaluate(self._attempt(), _EvalProvider())
        self.assertIsNone(error)
        self.assertEqual(saved["basis"], "MODEL_JUDGEMENT")
        self.assertEqual(saved["evidence_references"][0]["location"], "Slide 2 (Kinked demand)")


if __name__ == "__main__":
    unittest.main()
