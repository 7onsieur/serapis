"""Stage 3: independent mathematical verification (offline, deterministic).

Engine tests pin the restricted evaluator, the verdicts and what each one means. Integration tests drive the real
tutoring paths with scripted providers: an unverified calculation is never shown, graded against, hinted from or
revealed; a task without a calculation behaves exactly as before.
"""

from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import test_tutoring_sequence as seq  # noqa: E402

from university_jarvis import tutor_policy as tp  # noqa: E402
from university_jarvis import tutoring  # noqa: E402
from university_jarvis.calculation import (  # noqa: E402
    INCONCLUSIVE,
    REJECTED,
    VERIFIED,
    CalcError,
    evaluate,
    parse_formula,
    parse_unit,
    verify_calculation,
)

MEAN = "The mean is the total divided by the count."
PROFIT = "Profit is revenue minus cost. Profit margin is calculated as profit divided by revenue."
SE = "The standard error of the mean is calculated as the sample standard deviation divided by the square root of the sample size."


def spec(inputs, steps, value, unit="", decimals=None):
    return {"inputs": [{"name": n, "label": l, "value": v, "unit": u, "source": s}
                       for n, l, v, u, s in [(i + ("QUESTION",))[:5] if len(i) == 4 else i for i in inputs]],
            "steps": [{"name": n, "label": l, "formula": f} for n, l, f in steps],
            "result": {"value": value, "unit": unit, "decimals": decimals}}


def mean_spec(total="2", count="3", value="0.67", decimals=2, formula="t / c"):
    return spec([("t", "total", total, ""), ("c", "count", count, "")], [("m", "mean", formula)], value, "", decimals)


def check(sp, question="A total of 2 is shared over a count of 3. What is the mean?",
          expected="The mean is 0.67.", page=MEAN):
    return verify_calculation(sp, question=question, expected_answer=expected, cited_pages=[page] if page else [])


class EvaluatorTests(unittest.TestCase):
    def ev(self, formula, **names):
        from university_jarvis.calculation import _q
        return evaluate(parse_formula(formula), {k: _q(Decimal(v), {}) for k, v in names.items()}).value

    def test_arithmetic_precedence_and_exactness(self):
        self.assertEqual(self.ev("1 + 2 * 3 - 4 / 2"), Decimal(5))
        self.assertEqual(self.ev("-2 ^ 2"), Decimal(-4))
        self.assertEqual(self.ev("(0.1 + 0.2) * 10"), Decimal(3))
        self.assertEqual(self.ev("2 ^ -2"), Decimal("0.25"))
        self.assertEqual(self.ev("sqrt(x)", x="16"), Decimal(4))
        self.assertEqual(self.ev("50% * x", x="80"), Decimal(40))
        self.assertEqual(self.ev("x ** 2", x="-3"), Decimal(9))

    def test_unsafe_or_malformed_formulas_never_evaluate(self):
        for bad in ("__import__('os')", "x.real", "open('f')", "x[0]", "1e5", "2x", "x y", "x +", "(x", "x)", "",
                    "lambda: 1", "x if x else 1", "x; x", "x // 2", "x % 2", "x | 2", "é", "x" * 300):
            with self.subTest(formula=bad), self.assertRaises(CalcError):
                self.ev(bad, x="2")

    def test_domain_and_size_limits(self):
        for bad, kind in (("1 / 0", REJECTED), ("sqrt(0 - 1)", REJECTED), ("10 ^ 17", REJECTED), ("0 ^ -1", REJECTED),
                          ("99999999999999999999 * 99999999999999999999 * 99999999999999999999", REJECTED),
                          ("2 ^ 0.3", INCONCLUSIVE)):
            with self.subTest(formula=bad), self.assertRaises(CalcError) as caught:
                self.ev(bad)
            self.assertEqual(caught.exception.status, kind)

    def test_units_convert_exactly_and_unknown_units_are_opaque(self):
        self.assertEqual(parse_unit("km/h")[1], Decimal(1000) / Decimal(3600))
        self.assertEqual(parse_unit("%"), ({}, Decimal("0.01")))
        self.assertEqual(parse_unit("m^2")[0], {"length": 2})
        self.assertTrue(any(k.startswith("?") for k in parse_unit("apples")[0]))
        for bad in ("°C", "kelvin"):
            with self.assertRaises(CalcError) as caught:
                parse_unit(bad)
            self.assertEqual(caught.exception.status, INCONCLUSIVE)
        with self.assertRaises(CalcError):
            parse_unit("m/s/s")


