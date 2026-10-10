"""Phase 2: deterministic passage retrieval over synthetic academic sources.

All material is invented (a fictional economics course); nothing real is read
and no model is called.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_pptx_sources import _build_pptx, _slide_xml  # noqa: E402

from university_jarvis import sources as sources_module  # noqa: E402
from university_jarvis.reasoning import (  # noqa: E402
    build_reasoning_context,
    build_source_location_index,
)
from university_jarvis.retrieval import (  # noqa: E402
    RETRIEVAL_CHARACTER_LIMIT,
    build_passages,
    select_passages,
    split_passages,
    tokenize,
)
from university_jarvis.sources import render_source_location  # noqa: E402
from university_jarvis.workflows import _load_sources  # noqa: E402


def _lecture_pages() -> list[str]:
    """40 pages of generic 'market' prose; the answer to the test query is on page 37."""
    pages = []
    for number in range(1, 41):
        pages.append(
            f"Page {number} of the market structures lecture. In a market, firms compete "
            f"for customers and the market price adjusts. Topic note {number} reviews "
            "market definitions, market boundaries and market participants in general terms. "
            + "Further background on market behaviour continues here. " * 6
        )
    pages[36] = (
        "Oligopoly overview and introductory remarks on firm interdependence. " * 8
        + "Oligopoly and the kinked demand curve. Rivals match a price cut but ignore a price "
        "rise, so the kinked demand curve makes prices sticky. A marginal revenue gap sits "
        "beneath the kink, which explains why costs can change without a price change."
    )
    return pages


class _Fixture:
    def __init__(self, directory: Path) -> None:
        self.lecture_path = directory / "lecture.pdf"
        self.lecture_path.write_bytes(b"synthetic lecture bytes")
        self.deck_path = directory / "deck.pptx"
        _build_pptx(
            self.deck_path,
            sld_id_to_rid=[(1, "rId1"), (2, "rId2"), (3, "rId3")],
            rid_to_target=[(f"rId{i}", f"slides/slide{i}.xml") for i in (1, 2, 3)],
            slides_by_filename={
                "slide1.xml": _slide_xml(title="Course admin", body_lines=["Office hours and marking."]),
                "slide2.xml": _slide_xml(
                    title="Kinked demand",
                    body_lines=["Kinked demand curve: rivals follow price cuts, not price rises."],
                ),
                "slide3.xml": _slide_xml(title="Perfect competition", body_lines=["Price takers face a flat demand curve."]),
            },
        )
        self.sources = [
            {"id": "LEC", "type": "lecture_notes", "title": "Market structures", "availability": "content_available", "locator": str(self.lecture_path)},
            {"id": "DECK", "type": "slides", "title": "Week 5 deck", "availability": "content_available", "locator": str(self.deck_path)},
        ]
        self.state = {"sources": self.sources}

    def load(self, query, **kwargs):
        with mock.patch.object(
            sources_module,
            "extract_pdf_text",
            return_value={"method": sources_module.PDF_EXTRACTION_METHOD, "page_count": 40, "pages": _lecture_pages()},
        ):
            return _load_sources(self.state, ["LEC", "DECK"], query, **kwargs)


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = _Fixture(Path(self._tmp.name))

    def _excerpts(self, contexts, source_id):
        return next(c for c in contexts if c["source_id"] == source_id)["excerpts"]

    def test_legacy_truncation_misses_late_evidence_but_retrieval_finds_it(self) -> None:
        with mock.patch.object(
            sources_module,
            "extract_pdf_text",
            return_value={"method": sources_module.PDF_EXTRACTION_METHOD, "page_count": 40, "pages": _lecture_pages()},
        ):
            _, legacy = _load_sources(self.fx.state, ["LEC"])
        legacy_text = " ".join(e["text"] for e in legacy[0]["excerpts"] if e["pdf_page"] == 37)
        self.assertNotIn("sticky", legacy_text)

        _, contexts = self.fx.load("Why are prices sticky under a kinked demand curve?")
        late = [e for e in self._excerpts(contexts, "LEC") if e["pdf_page"] == 37]
        self.assertTrue(late)
        sticky = next(e for e in late if "sticky" in e["text"])
        self.assertEqual(sticky["passage_id"].split(":")[:2], ["LEC", "37"])

    def test_ubiquitous_term_does_not_drown_specific_terms(self) -> None:
        _, contexts = self.fx.load("market kinked demand curve")
        pages = [e["pdf_page"] for e in self._excerpts(contexts, "LEC")]
        self.assertIn(37, pages)
        self.assertLessEqual(len(pages), 4)

    def test_multiple_sources_keep_identity_page_title_and_fingerprint(self) -> None:
        _, contexts = self.fx.load("kinked demand curve")
        by_id = {c["source_id"]: c for c in contexts}
        self.assertEqual(
            by_id["LEC"]["source_fingerprint"],
            hashlib.sha256(self.fx.lecture_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            by_id["DECK"]["source_fingerprint"],
            hashlib.sha256(self.fx.deck_path.read_bytes()).hexdigest(),
        )
        slide = by_id["DECK"]["excerpts"][0]
        self.assertEqual((slide["pdf_page"], slide["title"]), (2, "Kinked demand"))
        self.assertEqual(render_source_location(sources_module.PPTX_EXTRACTION_METHOD, 2, title=slide["title"]), ", Slide 2 (Kinked demand)")
        self.assertTrue(by_id["LEC"]["excerpts"])
        self.assertEqual(by_id["DECK"]["retrieval"], by_id["LEC"]["retrieval"])

    def test_slide_title_alone_can_match(self) -> None:
        _, contexts = self.fx.load("perfect competition")
        self.assertEqual([e["pdf_page"] for e in self._excerpts(contexts, "DECK")][:1], [3])

    def test_context_is_bounded_and_partial_selection_is_reported(self) -> None:
        _, contexts = self.fx.load("market behaviour participants boundaries")
        report = contexts[0]["retrieval"]
        total = sum(c["character_count"] for c in contexts)
        self.assertLessEqual(total, RETRIEVAL_CHARACTER_LIMIT)
        self.assertGreater(report["matched_passages_omitted"], 0)
        self.assertFalse(report["complete"])
        self.assertIn("left out to bound context", report["note"])

    def test_narrow_query_is_reported_complete(self) -> None:
        _, contexts = self.fx.load("kinked demand curve")
        self.assertTrue(contexts[0]["retrieval"]["complete"])
        self.assertIn("not the whole source", contexts[0]["retrieval"]["note"])

    def test_no_match_is_explicit_and_falls_back_to_labelled_coverage(self) -> None:
        _, contexts = self.fx.load("photosynthesis chloroplast")
        for context in contexts:
            self.assertEqual(context["retrieval"]["status"], "no_match")
            self.assertEqual(context["selection"], "coverage_fallback_no_retrieval_match")
            self.assertIn("NOT evidence", context["retrieval"]["note"])
            self.assertTrue(context["excerpts"])

    def test_stopword_only_query_reports_no_query_terms(self) -> None:
        _, contexts = self.fx.load("what is the")
        self.assertEqual(contexts[0]["retrieval"]["status"], "no_query_terms")

    def test_deterministic(self) -> None:
        first = self.fx.load("kinked demand price rise")[1]
        second = self.fx.load("kinked demand price rise")[1]
        self.assertEqual(first, second)

    def test_pinned_unit_is_always_included(self) -> None:
        _, contexts = self.fx.load("kinked demand curve", pinned=[("LEC", 5)])
        self.assertIn(5, [e["pdf_page"] for e in self._excerpts(contexts, "LEC")])
        self.assertIn(37, [e["pdf_page"] for e in self._excerpts(contexts, "LEC")])

    def test_query_free_loading_is_unchanged(self) -> None:
        _, contexts = self.fx.load(None)
        self.assertNotIn("retrieval", contexts[0])
        self.assertNotIn("source_fingerprint", contexts[0])
        self.assertEqual(contexts[0]["selection"], "ordered page coverage with leading excerpts")

    def test_reasoning_context_carries_retrieval_and_provenance_set(self) -> None:
        prepared, contexts = self.fx.load("kinked demand curve")
        context = {
            "workflow": "TEACH",
            "objective_context": {},
            "module": {"code": "SYN101", "title": "t", "semester": "1", "academic_year": "2026"},
            "sources": prepared,
            "source_contexts": contexts,
        }
        reasoning = build_reasoning_context(context)
        self.assertEqual(reasoning["source_contexts"][0]["retrieval"]["status"], "matched")
        index = build_source_location_index(context)
        self.assertEqual(index["DECK"]["titles"][2], "Kinked demand")


class PassageUnitTests(unittest.TestCase):
    def test_long_unit_is_split_without_losing_text_or_exceeding_target(self) -> None:
        sentence = "Elasticity measures responsiveness of quantity to price changes."
        raw = " ".join([sentence] * 40) + "\n\nSecond block about cross elasticity."
        passages = split_passages(raw)
        self.assertGreater(len(passages), 2)
        self.assertTrue(all(len(p) <= 600 for p in passages))
        self.assertIn("cross elasticity", passages[-1])

    def test_unbroken_text_is_hard_split(self) -> None:
        passages = split_passages("word " * 500)
        self.assertTrue(all(len(p) <= 600 for p in passages))

    def test_empty_units_produce_no_passages_and_numbers_are_preserved(self) -> None:
        passages = build_passages("S", 0, ["", "  ", "Real content here."])
        self.assertEqual([(p.unit, p.index) for p in passages], [(3, 1)])

    def test_tokenize_stems_and_drops_stopwords(self) -> None:
        self.assertEqual(tokenize("The prices of demanded goods"), ["price", "demand", "good"])

    def test_ties_break_by_document_order(self) -> None:
        passages = build_passages("S", 0, ["alpha beta.", "alpha beta."])
        selected, _ = select_passages(passages, "alpha beta")
        self.assertEqual([p.unit for p in selected], [1, 2])

    def test_weak_matches_below_relative_floor_are_dropped(self) -> None:
        passages = build_passages(
            "S", 0, ["kinked demand curve kinked demand.", "A long page about many things. " * 10 + "demand"]
        )
        selected, report = select_passages(passages, "kinked demand curve")
        self.assertEqual([p.unit for p in selected], [1])
        self.assertEqual(report["matched_passages_omitted"], 1)
        self.assertFalse(report["complete"])


if __name__ == "__main__":
    unittest.main()
