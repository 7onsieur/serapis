"""Stage 3 adversarial cases (independent mathematical verification). Kept apart from the frozen 164-case corpus.

Gold labels were written from the passage and question text before the verifier ran on them.
  ACCEPT        the calculation is right and its formula is stated by the passage.
  REJECT        something is wrong (arithmetic, operator, operand order, units, sign, percentage handling, malformed or
                unsafe formula). A verifier that answers INCONCLUSIVE here still blocks it; that is tallied apart as
                SAFE_BLOCK because it is not a rejection for the right reason.
  INCONCLUSIVE  nothing is wrong that can be shown, but the formula or a constant is not grounded in the sources, or the
                rounding is ambiguous. It must be blocked and must not be reported as correct.

``KNOWN_LIMIT`` marks cases where the right answer needs meaning the verifier cannot see; they are expected to fail and
are reported as such, never hidden.
"""

from __future__ import annotations

import corpus as C

ECO, STA, FIN = (C.SUBJECTS[k] for k in ("economics", "statistics", "finance"))


def inp(name, label, value, unit="", source="QUESTION"):
    return {"name": name, "label": label, "value": value, "unit": unit, "source": source}


def step(name, label, formula):
    return {"name": name, "label": label, "formula": formula}


def spec(inputs, steps, value, unit="", decimals=None):
    return {"inputs": inputs, "steps": steps, "result": {"value": value, "unit": unit, "decimals": decimals}}


P_PROFIT = "Profit is revenue minus cost. Profit margin is calculated as profit divided by revenue."
P_SPEED = "Average speed is calculated as the distance travelled divided by the time taken."
P_DISCOUNT = "The sale price is the original price multiplied by one minus the discount rate."
P_MEAN = "The mean is the total divided by the count."
P_AREA = "Area equals length multiplied by width."
P_TOTAL = "The total is the length plus the width."
P_INTEREST = "Simple interest equals the principal multiplied by the rate multiplied by the time."
P_UNRELATED = "Retail inventory turnover measures how many times stock is sold and replaced in a year."

Q_PROFIT = "A firm has revenue of 500 and cost of 320. What is its profit?"
PROFIT_IN = [inp("rev", "revenue", "500"), inp("cost", "cost", "320")]
Q_SALE = "An item costs 80 and the discount is 25%. What is the sale price?"
Q_SPEED = "A cyclist travels 150 km in 2 h. What is the average speed?"
Q_MEAN = "A total of 2 is shared over a count of 3. What is the mean?"
SE_IN = [inp("s", "sample standard deviation", "10"), inp("n", "sample size", "25")]
Q_SE = "A sample has standard deviation 10 and size 25. What is the standard error of the mean?"
SE_P, ECO_P, FIN_P = STA["pages"][0], ECO["pages"][0], FIN["pages"][0]