class HoldoutFixTests(unittest.TestCase):
    """Regression tests for the two Stage 3 false accepts and the review findings (names are case ids of the holdout)."""

    FALL = "Quantity demanded falls by 20% when price rises by 10%. What is the price elasticity of demand?"
    ELAS = "Price elasticity of demand is the percentage change in quantity demanded divided by the percentage change in price."

    def elasticity(self, dq, dp, value):
        return check(spec([("dq", "percentage change in quantity demanded", dq, "%"),
                           ("dp", "percentage change in price", dp, "%")],
                          [("e", "price elasticity of demand", "dq / dp")], value),
                     question=self.FALL, expected=f"It is {value}.", page=self.ELAS)

    def test_direction_of_change_must_agree_with_the_text(self):
        self.assertEqual(self.elasticity("-20", "10", "-2").status, VERIFIED)
        for dq, dp, value in (("20", "10", "2"), ("-20", "-10", "2")):
            with self.subTest(dq=dq, dp=dp):
                v = self.elasticity(dq, dp, value)
                self.assertEqual(v.status, INCONCLUSIVE)
                self.assertIn("sign", v.reason)

    def test_a_quantity_named_as_a_decrease_is_a_positive_magnitude(self):
        net = "The net change is the gain minus the loss."
        q = "A fund has a gain of 90 and a loss of 40. What is the net change?"
        run = lambda loss, value: check(spec([("g", "gain", "90", ""), ("l", "loss", loss, "")],  # noqa: E731
                                             [("n", "net change", "g - l")], value), question=q,
                                        expected=f"The net change is {value}.", page=net)
        self.assertEqual(run("40", "50").status, VERIFIED)
        self.assertEqual(run("-40", "130").status, INCONCLUSIVE)

    def test_number_written_before_its_name_is_tied_to_that_name(self):
        for q in ("The values are 7 for the total and 3 for the count. What is the mean?",
                  "Here 7 is the total and 3 is the count. What is the mean?"):
            with self.subTest(question=q):
                good = check(mean_spec("7", "3", "2.33", 2), question=q, expected="The mean is 2.33.")
                swapped = check(mean_spec("3", "7", "0.43", 2), question=q, expected="The mean is 0.43.")
                self.assertEqual((good.status, swapped.status), (VERIFIED, INCONCLUSIVE))
        q = "There are 3 favourable outcomes out of 12 possible outcomes. What is the probability of the event?"
        page = "The probability of an event is the number of favourable outcomes divided by the number of possible outcomes."
        run = lambda f, p, value: check(spec([("f", "number of favourable outcomes", f, ""),  # noqa: E731
                                              ("p", "number of possible outcomes", p, "")],
                                             [("pr", "probability of the event", "f / p")], value),
                                        question=q, expected=f"The probability is {value}.", page=page)
        self.assertEqual(run("3", "12", "0.25").status, VERIFIED)
        self.assertEqual(run("12", "3", "4").status, INCONCLUSIVE)

    def test_an_input_whose_name_is_present_but_not_tied_to_the_number_is_not_trusted(self):
        q = "Of the figures 7 and 3 the first is a total and the second a count. What is the mean?"
        self.assertEqual(check(mean_spec("7", "3", "2.33", 2), question=q, expected="The mean is 2.33.").status, INCONCLUSIVE)

    def test_the_answer_may_quote_only_numbers_the_calculation_accounts_for(self):
        q = "A sample has standard deviation 15 and size 9. What is the standard error of the mean?"
        sp = spec([("s", "sample standard deviation", "15", ""), ("n", "sample size", "9", "")],
                  [("se", "standard error of the mean", "s / sqrt(n)")], "5")
        run = lambda text: check(sp, question=q, expected=text, page=SE)  # noqa: E731
        self.assertEqual(run("It is 15 divided by the square root of 9, which is 3 into 15, so 5.").status, VERIFIED)
        for text in ("It is 5 and the population mean is 42.", "It is 15 divided by the square root of 16, so 5."):
            with self.subTest(text=text):
                self.assertEqual(run(text).status, REJECTED)

    def test_the_last_step_must_be_what_the_question_asks_for(self):
        q = "A shop has revenue of 500 and cost of 320. What is its profit margin?"
        sp = spec([("r", "revenue", "500", ""), ("c", "cost", "320", "")], [("p", "profit", "r - c")], "180")
        v = check(sp, question=q, expected="Profit is 180.", page=PROFIT)
        self.assertEqual(v.status, INCONCLUSIVE)
        self.assertIn("asks for", v.reason)

    def test_old_sessions_without_a_calculation_are_not_screened(self):
        # requires_calculation runs only on newly generated questions; a stored task is gated by reference_problem alone
        refs = [{"source_id": "s1", "pdf_page": 1, "fingerprint": {"v": 1}}]
        ctx = [{"source_id": "s1", "excerpts": [{"pdf_page": 1, "text": SE}]}]
        self.assertIsNone(tp.reference_problem("The standard error is the sample standard deviation divided by the "
                                               "square root of the sample size, which is 5.", refs, ctx, question="q"))


