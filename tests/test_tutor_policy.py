"""Phase 3C slice 1: the pure, offline teaching-policy rules (no provider, no files)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis import tutor_policy as tp

ANSWER = "Cells are the basic structural and functional unit of all living organisms"
RESPONSE = "I believe viruses are the basic unit of life because they replicate"
CITE = [{"source_id": "s1", "pdf_page": 1}]


def _ok(cites):
    if any(c["source_id"] != "s1" for c in cites):
        raise ValueError("unsupplied source")


def _mis(**over):
    base = {"label": "Thinks viruses are the unit of life", "quote": "viruses are the basic unit",
            "confidence": "high", "citations": CITE}
    return {**base, **over}


class HedgeTests(unittest.TestCase):
    def test_pure_non_answers(self):
        for text in ("idk", "I don't know", "I'm not sure", "no idea", "I think so", "???", "Dunno!"):
            with self.subTest(text=text):
                self.assertTrue(tp.detect_hedge(text)["non_answer"], text)

    def test_hedged_but_real_answers_are_still_answers(self):
        result = tp.detect_hedge("I think cells are the basic unit")
        self.assertEqual(result, {"hedged": True, "non_answer": False})

    def test_plain_answers_are_neither(self):
        for text in ("Cells are the basic unit", "my answer", "more", "42"):
            with self.subTest(text=text):
                self.assertEqual(tp.detect_hedge(text), {"hedged": False, "non_answer": False})

    def test_words_that_merely_contain_a_hedge_do_not_trigger(self):
        self.assertFalse(tp.detect_hedge("The guesstimate is irrelevant; mitochondria produce ATP")["hedged"])


class MisconceptionValidationTests(unittest.TestCase):
    def check(self, raw, diagnosis="misconception", response=RESPONSE, reference=ANSWER):
        return tp.validate_misconception(raw, response, diagnosis, citations_ok=_ok, reference_answer=reference)

    def test_a_quoted_cited_confident_misconception_is_kept(self):
        clean, why = self.check(_mis())
        self.assertIsNone(why)
        self.assertEqual(clean["confidence"], "high")
        self.assertEqual(clean["quote"], "viruses are the basic unit")

    def test_quote_must_be_literally_in_the_response(self):
        for quote in ("viruses are the smallest unit", "cells are the basic unit", "   "):
            with self.subTest(quote=quote):
                self.assertIsNone(self.check(_mis(quote=quote))[0])

    def test_quote_matching_ignores_case_and_punctuation_only(self):
        self.assertIsNotNone(self.check(_mis(quote="Viruses ARE the basic unit!"))[0])

    def test_unstated_or_low_confidence_is_dropped(self):
        for confidence in ("low", "", "certain", None):
            with self.subTest(confidence=confidence):
                self.assertIsNone(self.check(_mis(confidence=confidence))[0])

    def test_citation_failures_are_dropped_not_raised(self):
        for citations in ([], None, [{"source_id": "zzz", "pdf_page": 1}], [{"source_id": "s1"}]):
            with self.subTest(citations=citations):
                self.assertIsNone(self.check(_mis(citations=citations))[0])

    def test_only_a_misconception_diagnosis_carries_one(self):
        self.assertEqual(self.check(_mis(), diagnosis="partial"),
                         (None, "misconception given for a different diagnosis"))
        self.assertEqual(self.check(None, diagnosis="partial"), (None, None))

    def test_malformed_shapes_are_dropped(self):
        for raw in (None, "viruses", {"label": "x"}, {**_mis(), "extra": 1}):
            with self.subTest(raw=raw):
                self.assertIsNone(self.check(raw)[0])

    def test_a_label_that_states_the_answer_is_dropped(self):
        label = "Student thinks viruses: actually " + ANSWER
        self.assertIsNone(self.check(_mis(label=label))[0])


class LeakTests(unittest.TestCase):
    def test_verbatim_and_partial_reproduction_is_a_leak(self):
        self.assertTrue(tp.reveals_reference(f"Remember: {ANSWER}.", ANSWER))
        self.assertTrue(tp.reveals_reference("They are the basic structural and functional unit, so think again.", ANSWER))

    def test_paraphrase_and_unrelated_text_pass(self):
        self.assertFalse(tp.reveals_reference("Think about what every living thing is built from.", ANSWER))
        self.assertFalse(tp.reveals_reference("", ANSWER))
        self.assertFalse(tp.reveals_reference("anything", None))

    def test_echoing_the_students_own_words_is_not_a_leak(self):
        student = "Cells are the basic structural and functional unit of all living organisms"
        self.assertFalse(tp.reveals_reference(f"You wrote: {student}. Good.", ANSWER, allowed_text=[student]))

    def test_very_short_references_cannot_be_tested(self):
        self.assertFalse(tp.reveals_reference("The answer is nucleus", "nucleus"))


class NoveltyTests(unittest.TestCase):
    SHOWN = ["What is the basic structural unit of living organisms?", ANSWER]

    def test_a_rewording_of_a_shown_answer_is_not_novel(self):
        for text in ("Which unit is basic, structural and functional in all living organisms?",
                     "Cells are the basic unit of living organisms"):
            with self.subTest(text=text):
                self.assertFalse(tp.novelty_check(text, self.SHOWN)["novel"])

    def test_the_same_question_in_other_words_is_not_novel(self):
        self.assertFalse(tp.novelty_check("What is the basic structural unit of all living organisms?", self.SHOWN)["novel"])

    def test_a_different_question_is_novel(self):
        result = tp.novelty_check("A new bacterium is found with a nucleus-free interior; which cell type is it?", self.SHOWN)
        self.assertTrue(result["novel"], result)

    def test_empty_candidates_are_rejected(self):
        self.assertFalse(tp.novelty_check("the of and", self.SHOWN)["novel"])


class NextActionTests(unittest.TestCase):
    def test_policy_table(self):
        cases = [
            (dict(diagnosis="unclear", non_answer=True), "OFFER_HINT"),
            (dict(diagnosis="unclear", non_answer=True, hints_left=False), "OFFER_REVEAL_OR_END"),
            (dict(diagnosis="unclear"), "CLARIFY"),
            (dict(diagnosis="unclear", consecutive_unclear=1), "OFFER_HINT_OR_END"),
            (dict(diagnosis="off_target"), "RESTATE"),
            (dict(diagnosis="misconception", misconception=True), "REVIEW_SOURCE"),
            (dict(diagnosis="partial"), "FOLLOW_UP"),
            (dict(diagnosis="partial", hints_left=False), "REVIEW_SOURCE"),
            (dict(diagnosis="correct"), "CONSOLIDATE"),
            (dict(diagnosis="correct", assistance_status="PROMPTED"), "UNAIDED_RETEST_LATER"),
            (dict(diagnosis="correct", answer_revealed=True), "UNAIDED_RETEST_LATER"),
            (dict(diagnosis="correct", self_confidence="GUESSING"), "CHECK_REASONING"),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                self.assertEqual(tp.next_action(**kwargs), expected)

    def test_self_confidence_only_shifts_advice_never_the_diagnosis_branch(self):
        for confidence in (None, "SURE", "UNSURE", "GUESSING"):
            self.assertEqual(tp.next_action(diagnosis="off_target", self_confidence=confidence), "RESTATE")


class EvidenceClassificationTests(unittest.TestCase):
    def test_labels_follow_the_recorded_assistance_only(self):
        for status, label in (("REVEALED", "REVEALED"), ("PROMPTED", "ASSISTED"), ("UNAIDED", "UNAIDED_UNLINKED")):
            with self.subTest(status=status):
                self.assertEqual(tp.classify_evidence({"assistance_status": status}), label)

    def test_no_transfer_or_retention_claim_is_made_from_timing_capability_or_week(self):
        # Same capability, same week, days apart: still only "unaided, unlinked".
        attempt = {"assistance_status": "UNAIDED", "capability": "RECALL", "week": 1,
                   "attempted_at": "2026-01-09T10:00:00+00:00", "task_key": "b"}
        label = tp.classify_evidence(attempt)
        self.assertEqual(label, "UNAIDED_UNLINKED")
        self.assertFalse(hasattr(tp, "RETENTION_GAP_HOURS"))
        for forbidden in ("TRANSFER", "RETENTION", "INDEPENDENT"):
            self.assertNotIn(forbidden, label)

    def test_unknown_status_is_treated_as_assisted(self):
        self.assertEqual(tp.classify_evidence({}), "ASSISTED")


if __name__ == "__main__":
    unittest.main()