# (case id, category, question, expected answer, passage, spec, gold)
ENGINE = [
    # arithmetic and operators
    ("arith_valid", "arithmetic", Q_PROFIT, "Profit is 500 minus 320, which is 180.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost")], "180"), "ACCEPT"),
    ("arith_wrong_result", "arithmetic", Q_PROFIT, "Profit is 500 minus 320, which is 280.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost")], "280"), "REJECT"),
    ("arith_wrong_operator", "arithmetic", Q_PROFIT, "Profit is 500 plus 320, which is 820.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev + cost")], "820"), "REJECT"),
    ("arith_reversed_operands", "reversed_operands", Q_PROFIT, "Profit is 320 minus 500, which is negative 180.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "cost - rev")], "-180"), "REJECT"),
    ("arith_result_not_in_answer", "arithmetic", Q_PROFIT, "Profit is revenue minus cost.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost")], "180"), "REJECT"),
    ("arith_input_not_in_question", "arithmetic", Q_PROFIT, "Profit is 600 minus 320, which is 280.", P_PROFIT,
     spec([inp("rev", "revenue", "600"), inp("cost", "cost", "320")], [step("p", "profit", "rev - cost")], "280"),
     "REJECT"),
    ("arith_input_wrong_source", "arithmetic", Q_PROFIT, "Profit is 500 minus 320, which is 180.", P_PROFIT,
     spec([inp("rev", "revenue", "500", source="CITED"), inp("cost", "cost", "320")],
          [step("p", "profit", "rev - cost")], "180"), "REJECT"),
    # inputs assigned to the wrong quantity (the numbers are all in the question)
    ("swapped_inputs_mean", "swapped_inputs", Q_MEAN, "The mean is 1.5 to one place.", P_MEAN,
     spec([inp("t", "total", "3"), inp("c", "count", "2")], [step("m", "mean", "t / c")], "1.5", "", 1), "REJECT"),
    ("swapped_inputs_standard_error", "swapped_inputs", Q_SE, "The standard error is 7.9 to one place.", SE_P,
     spec([inp("s", "sample standard deviation", "25"), inp("n", "sample size", "10")],
          [step("se", "standard error", "s / sqrt(n)")], "7.9", "", 1), "REJECT"),
    ("swapped_inputs_not_detected_when_number_precedes_name", "swapped_inputs",
     "The values are 2 for the total and 3 for the count. What is the mean?", "The mean is 1.5 to one place.", P_MEAN,
     spec([inp("t", "total", "3"), inp("c", "count", "2")], [step("m", "mean", "t / c")], "1.5", "", 1), "KNOWN_LIMIT"),
    # negative values
    ("negative_result_valid", "negative_values", "A firm has revenue of 200 and cost of 350. What is its profit?",
     "Profit is 200 minus 350, which is negative 150.", P_PROFIT,
     spec([inp("rev", "revenue", "200"), inp("cost", "cost", "350")], [step("p", "profit", "rev - cost")], "-150"),
     "ACCEPT"),
    ("negative_result_sign_dropped", "negative_values", "A firm has revenue of 200 and cost of 350. What is its profit?",
     "Profit is 150.", P_PROFIT,
     spec([inp("rev", "revenue", "200"), inp("cost", "cost", "350")], [step("p", "profit", "rev - cost")], "150"),
     "REJECT"),
    ("negative_input_sign_unsupported", "negative_values", "A firm has revenue of 5 and cost of 3. What is its profit?",
     "Profit is negative 5 minus 3, which is negative 8.", P_PROFIT,
     spec([inp("rev", "revenue", "-5"), inp("cost", "cost", "3")], [step("p", "profit", "rev - cost")], "-8"),
     "INCONCLUSIVE"),
    ("negative_input_with_cue_valid", "negative_values",
     "Quantity demanded falls by 20% when price rises by 10%. What is the price elasticity of demand?",
     "It is minus 20 divided by 10, which is negative 2.", ECO_P,
     spec([inp("dq", "percentage change in quantity demanded", "-20", "%"),
           inp("dp", "percentage change in price", "10", "%")],
          [step("e", "price elasticity of demand", "dq / dp")], "-2"), "ACCEPT"),
    ("negative_direction_ignored", "negative_values",
     "Quantity demanded falls by 20% when price rises by 10%. What is the price elasticity of demand?",
     "It is 20 divided by 10, which is 2.", ECO_P,
     spec([inp("dq", "percentage change in quantity demanded", "20", "%"),
           inp("dp", "percentage change in price", "10", "%")],
          [step("e", "price elasticity of demand", "dq / dp")], "2"), "KNOWN_LIMIT"),
    # percentages versus decimals
    ("percent_valid", "percentages", Q_SALE, "The sale price is 80 multiplied by one minus 0.25, which is 60.", P_DISCOUNT,
     spec([inp("price", "original price", "80"), inp("rate", "discount rate", "25", "%")],
          [step("sp", "sale price", "price * (1 - rate)")], "60"), "ACCEPT"),
    ("percent_as_plain_number", "percentages", Q_SALE, "The sale price is 80 times one minus 25, which is negative 1920.",
     P_DISCOUNT, spec([inp("price", "original price", "80"), inp("rate", "discount rate", "25")],
                      [step("sp", "sale price", "price * (1 - rate)")], "-1920"), "REJECT"),
    ("percent_decimal_equivalent", "percentages", Q_SALE, "The sale price is 80 multiplied by 0.75, which is 60.",
     P_DISCOUNT, spec([inp("price", "original price", "80"), inp("rate", "discount rate", "0.25")],
                      [step("sp", "sale price", "price * (1 - rate)")], "60"), "ACCEPT"),
    ("percent_result_valid", "percentages", "A firm has revenue of 500 and cost of 320. What is its profit margin?",
     "The profit margin is 36%.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost"), step("m", "profit margin", "p / rev")], "36", "%"), "ACCEPT"),
    ("percent_result_decimal_claimed_as_percent", "percentages",
     "A firm has revenue of 500 and cost of 320. What is its profit margin?", "The profit margin is 0.36%.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost"), step("m", "profit margin", "p / rev")], "0.36", "%"), "REJECT"),
    ("percent_result_percent_claimed_as_decimal", "percentages",
     "A firm has revenue of 500 and cost of 320. What is its profit margin?", "The profit margin is 36.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost"), step("m", "profit margin", "p / rev")], "36"), "REJECT"),
    ("percent_unit_without_percent_in_source", "percentages", "An item costs 80 and the discount is 0.25. What is the sale price?",
     "The sale price is 60.", P_DISCOUNT,
     spec([inp("price", "original price", "80"), inp("rate", "discount rate", "0.25", "%")],
          [step("sp", "sale price", "price * (1 - rate)")], "60"), "INCONCLUSIVE"),
    # units and conversions
    ("units_valid", "units", Q_SPEED, "The average speed is 150 divided by 2, which is 75 km/h.", P_SPEED,
     spec([inp("d", "distance travelled", "150", "km"), inp("t", "time taken", "2", "h")],
          [step("v", "average speed", "d / t")], "75", "km/h"), "ACCEPT"),
    ("units_conversion_valid", "units", "A runner covers 1500 m in 30 min. What is the average speed in km/h?",
     "The average speed is 3 km/h.", P_SPEED,
     spec([inp("d", "distance travelled", "1500", "m"), inp("t", "time taken", "30", "min")],
          [step("v", "average speed", "d / t")], "3", "km/h"), "ACCEPT"),
    ("units_conversion_forgotten", "units", "A runner covers 1500 m in 30 min. What is the average speed in m/s?",
     "The average speed is 50 m/s.", P_SPEED,
     spec([inp("d", "distance travelled", "1500", "m"), inp("t", "time taken", "30", "min")],
          [step("v", "average speed", "d / t")], "50", "m/s"), "REJECT"),
    ("units_result_unit_wrong_dimension", "units", Q_SPEED, "The average speed is 75.", P_SPEED,
     spec([inp("d", "distance travelled", "150", "km"), inp("t", "time taken", "2", "h")],
          [step("v", "average speed", "d / t")], "75", ""), "REJECT"),
    ("units_add_incompatible", "units", "A rectangle has length 5 m and width 3 s. What is the total?",
     "The total is 8.", P_TOTAL,
     spec([inp("l", "length", "5", "m"), inp("w", "width", "3", "s")], [step("t", "total", "l + w")], "8", "m"), "REJECT"),
    ("units_add_converted", "units", "A rectangle has length 5 m and width 300 cm. What is the total in m?",
     "The total is 8 m.", P_TOTAL,
     spec([inp("l", "length", "5", "m"), inp("w", "width", "300", "cm")], [step("t", "total", "l + w")], "8", "m"),
     "ACCEPT"),
    ("units_area", "units", "A rectangle has length 5 m and width 3 m. What is the area?", "The area is 15 m^2.", P_AREA,
     spec([inp("l", "length", "5", "m"), inp("w", "width", "3", "m")], [step("a", "area", "l * w")], "15", "m^2"),
     "ACCEPT"),
    ("units_opaque_mismatch", "units", "A rectangle has length 5 apples and width 3 apples. What is the total?",
     "The total is 8 pears.", P_TOTAL,
     spec([inp("l", "length", "5", "apples"), inp("w", "width", "3", "apples")], [step("t", "total", "l + w")], "8",
          "pears"), "INCONCLUSIVE"),
    ("units_temperature", "units", "The mean of a total of 40 over a count of 2 is wanted. The unit is degrees.",
     "The mean is 20.", P_MEAN,
     spec([inp("t", "total", "40", "°C"), inp("c", "count", "2")], [step("m", "mean", "t / c")], "20", "°C"),
     "INCONCLUSIVE"),
    # rounding
    ("round_valid", "rounding", Q_MEAN, "The mean is 2 divided by 3, which is 0.67 to two places.", P_MEAN,
     spec([inp("t", "total", "2"), inp("c", "count", "3")], [step("m", "mean", "t / c")], "0.67", "", 2), "ACCEPT"),
    ("round_wrong_digit", "rounding", Q_MEAN, "The mean is 2 divided by 3, which is 0.66 to two places.", P_MEAN,
     spec([inp("t", "total", "2"), inp("c", "count", "3")], [step("m", "mean", "t / c")], "0.66", "", 2), "REJECT"),
    ("round_boundary_half_up", "rounding", "A total of 5 is shared over a count of 8. What is the mean?",
     "The mean is 0.63 to two places.", P_MEAN,
     spec([inp("t", "total", "5"), inp("c", "count", "8")], [step("m", "mean", "t / c")], "0.63", "", 2), "ACCEPT"),
    ("round_boundary_tie_other_convention", "rounding", "A total of 5 is shared over a count of 8. What is the mean?",
     "The mean is 0.62 to two places.", P_MEAN,
     spec([inp("t", "total", "5"), inp("c", "count", "8")], [step("m", "mean", "t / c")], "0.62", "", 2),
     "INCONCLUSIVE"),
    ("round_not_stated", "rounding", Q_MEAN, "The mean is 0.6667.", P_MEAN,
     spec([inp("t", "total", "2"), inp("c", "count", "3")], [step("m", "mean", "t / c")], "0.6667"), "INCONCLUSIVE"),
    ("round_exact_without_decimals", "rounding", "A total of 10 is shared over a count of 4. What is the mean?",
     "The mean is 2.5.", P_MEAN,
     spec([inp("t", "total", "10"), inp("c", "count", "4")], [step("m", "mean", "t / c")], "2.5"), "ACCEPT"),
    ("round_down_valid", "rounding", "A total of 5 is shared over a count of 6. What is the mean?",
     "The mean is 0.83 to two places.", P_MEAN,
     spec([inp("t", "total", "5"), inp("c", "count", "6")], [step("m", "mean", "t / c")], "0.83", "", 2), "ACCEPT"),
    ("round_up_wrong", "rounding", "A total of 5 is shared over a count of 6. What is the mean?",
     "The mean is 0.9 to one place.", P_MEAN,
     spec([inp("t", "total", "5"), inp("c", "count", "6")], [step("m", "mean", "t / c")], "0.9", "", 1), "REJECT"),
    # multi-step
    ("multi_valid", "multi_step", "A firm has revenue of 500 and cost of 320. What is its profit margin?",
     "Profit is 180 and the profit margin is 36%.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost"), step("m", "profit margin", "p / rev")], "36", "%"), "ACCEPT"),
    ("multi_wrong_final_step", "multi_step", "A firm has revenue of 500 and cost of 320. What is its profit margin?",
     "Profit is 180 and the profit margin is 56.25%.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost"), step("m", "profit margin", "p / cost")], "56.25", "%"),
     "REJECT"),
    ("multi_wrong_first_step", "multi_step", "A firm has revenue of 500 and cost of 320. What is its profit margin?",
     "Profit is 820 and the profit margin is 164%.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev + cost"), step("m", "profit margin", "p / rev")], "164", "%"), "REJECT"),
    ("multi_wrong_final_result", "multi_step", "A firm has revenue of 500 and cost of 320. What is its profit margin?",
     "Profit is 180 and the profit margin is 18%.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost"), step("m", "profit margin", "p / rev")], "18", "%"), "REJECT"),
    # missing or unsupported formulas
    ("formula_not_in_passage", "unsupported_formula", Q_PROFIT, "Profit is 500 minus 320, which is 180.", P_UNRELATED,
     spec(PROFIT_IN, [step("p", "profit", "rev - cost")], "180"), "INCONCLUSIVE"),
    ("formula_three_factor", "unsupported_formula", "A principal of 1000 earns a rate of 5% over a time of 2 years. What is the simple interest?",
     "The simple interest is 100.", P_INTEREST,
     spec([inp("p", "principal", "1000"), inp("r", "rate", "5", "%"), inp("t", "time", "2", "years")],
          [step("i", "simple interest", "p * r * t")], "100", ""), "INCONCLUSIVE"),
    ("formula_constant_not_in_sources", "unsupported_formula", Q_SALE, "The sale price is 80 times 0.75, which is 60.",
     P_DISCOUNT, spec([inp("price", "original price", "80")], [step("sp", "sale price", "price * (1 - 0.25)")], "60"),
     "INCONCLUSIVE"),
    ("formula_conversion_constant_not_in_sources", "unsupported_formula",
     "A runner covers 1500 m in 30 min. What is the average speed in m/s?", "The average speed is 0.83 m/s.", P_SPEED,
     spec([inp("d", "distance travelled", "1500", "m"), inp("t", "time taken", "30", "min")],
          [step("v", "average speed", "d / (t * 60)")], "0.83", "m/s", 2), "INCONCLUSIVE"),
    ("formula_no_cited_page", "unsupported_formula", Q_PROFIT, "Profit is 500 minus 320, which is 180.", "",
     spec(PROFIT_IN, [step("p", "profit", "rev - cost")], "180"), "INCONCLUSIVE"),
    ("formula_no_operator_step", "unsupported_formula", Q_PROFIT, "Profit is 500, which is 500.", P_PROFIT,
     spec(PROFIT_IN, [step("p", "profit", "rev")], "500"), "INCONCLUSIVE"),
    # division by zero
    ("zero_count", "division_by_zero", "A total of 6 is shared over a count of 0. What is the mean?", "The mean is 6.",
     P_MEAN, spec([inp("t", "total", "6"), inp("c", "count", "0")], [step("m", "mean", "t / c")], "6"), "REJECT"),
    ("zero_denominator_expression", "division_by_zero", Q_MEAN, "The mean is 6.", P_MEAN,
     spec([inp("t", "total", "2"), inp("c", "count", "3")], [step("m", "mean", "t / (c - c)")], "6"), "REJECT"),
    ("sqrt_negative", "division_by_zero", Q_SE, "The standard error is 2.", SE_P,
     spec(SE_IN, [step("se", "standard error", "s / sqrt(0 - n)")], "2"), "REJECT"),
    # malformed or malicious formulas (the specification is otherwise valid)
    *[(f"malicious_{name}", "malicious", Q_SE, "The standard error is 2.", SE_P,
       spec(SE_IN, [step("se", "standard error", formula)], "2"), "REJECT") for name, formula in [
        ("import", "__import__('os').system('ls')"), ("open_file", "open('/etc/passwd')"),
        ("attribute", "s.__class__"), ("eval_call", "eval('1')"), ("exec_call", "exec('x=1')"),
        ("power_tower", "9 ** 9 ** 9"), ("huge_power", "10 ^ 400"), ("trailing_operator", "s /"),
        ("implicit_multiplication", "2s"), ("unknown_variable", "s / sqrt(m)"), ("semicolon", "s; n"),
        ("empty", ""), ("too_long", "s + " * 80 + "s"), ("fullwidth_plus", "s ＋ n"),
        ("deep_nesting", "(" * 40 + "s" + ")" * 40), ("scientific_notation", "1e400"),
        ("keyword_name", "True"), ("lambda", "lambda: 1"), ("comprehension", "[s for s in n]"),
        ("subscript", "s[0]"), ("comma", "sqrt(s, n)"), ("unsupported_function", "log(s)"),
        ("unbalanced", "(s / n"), ("comment", "s / n # hide"), ("string", "'s'"), ("newline", "s\n/ n"),
        ("division_by_literal_zero", "s / 0"), ("modulo", "s % n"), ("floor_division", "s // n"),
        ("bitwise", "s | n"), ("walrus", "(x := s)"), ("backtick", "`s`"), ("dunder_name", "__s__")]],
    ("malicious_not_a_mapping", "malicious", Q_SE, "The standard error is 2.", SE_P, "s / sqrt(n)", "REJECT"),
    ("malicious_extra_key", "malicious", Q_SE, "The standard error is 2.", SE_P,
     {**spec(SE_IN, [step("se", "standard error", "s / sqrt(n)")], "2"), "code": "print(1)"}, "REJECT"),
    ("malicious_oversized_value", "malicious", Q_SE, "The standard error is 2.", SE_P,
     spec([inp("s", "sample standard deviation", "9" * 40), inp("n", "sample size", "25")],
          [step("se", "standard error", "s / sqrt(n)")], "2"), "REJECT"),
    ("malicious_duplicate_name", "malicious", Q_SE, "The standard error is 2.", SE_P,
     spec([inp("s", "sample standard deviation", "10"), inp("s", "sample size", "25")],
          [step("se", "standard error", "s / sqrt(s)")], "2"), "REJECT"),
    ("malicious_name_shadows_function", "malicious", Q_SE, "The standard error is 2.", SE_P,
     spec([inp("sqrt", "sample standard deviation", "10"), inp("n", "sample size", "25")],
          [step("se", "standard error", "sqrt / sqrt(n)")], "2"), "REJECT"),
    # mathematically equivalent valid expressions
    ("equiv_sqrt", "equivalent", Q_SE, "The standard error is 10 divided by 5, which is 2.", SE_P,
     spec(SE_IN, [step("se", "standard error", "s / sqrt(n)")], "2"), "ACCEPT"),
    ("equiv_power_half", "equivalent", Q_SE, "The standard error is 10 divided by 5, which is 2.", SE_P,
     spec(SE_IN, [step("se", "standard error", "s / n ^ 0.5")], "2"), "ACCEPT"),
    ("equiv_double_star", "equivalent", Q_SE, "The standard error is 10 divided by 5, which is 2.", SE_P,
     spec(SE_IN, [step("se", "standard error", "s / n ** 0.5")], "2"), "ACCEPT"),
    ("equiv_parentheses", "equivalent", Q_SE, "The standard error is 10 divided by 5, which is 2.", SE_P,
     spec(SE_IN, [step("se", "standard error", "(s) / (sqrt((n)))")], "2"), "ACCEPT"),
    ("equiv_commutative", "equivalent", "A rectangle has length 5 m and width 3 m. What is the area?",
     "The area is 15 m^2.", P_AREA,
     spec([inp("l", "length", "5", "m"), inp("w", "width", "3", "m")], [step("a", "area", "w * l")], "15", "m^2"),
     "ACCEPT"),
    ("equiv_claimed_trailing_zero", "equivalent", Q_SE, "The standard error is 2.", SE_P,
     spec(SE_IN, [step("se", "standard error", "s / sqrt(n)")], "2.00"), "ACCEPT"),
    ("equiv_inverse_form_not_grounded", "equivalent", Q_SE, "The standard error is 2.", SE_P,
     spec(SE_IN, [step("se", "standard error", "s * n ^ -0.5")], "2"), "INCONCLUSIVE"),
    ("equiv_reordered_sum_in_denominator", "equivalent", "A payment of 1100 is due in one period and the discount rate is 10%. What is its present value?",
     "The present value is 1100 divided by 1.10, which is 1000.", FIN_P,
     spec([inp("fv", "future value", "1100"), inp("r", "discount rate", "10", "%")],
          [step("pv", "present value", "fv / (r + 1)")], "1000"), "ACCEPT"),
]