class SignConventionTests(unittest.TestCase):
    """Provisional sign convention: a quantity that falls is negative; a quantity whose name is a decrease is a positive magnitude."""

    PM = "Profit is revenue minus cost. Profit margin is profit divided by revenue."
    NET = "The net result is the gain minus the loss."
    ELAS = "Price elasticity of demand is the percentage change in quantity demanded divided by the percentage change in price."

    def net(self, loss, value):
        return check(spec([("g", "gain", "200", ""), ("l", "loss", loss, "")], [("n", "net result", "g - l")], value),
                     question="A firm has a gain of 200 and a loss of 50. What is the net result?",
                     expected=f"The net result is {value}.", page=self.NET)

    def elasticity(self, dq, dp, value, question):
        return check(spec([("dq", "percentage change in quantity demanded", dq, "%"),
                           ("dp", "percentage change in price", dp, "%")],
                          [("e", "price elasticity of demand", "dq / dp")], value),
                     question=question, expected=f"It is {value}.", page=self.ELAS)

    def test_a_loss_is_a_positive_magnitude(self):
        self.assertEqual(self.net("50", "150").status, VERIFIED)
        self.assertEqual(self.net("-50", "250").status, INCONCLUSIVE)

    def test_a_fall_is_negative_and_a_rise_positive(self):
        q = "Price rises by 10% and quantity demanded falls by 15%. What is the price elasticity of demand?"
        self.assertEqual(self.elasticity("-15", "10", "-1.5", q).status, VERIFIED)
        for dq, dp, value in (("15", "10", "1.5"), ("-15", "-10", "1.5"), ("15", "-10", "-1.5")):
            with self.subTest(dq=dq, dp=dp):
                self.assertEqual(self.elasticity(dq, dp, value, q).status, INCONCLUSIVE)

    def test_levels_after_from_and_to_are_not_changes(self):
        pct = "The change is the new value minus the original value. The percentage change is the change divided by the original value."
        q = "Sales fall from 50 to 40. What is the percentage change?"
        sp = spec([("o", "original value", "50", ""), ("n", "new value", "40", "")],
                  [("c", "change", "n - o"), ("pc", "percentage change", "c / o")], "-20", "%")
        self.assertEqual(check(sp, question=q, expected="The change is negative 10, so it is negative 20%.", page=pct).status,
                         VERIFIED)

    def test_a_negative_value_with_no_direction_in_the_text_is_not_trusted(self):
        sp = spec([("r", "revenue", "-5", ""), ("c", "cost", "3", "")], [("p", "profit", "r - c")], "-8")
        self.assertEqual(check(sp, question="A shop has revenue of 5 and cost of 3. What is its profit?",
                               expected="Profit is negative 8.", page=self.PM).status, INCONCLUSIVE)

    def test_zero_has_no_sign(self):
        sp = spec([("r", "revenue", "0", ""), ("c", "cost", "3", "")], [("p", "profit", "r - c")], "-3")
        self.assertEqual(check(sp, question="A shop has revenue of 0 and cost of 3. What is its profit?",
                               expected="Profit is negative 3.", page=self.PM).status, VERIFIED)


