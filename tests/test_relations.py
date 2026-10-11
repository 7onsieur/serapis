"""Stage 2: explicit relationship checks between a text and its cited passages (offline, deterministic).

Each case pins one verdict. ``UNDETERMINED`` is never treated as support: ``relation_conflict`` only rejects a
recognised relation that clearly conflicts with a recognised relation in the passage.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis import tutor_policy as tp  # noqa: E402
from university_jarvis.relations import CONTRADICTED, SUPPORTED, UNDETERMINED, check_relations, relation_conflict  # noqa: E402

ELASTICITY = ("Price elasticity is calculated as the percentage change in quantity demanded divided by the "
              "percentage change in price. Demand is elastic when its absolute value exceeds one.")
SE = ("Standard error is calculated as the sample standard deviation divided by the square root of the sample size. "
      "A larger sample therefore gives a smaller standard error.")
ASSIGN = "Random assignment makes the groups equivalent on average before the treatment."


def verdicts(text, *pages):
    return {f.verdict for f in check_relations(text, pages)}


class RelationTests(unittest.TestCase):
    def test_reversed_ratio_is_contradicted(self):
        text = "It is the percentage change in price divided by the percentage change in quantity demanded."
        self.assertEqual(verdicts(text, ELASTICITY), {CONTRADICTED})
        self.assertIn("contradicts", relation_conflict(text, [ELASTICITY]))

    def test_same_ratio_in_other_words_is_supported(self):
        text = "Elasticity equals the percentage change in the quantity demanded divided by the percentage change in price."
        self.assertEqual(verdicts(text, ELASTICITY), {SUPPORTED})
        self.assertIsNone(relation_conflict(text, [ELASTICITY]))

    def test_commutative_operations_accept_either_operand_order(self):
        self.assertIsNone(relation_conflict("Area is width times length.", ["Area equals length multiplied by width."]))
        self.assertEqual(verdicts("Cost is variable cost plus fixed cost.", "Cost is fixed cost plus variable cost."),
                         {SUPPORTED})

    def test_non_commutative_operations_reject_reversal_and_a_changed_operation(self):
        self.assertIsNotNone(relation_conflict("Profit is cost minus revenue.", ["Profit is revenue minus cost."]))
        self.assertIsNotNone(relation_conflict("Profit is revenue plus cost.", ["Profit is revenue minus cost."]))
        self.assertIsNotNone(relation_conflict(
            "Standard error is the sample standard deviation times the square root of the sample size.", [SE]))

    def test_comparison_direction(self):
        self.assertIsNotNone(relation_conflict("Demand is elastic when its absolute value is below one.", [ELASTICITY]))
        self.assertIsNone(relation_conflict("One is less than its absolute value when demand is elastic.", [ELASTICITY]))

    def test_direction_of_change(self):
        self.assertIsNotNone(relation_conflict("A larger sample gives a larger standard error.", [SE]))
        self.assertIsNone(relation_conflict("A smaller sample gives a larger standard error.", [SE]))

    def test_negation_flip_is_contradicted_only_for_the_identical_clause(self):
        self.assertIsNotNone(relation_conflict(
            "Random assignment does not make the groups equivalent on average before the treatment.", [ASSIGN]))
        self.assertIsNone(relation_conflict(
            "Random sampling does not make the groups equivalent on average before the treatment.", [ASSIGN]))
        self.assertIsNone(relation_conflict(
            "Random assignment does not only make the groups equivalent on average before the treatment.", [ASSIGN]))
        self.assertIsNone(relation_conflict(
            "It does not make the groups equivalent on average before the treatment.", [ASSIGN]))

    def test_unrecognised_or_unmatched_patterns_are_undetermined_not_supported(self):
        for text in ("Standard error equals the standard deviation over the root of the sample size.",
                     "The standard error is 10 divided by 5, which is 2.",
                     "It is the percentage change in quantity demanded divided by the percentage change in income.",
                     "Standard error describes how sample means vary."):
            self.assertNotIn(CONTRADICTED, verdicts(text, SE, ELASTICITY))
            self.assertNotIn(SUPPORTED, verdicts(text, SE, ELASTICITY), text)
            self.assertIsNone(relation_conflict(text, [SE]))

    def test_a_clause_with_a_negator_is_never_read_as_arithmetic(self):
        self.assertIsNone(relation_conflict(
            "Elasticity is not the percentage change in price divided by the percentage change in quantity demanded.",
            [ELASTICITY]))

    def test_a_quoted_misconception_is_not_judged(self):
        for text in ("A common mistake is to say that a larger sample gives a larger standard error, but a larger "
                     "sample gives a smaller standard error.",
                     "If you think a larger sample gives a larger standard error you are mistaken.",
                     "Students often claim the percentage change in price divided by the percentage change in "
                     "quantity demanded, which is wrong."):
            self.assertIsNone(relation_conflict(text, [SE, ELASTICITY]), text)
            self.assertNotIn(CONTRADICTED, verdicts(text, SE, ELASTICITY))
            self.assertNotIn(SUPPORTED, verdicts(text, SE, ELASTICITY))

    def test_a_wrong_relation_beside_a_correct_one_is_still_rejected(self):
        text = "A larger sample gives a smaller standard error, and a larger sample gives a larger standard error."
        self.assertIsNotNone(relation_conflict(text, [SE]))

    def test_related_but_different_claims_across_pages_are_not_contradictions(self):
        pages = ["Present value equals the future value divided by one plus the discount rate.",
                 "Future value equals the present value multiplied by one plus the interest rate."]
        text = ("Present value equals the future value divided by one plus the discount rate, and future value "
                "equals the present value multiplied by one plus the interest rate.")
        self.assertIsNone(relation_conflict(text, pages))
        self.assertIsNotNone(relation_conflict(
            "Present value equals the future value multiplied by one plus the discount rate.", pages))

    def test_reference_gate_uses_it(self):
        swapped = "It is the percentage change in price divided by the percentage change in quantity demanded."
        self.assertIn("contradicts", tp.reference_unsupported(swapped, [ELASTICITY]))
        right = "It is the percentage change in quantity demanded divided by the percentage change in price."
        self.assertIsNone(tp.reference_unsupported(right, [ELASTICITY]))

    def test_validate_question_rejects_a_contradicted_expected_answer(self):
        def run(expected, question="How does the size of a sample change the standard error?"):
            return tp.validate_question(
                {"question": question, "expected_answer": expected, "citations": [{"source_id": "s", "pdf_page": 1}]},
                step="FOLLOW_UP", citations_ok=lambda c: None, cited_text=lambda c: SE, shown=[], prior_questions=[],
                prior_answers=[], unrevealed_answers=[], concept_text=SE)
        self.assertIn("contradicts", run("A larger sample gives a larger standard error.")[1])
        self.assertIsNone(run("A larger sample gives a smaller standard error.")[1])


if __name__ == "__main__":
    unittest.main()