# Frozen QUANT texts, given a structured specification. gold copied from corpus.QUANT (valid -> ACCEPT, others REJECT).
# (case id, subject, question, expected, spec, gold)
Q = C.QUANT
GENERATED = [
    ("quant_stat_valid", "statistics", Q["statistics"]["question"], Q["statistics"]["valid"],
     spec([inp("s", "sample standard deviation", "10"), inp("n", "sample size", "25")],
          [step("se", "standard error of the mean", "s / sqrt(n)")], "2"), "ACCEPT"),
    ("quant_stat_wrong_arith", "statistics", Q["statistics"]["question"], Q["statistics"]["wrong_arith"],
     spec([inp("s", "sample standard deviation", "10"), inp("n", "sample size", "25")],
          [step("se", "standard error of the mean", "s / n")], "0.4"), "REJECT"),
    ("quant_stat_wrong_arith_same_formula", "statistics", Q["statistics"]["question"], Q["statistics"]["wrong_arith"],
     spec([inp("s", "sample standard deviation", "10"), inp("n", "sample size", "25")],
          [step("se", "standard error of the mean", "s / sqrt(n)")], "0.4"), "REJECT"),
    ("quant_stat_wrong_formula", "statistics", Q["statistics"]["question"], Q["statistics"]["wrong_formula"],
     spec([inp("s", "sample standard deviation", "10"), inp("n", "sample size", "25")],
          [step("se", "standard error of the mean", "s * sqrt(n)")], "50"), "REJECT"),
    ("quant_eco_valid", "economics", Q["economics"]["question"], Q["economics"]["valid"],
     spec([inp("dq", "percentage change in quantity demanded", "-20", "%"),
           inp("dp", "percentage change in price", "10", "%")],
          [step("e", "price elasticity of demand", "dq / dp")], "-2"), "ACCEPT"),
    ("quant_eco_wrong_arith", "economics", Q["economics"]["question"], Q["economics"]["wrong_arith"],
     spec([inp("dq", "percentage change in quantity demanded", "-20", "%"),
           inp("dp", "percentage change in price", "10", "%")],
          [step("e", "price elasticity of demand", "dp / dq")], "-0.5"), "REJECT"),
    ("quant_eco_wrong_formula", "economics", Q["economics"]["question"], Q["economics"]["wrong_formula"],
     spec([inp("dq", "percentage change in quantity demanded", "20", "%"),
           inp("dp", "percentage change in price", "10", "%")],
          [step("e", "price elasticity of demand", "dq * dp")], "200"), "REJECT"),
    ("quant_fin_valid", "finance", Q["finance"]["question"], Q["finance"]["valid"],
     spec([inp("fv", "future value", "1100"), inp("r", "discount rate", "10", "%")],
          [step("pv", "present value", "fv / (1 + r)")], "1000"), "ACCEPT"),
    ("quant_fin_wrong_arith", "finance", Q["finance"]["question"], Q["finance"]["wrong_arith"],
     spec([inp("fv", "future value", "1100"), inp("r", "discount rate", "10", "%")],
          [step("pv", "present value", "fv / (1 + r)")], "1100"), "REJECT"),
    ("quant_fin_wrong_formula", "finance", Q["finance"]["question"], Q["finance"]["wrong_formula"],
     spec([inp("fv", "future value", "1100"), inp("r", "discount rate", "10", "%")],
          [step("pv", "present value", "fv * (1 + r)")], "1210"), "REJECT"),
    # A correct derived answer whose lexical support falls below the Stage 1 threshold because its numbers are
    # derived rather than quoted. Synthetic: it shows the mechanism, not how often real questions look like this.
    ("derived_numeric_heavy_valid", "statistics",
     "A sample has standard deviation 12 and size 36. What is the standard error of the mean?",
     "It is 2, because 12 divided by 6 gives 2 where 6 is the square root of 36.",
     spec([inp("s", "sample standard deviation", "12"), inp("n", "sample size", "36")],
          [step("se", "standard error of the mean", "s / sqrt(n)")], "2"), "ACCEPT"),
    ("derived_numeric_heavy_wrong", "statistics",
     "A sample has standard deviation 12 and size 36. What is the standard error of the mean?",
     "It is 3, because 12 divided by 4 gives 3 where 4 is the square root of 36.",
     spec([inp("s", "sample standard deviation", "12"), inp("n", "sample size", "36")],
          [step("se", "standard error of the mean", "s / sqrt(n)")], "3"), "REJECT"),
]