class AmbiguousAssignmentTests(unittest.TestCase):
    GM = "Gross profit is revenue minus cost of goods sold. Gross margin is gross profit divided by revenue."
    PCT = "The change is the new value minus the original value. The percentage change is the change divided by the original value."

    def gm(self, question):
        return check(spec([("rev", "revenue", "800", ""), ("cogs", "cost of goods sold", "520", "")],
                          [("gp", "gross profit", "rev - cogs"), ("gm", "gross margin", "gp / rev")], "35", "%"),
                     question=question, expected="Gross profit is 280, so gross margin is 35%.", page=self.GM)

    def test_inputs_named_in_the_question_are_confirmed(self):
        self.assertEqual(self.gm("A firm has revenue of 800 and cost of goods sold of 520. What is its gross margin?").status,
                         VERIFIED)

    def test_most_inputs_unnamed_in_the_question_is_inconclusive(self):
        v = self.gm("A bakery has takings of 800 and expenses of 520. What is its gross margin?")
        self.assertEqual(v.status, INCONCLUSIVE)
        self.assertIn("fewer than half", v.reason)

    def test_one_unnamed_input_of_several_is_tolerated(self):
        # the question may call one quantity its own name ("costs 150" for a passage's "price")
        sale = "The discount amount is the price multiplied by the discount rate."
        sp = spec([("p", "price", "150", ""), ("r", "discount rate", "20", "%")], [("d", "discount amount", "p * r")], "30")
        self.assertEqual(check(sp, question="A coat costs 150 with a discount rate of 20%. What is the discount amount?",
                               expected="The discount amount is 30.", page=sale).status, VERIFIED)

    def test_from_a_to_b_places_the_two_numbers_in_that_order(self):
        def run(first, second, q):
            return check(spec([("o", "original value", first, ""), ("n", "new value", second, "")],
                              [("c", "change", "n - o"), ("pc", "percentage change", "c / o")],
                              "25" if first == "40" else "-20", "%"),
                         question=q, expected="The percentage change is 25%." if first == "40" else "It is negative 20%.",
                         page=self.PCT)
        self.assertEqual(run("40", "50", "Sales rise from 40 to 50. What is the percentage change?").status, VERIFIED)
        swapped = check(spec([("o", "original value", "50", ""), ("n", "new value", "40", "")],
                             [("c", "change", "n - o"), ("pc", "percentage change", "c / o")], "-20", "%"),
                        question="Sales rise from 40 to 50. What is the percentage change?",
                        expected="It is negative 20%.", page=self.PCT)
        self.assertEqual(swapped.status, INCONCLUSIVE)
        self.assertIn("opposite order", swapped.reason)


class VocabularyRelaxationTests(unittest.TestCase):
    """The narration and unit words a verified calculation may use are exempt from lexical support; nothing else is."""

    ROI = "Return on investment is the net profit divided by the cost of the investment."
    Q = "An investment of 60000 earns a net profit of 15000. What is the return on investment?"
    SP = spec([("np", "net profit", "15000", ""), ("ci", "cost of the investment", "60000", "")],
              [("roi", "return on investment", "np / ci")], "25", "%")

    def validate(self, expected):
        return tp.validate_question(
            {"question": self.Q, "expected_answer": expected, "citations": [{"source_id": "s1", "pdf_page": 1}],
             "calculation": self.SP}, step="FOLLOW_UP", citations_ok=lambda c: None, cited_text=lambda c: self.ROI,
            shown=[], prior_questions=["Summarise."], prior_answers=[], unrevealed_answers=[],
            concept_text=self.Q)

    def test_narration_and_unit_words_pass(self):
        clean, reason = self.validate("Return on investment is 15000 divided by 60000, which is 25 percent, rounded.")
        self.assertIsNone(reason)

    def test_unrelated_factual_or_numerical_claims_are_still_blocked(self):
        for text, expect in (
                ("Return on investment is 15000 divided by 60000, which is 25%, so the project will certainly beat its competitors.",
                 "not supported"),
                ("Return on investment is 15000 divided by 60000, which is 25%, against an industry average of 12%.",
                 "calculation rejected"),
                ("Return on investment is 15000 divided by 60000, which is 25%, and the firm has two competitors.",
                 "calculation rejected"),
                ("Return on investment is 15000 divided by 60000, which is 25%, and inflation was three times higher.",
                 "calculation rejected")):
            with self.subTest(text=text[-40:]):
                clean, reason = self.validate(text)
                self.assertIsNone(clean)
                self.assertIn(expect, reason)


class SafetyTests(unittest.TestCase):
    def test_the_module_never_executes_text(self):
        import re

        source = (Path(__file__).resolve().parents[1] / "src" / "university_jarvis" / "calculation.py").read_text()
        code = re.sub(r'"""[\s\S]*?"""|#.*', "", source)
        for banned in (r"\beval\s*\(", r"\bexec\s*\(", r"(?<![.\w])compile\s*\(", r"import\s+ast", r"__import__", r"\bgetattr\s*\(",
                       r"subprocess", r"\bopen\s*\("):
            self.assertIsNone(re.search(banned, code), banned)

    def test_every_number_is_decimal_not_float(self):
        self.assertEqual(check(mean_spec("0.1", "0.3", "0.33", 2), question="A total of 0.1 over a count of 0.3.",
                               expected="The mean is 0.33.").status, VERIFIED)


