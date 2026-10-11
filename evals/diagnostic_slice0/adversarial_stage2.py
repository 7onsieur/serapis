"""Stage 2 adversarial cases (relationships and contradictions). Kept apart from the frozen 164-case corpus.

Gold labels were written from the passage text before any validator ran on them.
  REJECT        the text clearly states a relation the passage contradicts.
  ACCEPT        the text states the passage's relation (or an equivalent one); rejecting it would be a false reject.
  INCONCLUSIVE  the pattern is unsupported or ambiguous; the relation layer must neither reject it nor claim support.
                (Some of these are really wrong or really right; the point is that the layer fails safe.)
"""

from __future__ import annotations

import corpus as C

STA, ECO, FIN, PSY = (C.SUBJECTS[k] for k in ("statistics", "economics", "finance", "psychology"))
P_PROFIT = ["Profit is revenue minus cost."]
P_AREA = ["Area equals length multiplied by width."]
P_COST = ["Total cost is fixed cost plus variable cost."]
P_ASSIGN = ["Random assignment makes the groups equivalent on average before the treatment."]
P_NOT = ["Random assignment does not make the groups equivalent on average before the treatment."]

# (case id, category, text, cited passages, gold)
CASES = [
    # reversed operands
    ("rev_ratio_price_over_quantity", "reversed_operands",
     "It is calculated as the percentage change in price divided by the percentage change in quantity demanded.",
     ECO["pages"][:1], "REJECT"),
    ("rev_ratio_root_over_sd", "reversed_operands",
     "Standard error is the square root of the sample size divided by the sample standard deviation.",
     STA["pages"][:1], "REJECT"),
    ("rev_ratio_one_plus_rate_over_fv", "reversed_operands",
     "Present value equals one plus the discount rate divided by the future value.", FIN["pages"][:1], "REJECT"),
    ("rev_ratio_correct_order", "reversed_operands",
     "It is calculated as the percentage change in quantity demanded divided by the percentage change in price.",
     ECO["pages"][:1], "ACCEPT"),
    ("rev_subtraction", "reversed_operands", "Profit is cost minus revenue.", P_PROFIT, "REJECT"),
    ("op_multiply_for_divide", "reversed_operands",
     "Standard error is the sample standard deviation multiplied by the square root of the sample size.",
     STA["pages"][:1], "REJECT"),
    ("op_times_for_divide", "reversed_operands",
     "Standard error is the sample standard deviation times the square root of the sample size.",
     STA["pages"][:1], "REJECT"),
    ("op_plus_for_minus", "reversed_operands", "Profit is revenue plus cost.", P_PROFIT, "REJECT"),
    ("op_subtraction_correct", "reversed_operands", "Profit equals revenue minus cost.", P_PROFIT, "ACCEPT"),
    # equivalent expressions
    ("equiv_commutative_multiply", "equivalent", "Area is width times length.", P_AREA, "ACCEPT"),
    ("equiv_commutative_add", "equivalent", "Total cost is variable cost plus fixed cost.", P_COST, "ACCEPT"),
    ("equiv_wording_and_article", "equivalent",
     "Elasticity is the percentage change in quantity demanded divided by the percentage change in the price.",
     ECO["pages"][:1], "ACCEPT"),
    ("equiv_direction_reworded", "equivalent", "A bigger sample yields a smaller standard error.",
     STA["pages"][:1], "ACCEPT"),
    ("equiv_direction_both_reversed", "equivalent", "A smaller sample gives a larger standard error.",
     STA["pages"][:1], "ACCEPT"),
    ("equiv_comparison_reversed_wording", "equivalent", "One is less than its absolute value.",
     ["Demand is elastic when its absolute value is greater than one."], "ACCEPT"),
    # comparisons and directions
    ("cmp_below_for_exceeds", "comparisons", "Demand is elastic when its absolute value is below one.",
     ECO["pages"][:1], "REJECT"),
    ("cmp_one_exceeds_value", "comparisons", "One exceeds its absolute value when demand is elastic.",
     ECO["pages"][:1], "REJECT"),
    ("cmp_same_direction", "comparisons", "Demand is elastic when its absolute value exceeds one.",
     ECO["pages"][:1], "ACCEPT"),
    ("dir_larger_gives_larger", "comparisons", "A larger sample gives a larger standard error.",
     STA["pages"][:1], "REJECT"),
    ("dir_higher_rate_higher_pv", "comparisons", "A higher discount rate gives a higher present value.",
     FIN["pages"][:1], "REJECT"),
    ("dir_correct", "comparisons", "A higher discount rate gives a lower present value.", FIN["pages"][:1], "ACCEPT"),
    ("dir_other_page_same_words_other_subject", "comparisons", "A larger spread gives a smaller standard deviation.",
     STA["pages"][:2], "INCONCLUSIVE"),
    # negation scope
    ("neg_added", "negation_scope", "Random assignment does not make the groups equivalent on average before the treatment.",
     P_ASSIGN, "REJECT"),
    ("neg_removed", "negation_scope", "Random assignment makes the groups equivalent on average before the treatment.",
     P_NOT, "REJECT"),
    ("neg_cannot_added", "negation_scope",
     "Random assignment cannot make the groups equivalent on average before the treatment.", P_ASSIGN, "REJECT"),
    ("neg_both_negated", "negation_scope",
     "Random assignment does not make the groups equivalent on average before the treatment.", P_NOT, "ACCEPT"),
    ("neg_other_subject", "negation_scope",
     "Random sampling does not make the groups equivalent on average before the treatment.", P_ASSIGN, "INCONCLUSIVE"),
    ("neg_not_only", "negation_scope",
     "Random assignment does not only make the groups equivalent on average before the treatment.", P_ASSIGN,
     "INCONCLUSIVE"),
    ("neg_pronoun_subject", "negation_scope", "It does not make the groups equivalent on average before the treatment.",
     P_ASSIGN, "INCONCLUSIVE"),
    ("neg_implicit_fail", "negation_scope",
     "Random assignment fails to make the groups equivalent on average before the treatment.", P_ASSIGN,
     "INCONCLUSIVE"),
    ("neg_in_comparison", "negation_scope", "Demand is elastic when its absolute value does not exceed one.",
     ECO["pages"][:1], "INCONCLUSIVE"),
    # unsupported patterns / different operands
    ("unsupported_ratio_to", "unsupported", "Elasticity is the ratio of the quantity change to the price change.",
     ECO["pages"][:1], "INCONCLUSIVE"),
    ("unsupported_over", "unsupported", "Standard error equals the standard deviation over the root of the sample size.",
     STA["pages"][:1], "INCONCLUSIVE"),
    ("unsupported_numeric_operands", "unsupported", "The standard error is 10 divided by 5, which is 2.",
     STA["pages"][:1], "INCONCLUSIVE"),
    ("unsupported_other_quantity", "unsupported",
     "It is the percentage change in quantity demanded divided by the percentage change in income.",
     ECO["pages"][:1], "INCONCLUSIVE"),
    ("unsupported_no_pattern", "unsupported", "Standard error describes how sample means vary between samples.",
     STA["pages"][:1], "INCONCLUSIVE"),
]

# Generated-question path (production next_question): (id, subject, question, expected answer, citations, gold)
CITE = lambda sid, *pages: [{"source_id": sid, "pdf_page": p} for p in pages]  # noqa: E731
GENERATED = [
    ("gen_direction_contradicted", "statistics", "How does the size of a sample change the standard error?",
     "A larger sample gives a larger standard error.", CITE(STA["source_id"], 1), "REJECT"),
    ("gen_direction_supported", "statistics", "How does the size of a sample change the standard error?",
     "A larger sample gives a smaller standard error.", CITE(STA["source_id"], 1), "ACCEPT"),
    ("gen_ratio_reversed", "economics", "How is price elasticity of demand calculated from percentage changes?",
     "It is the percentage change in price divided by the percentage change in quantity demanded.",
     CITE(ECO["source_id"], 1), "REJECT"),
    ("gen_question_false_premise", "statistics",
     "Since a larger sample gives a larger standard error, how is the standard error calculated from the deviation?",
     "It is the sample standard deviation divided by the square root of the sample size.",
     CITE(STA["source_id"], 1), "REJECT"),
]
