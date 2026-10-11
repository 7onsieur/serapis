"""Stage 1 academic reliability: citation relevance and answer-leak detection (offline, synthetic text).

These are lexical screens. They reject clear decoys and clear leaks; they do not prove an answer is correct,
and the KNOWN_MISS leak cases pin what they cannot see. Cases come from ``evals/diagnostic_slice0`` (the
adversarial set sits apart from the frozen 164-case benchmark).
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals" / "diagnostic_slice0"))

import adversarial as A  # noqa: E402
import corpus as C  # noqa: E402

from university_jarvis import tutor_policy as tp  # noqa: E402


class NumberParsingTests(unittest.TestCase):
    def values(self, text, *, locators=False):
        return [v for v, loc in tp.numbers_in(text) if locators or not loc]

    def test_signs_words_separators_and_locators(self):
        self.assertEqual(self.values("-2"), [Decimal(-2)])
        self.assertEqual(self.values("minus two"), [Decimal(-2)])
        self.assertEqual(self.values("negative 2"), [Decimal(-2)])
        self.assertEqual(self.values("1,000 and one thousand and 1000.00"), [Decimal(1000)] * 3)
        self.assertEqual(self.values("twenty five"), [Decimal(25)])
        self.assertEqual(self.values("see page 2"), [])  # a place, not a value
        self.assertEqual(self.values("10-20"), [Decimal(10), Decimal(20)])  # a range, not a negative
        self.assertEqual(self.values("one plus the rate"), [])  # a lone "one" is a pronoun
        self.assertEqual(self.values("50%"), self.values("50"))  # percent is not folded into a fraction

    def test_a_sign_is_part_of_the_value(self):
        self.assertNotEqual(self.values("-2"), self.values("2"))


class LeakCaseTests(unittest.TestCase):
    def test_every_adversarial_leak_case(self):
        for case_id, ref, task, message, student, gold in A.LEAK:
            with self.subTest(case=case_id):
                blocked = tp.reveals_reference(message, ref, allowed_text=[task, student])
                if gold == "LEAK":
                    self.assertTrue(blocked)
                elif gold == "CLEAN":
                    self.assertFalse(blocked)
                else:  # KNOWN_MISS: a real leak the deterministic check is not expected to catch
                    self.assertFalse(blocked, "limitation changed: move this case out of KNOWN_MISS")

    def test_a_quoted_student_answer_is_never_a_leak(self):
        for ref in ("-2", "mitochondria", C.SUBJECTS["statistics"]["root_ref"]):
            with self.subTest(ref=ref):
                self.assertFalse(tp.reveals_reference(f'You wrote "{ref}".', ref, allowed_text=[ref]))

    def test_a_long_reference_message_that_only_shares_topic_words_is_clean(self):
        ref = C.SUBJECTS["economics"]["root_ref"]
        self.assertFalse(tp.reveals_reference("Re-read the part about elasticity and price changes.", ref))

    def test_frozen_clean_hints_stay_clean(self):
        for s in C.SUBJECTS.values():
            with self.subTest(subject=s["concept"]):
                self.assertFalse(tp.reveals_reference(s["short"]["clean"], s["short"]["ref"],
                                                      allowed_text=[s["short"]["task"]]))


class ShortReferenceFalsePositiveTests(unittest.TestCase):
    """Legitimate mentions of numbers and names that are not the reference must not be blocked."""

    def blocked(self, message, ref, task="Q?", student="my answer"):
        return tp.reveals_reference(message, ref, allowed_text=[task, student])

    def test_ordinals_labels_and_chemistry_are_not_values(self):
        for message in ("Look at the 2nd paragraph.", "Re-read the 3rd example.", "H2O is not what is asked.",
                        "In week 2 and on slide 2 this is covered.", "Version 12 of the notes differs."):
            with self.subTest(message=message):
                self.assertFalse(self.blocked(message, "2"))

    def test_other_numbers_and_longer_words_are_not_the_reference(self):
        self.assertFalse(self.blocked("The sample has 25 observations and a mean of 12.", "2"))
        self.assertFalse(self.blocked("It ranges from 20 to 30.", "-2"))
        self.assertFalse(self.blocked("Consider the mitochondrial membrane.", "mitochondria"))
        self.assertFalse(self.blocked("Nucleotides pair up.", "nucleus"))

    def test_a_number_or_name_the_question_or_student_already_used_is_not_a_leak(self):
        self.assertFalse(self.blocked("With 25 observations, take the square root first.", "25", task="n = 25?"))
        self.assertFalse(self.blocked("Mitochondria is a good guess to check.", "mitochondria", student="mitochondria"))

    def test_known_false_positive_the_same_value_used_for_something_else_is_blocked(self):
        # Accepted, safe-direction limitation (see the eval README): a tutor message that uses the reference's
        # value for an unrelated purpose cannot be told apart lexically.
        self.assertTrue(self.blocked("Compare the 2 groups before you answer.", "2"))


class CitationRelevanceTests(unittest.TestCase):
    def check(self, subject, question, answer, pages, *, with_others=True):
        s = C.SUBJECTS[subject]
        sid, texts = s["source_id"], s["pages"]
        cites = [{"source_id": sid, "pdf_page": p} for p in pages]
        others = [t for i, t in enumerate(texts, 1) if i not in pages] if with_others else []
        return tp.validate_question(
            {"question": question, "expected_answer": answer, "citations": cites}, step="FOLLOW_UP",
            citations_ok=lambda c: None,
            cited_text=lambda cs: " ".join(texts[c["pdf_page"] - 1] for c in cs),
            shown=[s["root_task"]], prior_questions=[s["root_task"]], prior_answers=[s["root_ref"]],
            unrevealed_answers=[s["root_ref"]], concept_text=" ".join([s["root_task"], s["root_ref"]]),
            other_pages=others)

    def test_an_answer_about_a_different_concept_from_a_decoy_page_is_rejected(self):
        for key, s in C.SUBJECTS.items():
            with self.subTest(subject=key):
                clean, reason = self.check(key, s["fq"], s["fq_decoy_swap"], [2])
                self.assertIsNone(clean)
                self.assertEqual(reason, "the question is better supported by a page that was not cited")

    def test_the_same_decoy_passes_without_the_other_pages_so_the_gain_is_the_new_check(self):
        s = C.SUBJECTS["economics"]
        self.assertIsNotNone(self.check("economics", s["fq"], s["fq_decoy_swap"], [2], with_others=False)[0])

    def test_valid_questions_are_still_accepted_when_a_decoy_shares_vocabulary(self):
        for key, s in C.SUBJECTS.items():
            if key == "marketing":  # existing false reject: "gives away its own answer"; unrelated to Stage 1
                continue
            with self.subTest(subject=key):
                self.assertIsNotNone(self.check(key, s["fq"], s["fq_valid"], [1])[0])

    def test_a_cited_page_that_adds_nothing_and_matches_the_question_worse_is_rejected(self):
        for key in ("economics", "statistics", "finance", "psychology"):
            s = C.SUBJECTS[key]
            with self.subTest(subject=key):
                clean, reason = self.check(key, s["fq"], s["fq_valid"], [1, 2])
                self.assertIsNone(clean)
                self.assertEqual(reason, "a cited passage adds nothing to the expected answer")

    def test_legitimate_multi_page_support_is_kept(self):
        question, answer = (A.GENERATED[2][2], A.GENERATED[2][3])
        clean, reason = self.check("finance", question, answer, [1, 2])
        self.assertIsNotNone(clean, reason)

    def test_a_second_page_that_matches_the_question_equally_well_is_not_called_redundant(self):
        # Corroboration, not a decoy: the margin leaves it alone.
        s = C.SUBJECTS["economics"]
        question = "How is elasticity of demand calculated as a percentage change in quantity demanded?"
        answer = "It is the percentage change in quantity demanded divided by the percentage change in price or income."
        self.assertIsNone(tp._citation_relevance(question, tp_stems(answer) - tp_stems(question),
                                                 [s["pages"][0], s["pages"][1]], []))

    def test_a_slightly_better_uncited_page_does_not_reject(self):
        q = "alpha beta gamma delta epsilon zeta eta theta"
        cited, near = "alpha beta gamma delta epsilon", "alpha beta gamma delta epsilon zeta"
        self.assertIsNone(tp._citation_relevance(q, set(), [cited], [near]))  # 0.625 vs 0.75: inside the margin
        far = "alpha beta gamma delta epsilon zeta eta"
        self.assertIsNotNone(tp._citation_relevance(q, set(), [cited], [far]))  # 0.625 vs 0.875: outside it


def tp_stems(text):
    from university_jarvis.retrieval import tokenize
    return set(tokenize(text))


class ProductionPathTests(unittest.TestCase):
    """The full path: real retrieval, create_session -> skip -> next_question."""

    @classmethod
    def setUpClass(cls):
        import run_eval  # noqa: PLC0415 - installs the harness' own offline guard
        cls.run_next = staticmethod(run_eval.run_next)

    def test_decoy_concept_answers_are_not_opened_and_valid_questions_are(self):
        for key in ("economics", "statistics"):
            s = C.SUBJECTS[key]
            cite = lambda *p: [{"source_id": s["source_id"], "pdf_page": n} for n in p]  # noqa: E731
            with self.subTest(subject=key, case="decoy"):
                self.assertEqual(self.run_next(key, s["fq"], s["fq_decoy_swap"], cite(2))["observed"], "REJECT")
            with self.subTest(subject=key, case="extra_decoy"):
                self.assertEqual(self.run_next(key, s["fq"], s["fq_valid"], cite(1, 2))["observed"], "REJECT")
            with self.subTest(subject=key, case="valid"):
                self.assertEqual(self.run_next(key, s["fq"], s["fq_valid"], cite(1))["observed"], "ACCEPT")


if __name__ == "__main__":
    unittest.main()