class VerdictTests(unittest.TestCase):
    def test_verified_requires_everything(self):
        v = check(mean_spec())
        self.assertEqual((v.status, v.value), (VERIFIED, "0.67"))
        self.assertTrue(v.verified)

    def test_wrong_result_formula_and_reversed_operands_are_rejected(self):
        self.assertEqual(check(mean_spec(value="0.66"), expected="The mean is 0.66.").status, REJECTED)
        self.assertEqual(check(mean_spec(formula="t * c", value="6"), expected="The mean is 6.").status, REJECTED)
        v = check(mean_spec(formula="c / t", value="1.5", decimals=1), expected="The mean is 1.5.")
        self.assertEqual(v.status, REJECTED)
        self.assertIn("contradicts", v.reason)

    def test_formula_not_stated_by_the_passage_is_inconclusive_even_if_the_arithmetic_is_right(self):
        v = check(mean_spec(), page="Retail inventory turnover measures how many times stock is sold.")
        self.assertEqual(v.status, INCONCLUSIVE)
        self.assertEqual(check(mean_spec(), page="").status, INCONCLUSIVE)
        self.assertEqual(check(mean_spec(formula="t / c / 1"), page="The mean is the total divided by the count divided by one.").status,
                         INCONCLUSIVE)  # an ambiguous multi-operator clause is never matched

    def test_expected_answer_must_state_the_result(self):
        self.assertEqual(check(mean_spec(), expected="The mean is the total divided by the count.").status, REJECTED)
        self.assertEqual(check(mean_spec(), expected="The mean is 0.67.").status, VERIFIED)
        self.assertEqual(check(mean_spec(), expected="See page 0.67.").status, REJECTED)  # a place, not a value
        self.assertEqual(check(mean_spec(), expected="It is on page 67.").status, REJECTED)

    def test_inputs_must_come_from_their_source(self):
        self.assertEqual(check(mean_spec(total="9", value="3", decimals=None), expected="The mean is 3.").status, REJECTED)
        # both numbers are in the question, but each sits next to the other's name: swapped inputs are not trusted
        swapped = check(mean_spec(total="3", count="2", value="1.5", decimals=1), expected="The mean is 1.5.")
        self.assertEqual(swapped.status, INCONCLUSIVE)
        self.assertIn("different quantity", swapped.reason)
        wrong_source = mean_spec()
        wrong_source["inputs"][0]["source"] = "CITED"
        self.assertEqual(check(wrong_source).status, REJECTED)
        cited = mean_spec()
        cited["inputs"][0]["source"] = "CITED"
        self.assertEqual(check(cited, page=MEAN + " In the example the total is 2.").status, VERIFIED)

    def test_signs_percentages_and_decimals(self):
        profit = lambda q, v, rev="200", cost="350", e="Profit is negative 150.": check(  # noqa: E731
            spec([("rev", "revenue", rev, ""), ("cost", "cost", cost, "")], [("p", "profit", "rev - cost")], v),
            question=q, expected=e, page=PROFIT)
        q = "A firm has revenue of 200 and cost of 350. What is its profit?"
        self.assertEqual(profit(q, "-150").status, VERIFIED)
        self.assertEqual(profit(q, "150", e="Profit is 150.").status, REJECTED)
        # a sign the question does not state is not guessed
        self.assertEqual(profit("A firm has revenue of 5 and cost of 3. What is its profit?", "-8", rev="-5",
                                cost="3", e="Profit is negative 8.").status, INCONCLUSIVE)
        sale = "The sale price is the original price multiplied by one minus the discount rate."
        q = "An item costs 80 and the discount is 25%. What is the sale price?"
        as_percent = spec([("p", "original price", "80", ""), ("r", "discount rate", "25", "%")],
                          [("s", "sale price", "p * (1 - r)")], "60")
        as_plain = spec([("p", "original price", "80", ""), ("r", "discount rate", "25", "")],
                        [("s", "sale price", "p * (1 - r)")], "-1920")
        as_decimal = spec([("p", "original price", "80", ""), ("r", "discount rate", "0.25", "")],
                          [("s", "sale price", "p * (1 - r)")], "60")
        self.assertEqual(check(as_percent, question=q, expected="The sale price is 60.", page=sale).status, VERIFIED)
        self.assertEqual(check(as_decimal, question=q, expected="The sale price is 60.", page=sale).status, VERIFIED)
        plain = check(as_plain, question=q, expected="The sale price is negative 1920.", page=sale)
        self.assertEqual(plain.status, REJECTED)
        self.assertIn("percentage", plain.reason)

    def test_unit_conversion_and_dimension_checks(self):
        speed = "Average speed is calculated as the distance travelled divided by the time taken."
        q = "A runner's distance travelled is 1500 m and the time taken is 30 min. What is the average speed in km/h?"
        run = lambda value, unit, e: check(  # noqa: E731
            spec([("d", "distance travelled", "1500", "m"), ("t", "time taken", "30", "min")],
                 [("v", "average speed", "d / t")], value, unit), question=q, expected=e, page=speed)
        self.assertEqual(run("3", "km/h", "The speed is 3 km/h.").status, VERIFIED)
        self.assertEqual(run("50", "km/h", "The speed is 50 km/h.").status, REJECTED)
        self.assertEqual(run("3", "kg", "The speed is 3.").status, REJECTED)  # known, incompatible dimension
        self.assertEqual(run("3", "bananas", "The speed is 3.").status, INCONCLUSIVE)  # opaque unit: not guessed

    def test_rounding_boundaries(self):
        q = "A total of 5 is shared over a count of 8. What is the mean?"
        run = lambda value, d: check(mean_spec("5", "8", value, d), question=q, expected=f"The mean is {value}.")  # noqa: E731
        self.assertEqual(run("0.63", 2).status, VERIFIED)          # half-up is the stated convention
        self.assertEqual(run("0.62", 2).status, INCONCLUSIVE)      # the other tie convention: not accepted, not rejected
        self.assertEqual(run("0.64", 2).status, REJECTED)
        self.assertEqual(run("0.625", None).status, VERIFIED)
        irrational = check(mean_spec(value="0.6667", decimals=None), expected="The mean is 0.6667.")
        self.assertEqual(irrational.status, INCONCLUSIVE)          # rounding unstated for a non-terminating result

    def test_multi_step_each_step_is_grounded(self):
        q = "A firm has revenue of 500 and cost of 320. What is its profit margin?"
        inputs = [("rev", "revenue", "500", ""), ("cost", "cost", "320", "")]
        good = spec(inputs, [("p", "profit", "rev - cost"), ("m", "profit margin", "p / rev")], "36", "%")
        self.assertEqual(check(good, question=q, expected="The margin is 36%.", page=PROFIT).status, VERIFIED)
        bad_first = spec(inputs, [("p", "profit", "rev + cost"), ("m", "profit margin", "p / rev")], "164", "%")
        self.assertEqual(check(bad_first, question=q, expected="The margin is 164%.", page=PROFIT).status, REJECTED)
        bad_last = spec(inputs, [("p", "profit", "rev - cost"), ("m", "profit margin", "p / cost")], "56.25", "%")
        self.assertNotEqual(check(bad_last, question=q, expected="The margin is 56.25%.", page=PROFIT).status, VERIFIED)

    def test_constants_must_be_structural_or_stated(self):
        sale = "The sale price is the original price multiplied by one minus the discount rate."
        q = "An item costs 80 and the discount is 25%. What is the sale price?"
        sp = spec([("p", "original price", "80", "")], [("s", "sale price", "p * (1 - 0.25)")], "60")
        self.assertEqual(check(sp, question=q, expected="The sale price is 60.", page=sale).status, INCONCLUSIVE)

    def test_malformed_specifications_are_rejected_not_raised(self):
        for bad in (None, "x", [], {}, {"inputs": [], "steps": [], "result": {}}, {**mean_spec(), "extra": 1},
                    mean_spec(decimals=True), mean_spec(decimals=99), mean_spec(value="1e5"), mean_spec(value="NaN"),
                    mean_spec(formula="t / (c - c)")):
            with self.subTest(spec=str(bad)[:60]):
                v = check(bad)
                self.assertIn(v.status, (REJECTED, INCONCLUSIVE) if bad is not None else (REJECTED,))
                self.assertFalse(v.verified)

    def test_unknown_variables_and_duplicates_are_rejected(self):
        self.assertEqual(check(mean_spec(formula="t / z")).status, REJECTED)
        dup = mean_spec()
        dup["inputs"][1]["name"] = "t"
        self.assertEqual(check(dup).status, REJECTED)


class PolicyTests(unittest.TestCase):
    PAGE = "The mean cell size is calculated as the total length divided by the number of cells. Cells are small."
    Q = "Several cells have a total length of 60 and the number of cells is 12. What is the mean cell size?"
    A = "The mean cell size is the total length divided by the number of cells, which is 5."
    CITE = [{"source_id": "s1", "pdf_page": 1}]
    SPEC = spec([("tl", "total length", "60", ""), ("nc", "number of cells", "12", "")],
                [("m", "mean cell size", "tl / nc")], "5")

    def validate(self, calculation=None, expected=None):
        raw = {"question": self.Q, "expected_answer": expected or self.A, "citations": self.CITE}
        if calculation is not None:
            raw["calculation"] = calculation
        return tp.validate_question(
            raw, step="FOLLOW_UP", citations_ok=lambda c: None, cited_text=lambda c: self.PAGE, shown=[],
            prior_questions=["What are cells?"], prior_answers=[], unrevealed_answers=[],
            concept_text="cells mean size total length number")

    def test_verified_calculation_passes_and_is_returned(self):
        clean, reason = self.validate(self.SPEC)
        self.assertIsNone(reason)
        self.assertEqual(clean["calculation"], self.SPEC)
        self.assertEqual(clean["checks"]["calculation"], VERIFIED)

    def test_unverified_calculation_is_refused_with_its_reason(self):
        wrong = deepcopy(self.SPEC)
        wrong["result"]["value"] = "6"
        clean, reason = self.validate(wrong, expected=self.A.replace("5", "6"))
        self.assertIsNone(clean)
        self.assertIn("calculation rejected", reason)

    def test_a_computed_answer_cannot_skip_the_specification(self):
        clean, reason = self.validate()
        self.assertIsNone(clean)
        self.assertIn("needs a verified calculation", reason)
        clean, reason = self.validate(self.SPEC)
        self.assertIsNone(reason)

    def test_questions_that_only_mention_numbers_need_no_specification(self):
        page = "The study began in 1998 and followed 400 children for twelve years. Significance is set at 0.05."
        for question, expected in (("When did the study begin?", "It began in 1998."),
                                   ("How many children did the study follow, and for how long?",
                                    "It followed 400 children for 12 years."),
                                   ("At what level is significance set?", "Significance is set at 0.05.")):
            with self.subTest(question=question):
                self.assertIsNone(tp.requires_calculation(question, expected, [page]))
        self.assertIsNotNone(tp.requires_calculation("How many years did the study run?", "It ran for 15 years.", [page]))
        self.assertIsNotNone(tp.requires_calculation("Calculate the total of 5 items costing 4.", "The total is 4.",
                                                     ["Total is price times quantity. 4 is typical."]))

    def test_reference_problem_gates_on_the_calculation(self):
        refs = [{"source_id": "s1", "pdf_page": 1, "fingerprint": {"v": 1}}]
        contexts = [{"source_id": "s1", "excerpts": [{"pdf_page": 1, "text": self.PAGE}]}]
        problem = lambda calc, ref=self.A: tp.reference_problem(ref, refs, contexts, calculation=calc, question=self.Q)  # noqa: E731
        self.assertIsNone(problem(self.SPEC))
        self.assertIn("rejected", problem({**self.SPEC, "result": {**self.SPEC["result"], "value": "6"}}))
        vague = [{"source_id": "s1", "excerpts": [{"pdf_page": 1, "text": "The mean cell size, total length and "
                                                                          "number of cells are discussed in lecture."}]}]
        self.assertIn("inconclusive", tp.reference_problem(self.A, refs, vague, calculation=self.SPEC, question=self.Q))
        self.assertIsNone(tp.reference_problem(self.A, refs, contexts, calculation=None, question=self.Q))


CALC_PASSAGE = (seq.PASSAGE + " The mean cell size is calculated as the total length divided by the number of cells.")
CALC_SPEC = spec([("tl", "total length", "60", ""), ("nc", "number of cells", "12", "")],
                 [("m", "mean cell size", "tl / nc")], "5")
CALC_QUESTION = {
    "question": "Several living cells have a total length of 60 and the number of cells is 12. What is the mean cell size?",
    "expected_answer": "The mean cell size is the total length divided by the number of cells, so 60 divided by 12 is 5.",
    "citations": seq.CITE, "calculation": CALC_SPEC}


class TutoringIntegrationTests(seq.SequenceBase):
    def setUp(self):
        super().setUp()
        self.passage = CALC_PASSAGE

    def open_calc_question(self, question=CALC_QUESTION, feedback=("partial",)):
        self.script(list(feedback) + ["correct"] * 3, [question])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        return session, self.nxt(session)

    def test_a_verified_calculation_opens_and_is_kept_out_of_the_student_view(self):
        session, opened = self.open_calc_question()
        view = opened["session"]
        self.assertEqual(opened["tutor"]["kind"], "QUESTION")
        self.assertNotIn("calculation", view["task"])
        self.assertNotIn("expected_answer", view["task"])
        self.assertTrue(all("calculation" not in q["task"] for q in view["questions"]))
        self.assertNotIn("calculation", str(view["turns"]))
        stored = tutoring._read(self.session_file(session), "BIO101", 1)
        self.assertEqual(stored["questions"][1]["task"]["calculation"], CALC_SPEC)
        self.assertEqual(stored["questions"][1]["generated"]["checks"]["calculation"], VERIFIED)
        self.assertEqual(stored["questions"][1]["generated"]["prompt_version"], "tutor-question-v3")

    def assert_never_opens(self, change):
        bad = deepcopy(CALC_QUESTION)
        change(bad)
        self.script(["partial"], [bad, bad, bad])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        with self.assertRaises(tutoring.ReplyRejected):
            self.nxt(session)
        view = self.view(session)
        self.assertEqual(len(view["questions"]), 1)
        self.assertNotIn(bad["question"], " ".join(t.get("text") or "" for t in view["turns"]))

    def test_a_wrong_result_never_opens_a_question(self):
        self.assert_never_opens(lambda q: q["calculation"]["result"].update(value="6"))

    def test_a_wrong_formula_never_opens_a_question(self):
        self.assert_never_opens(lambda q: q["calculation"]["steps"][0].update(formula="tl * nc"))

    def test_a_wrong_input_never_opens_a_question(self):
        self.assert_never_opens(lambda q: q["calculation"]["inputs"][0].update(value="61"))

    def test_an_unverifiable_calculation_degrades_to_the_fixed_fallback(self):
        bad = deepcopy(CALC_QUESTION)
        bad["calculation"]["steps"][0]["formula"] = "tl * nc"
        self.script(["partial"], [bad, bad])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        for turn in ("n1", "n1", "n1"):
            try:
                result = self.nxt(session, turn)
            except tutoring.ReplyRejected:
                continue
            break
        self.assertEqual(len(self.view(session)["questions"]), 1)
        self.assertEqual(result["tutor"]["text"], tutoring.FALLBACK_QUESTION)

    def test_tampered_calculation_blocks_grading_hints_and_reveal(self):
        session, opened = self.open_calc_question()
        path = self.session_file(session)
        stored = tutoring._read(path, "BIO101", 1)
        for key in ("task",):
            stored[key]["calculation"]["result"]["value"] = "7"
        stored["questions"][1]["task"]["calculation"]["result"]["value"] = "7"
        tutoring._write(path, stored)
        calls_before = len(self.provider.calls)
        revealed = self.reveal(session, "rv1")
        self.assertEqual(revealed["tutor"]["kind"], "NOTE")
        self.assertEqual(revealed["tutor"]["text"], tutoring.REFERENCE_UNVERIFIED_REPLY)
        hint = self.hint(session, "h1")                       # level 1 is a pointer to the source
        hint = self.hint(session, "h2")                       # level 2 would use the reference: it must not
        self.assertNotIn("60 divided by 12", hint["tutor"]["text"])
        graded = self.answer(session, "a2", "It is 5")
        self.assertEqual(graded["diagnosis"], "unclear")
        self.assertEqual([c["action"] for c in self.provider.calls[calls_before:] if c.get("action") == "FEEDBACK"], [])
        self.assertEqual(self.learning()["evidence"][-1]["evaluation"]["basis"], "REFERENCE_NOT_SUPPORTED")

    def test_a_verified_calculation_is_graded_and_revealed_normally(self):
        session, opened = self.open_calc_question()
        graded = self.answer(session, "a2", "The total divided by the number gives 5")
        self.assertEqual(graded["diagnosis"], "correct")
        self.assertEqual(self.reveal(session, "rv1")["tutor"]["kind"], "REVEAL")

    def test_questions_without_a_calculation_are_unchanged(self):
        self.script(["partial"], [seq.FOLLOW])
        session = self.create("TEST_ME")
        self.answer(session, "a1", "Cells are units")
        opened = self.nxt(session)
        stored = tutoring._read(self.session_file(session), "BIO101", 1)
        self.assertNotIn("calculation", stored["questions"][1]["task"])
        self.assertNotIn("calculation", stored["questions"][1]["generated"]["checks"])
        self.assertEqual(opened["tutor"]["kind"], "QUESTION")

    def test_the_model_schema_carries_an_optional_calculation(self):
        props = tutoring.TUTOR_QUESTION_FORMAT["schema"]["properties"]
        self.assertIn("calculation", props)
        self.assertIn("calculation", tutoring.TUTOR_QUESTION_FORMAT["schema"]["required"])
        self.assertIn("null", props["calculation"]["type"])


if __name__ == "__main__":
    unittest.main()
