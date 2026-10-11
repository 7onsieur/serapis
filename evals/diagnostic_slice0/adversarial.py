"""Stage 1 adversarial cases. Kept apart from the frozen 164-case corpus; the frozen gold labels are untouched.

Gold labels were written from the text and the intended pedagogy before any validator ran on them.
KNOWN_MISS marks a case that is a real leak the deterministic check is NOT expected to catch; it is listed so the
limitation is measured and visible, not so it counts as a pass.
"""

from __future__ import annotations

import corpus as C

STA = C.SUBJECTS["statistics"]
ECO = C.SUBJECTS["economics"]
FIN = C.SUBJECTS["finance"]
PSY = C.SUBJECTS["psychology"]

# (case id, reference, task, message, student text, gold)   gold: LEAK | CLEAN | KNOWN_MISS
LEAK = [
    ("neg_digits_word", "-2", ECO["short"]["task"], "It works out to negative two.", "my answer", "LEAK"),
    ("neg_minus_digit", "-2", ECO["short"]["task"], "The result is minus 2.", "my answer", "LEAK"),
    ("neg_unicode_minus", "-2", ECO["short"]["task"], "The result is −2 here.", "my answer", "LEAK"),
    ("neg_sign_only_hint", "-2", ECO["short"]["task"],
     "Demand curves slope downward, so check the sign of your result.", "my answer", "CLEAN"),
    ("neg_positive_two_is_not_negative_two", "-2", ECO["short"]["task"],
     "Divide the two percentage changes and then think about the sign.", "my answer", "CLEAN"),
    ("student_said_it", "-2", ECO["short"]["task"], "You wrote -2; compare that with the cited page.", "-2", "CLEAN"),
    ("thousands_separator", "1000", FIN["short"]["task"], "It comes to 1,000.", "my answer", "LEAK"),
    ("number_words", "1000", FIN["short"]["task"], "It comes to one thousand.", "my answer", "LEAK"),
    ("trailing_zeros", "1000", FIN["short"]["task"], "It comes to 1000.00 in total.", "my answer", "LEAK"),
    ("compound_number_words", "25", "How many participants took part?", "There were twenty five.", "my answer", "LEAK"),
    ("decimal_spelling", "0.5", "What is the value?", "It is 0.50.", "my answer", "LEAK"),
    ("page_locator", "2", STA["short"]["task"], "See page 2 and divide by the square root of the sample size.",
     "my answer", "CLEAN"),
    ("step_locator", "2", STA["short"]["task"], "Work through step 2 of the example, then check your arithmetic.",
     "my answer", "CLEAN"),
    ("table_locator", "2", STA["short"]["task"], "Table 2 on the cited page shows the setup.", "my answer", "CLEAN"),
    ("value_in_task_not_a_leak", "25", STA["short"]["task"].replace("size 25", "size 25"),
     "Remember the sample size here is 25, so take its square root first.", "my answer", "CLEAN"),
    ("name_whole_word", "mitochondria", "Which organelle releases usable energy?", "The organelle is the mitochondria.",
     "my answer", "LEAK"),
    ("name_not_a_substring", "nucleus", "Which structure holds the DNA?", "Think about the nuclear envelope.",
     "my answer", "CLEAN"),
    ("name_said_by_student", "nucleus", "Which structure holds the DNA?", "You said nucleus; check the source for it.",
     "the nucleus", "CLEAN"),
    ("two_word_name", "random assignment", PSY["short"]["task"], "The procedure is random assignment.", "my answer",
     "LEAK"),
    ("two_word_name_other_words", "random assignment", PSY["short"]["task"],
     "Think about random sampling and how it differs from what you are asked.", "my answer", "CLEAN"),
    ("generic_short_reference", "true", "Is the statement true or false?", "That is true to the source's wording.",
     "my answer", "CLEAN"),
    ("reordered_reword", STA["root_ref"], STA["root_task"],
     "How much sample means vary is described by the standard deviation of the sample, calculated by dividing by "
     "the root of the sample size, a square root.", "my answer", "LEAK"),
    ("discussing_the_topic_only", STA["root_ref"], STA["root_task"],
     "Re-read the paragraph about how sample means vary, then compare your formula with the cited page.",
     "my answer", "CLEAN"),
    ("paraphrase_other_vocabulary", STA["root_ref"], STA["root_task"], STA["paraphrase"], "my answer", "KNOWN_MISS"),
    ("number_as_fraction_word", "0.5", "What is the value?", "It is one half.", "my answer", "KNOWN_MISS"),
    ("percent_vs_decimal", "0.5", "What is the value?", "It is 50%.", "my answer", "KNOWN_MISS"),
]

CITE = lambda sid, *pages: [{"source_id": sid, "pdf_page": p} for p in pages]  # noqa: E731

# (case id, subject, question, expected answer, citations, gold)   gold: ACCEPT | REJECT
GENERATED = [
    ("valid_single_page_decoy_shares_vocabulary", "statistics",
     "How does a larger sample size change the standard error of the sample mean?",
     "A larger sample therefore gives a smaller standard error.", CITE(STA["source_id"], 1), "ACCEPT"),
    ("valid_page_two_topic_page_one_shares_words", "economics",
     "How is income elasticity of demand calculated and what sign does it have for a normal good?",
     "It is the percentage change in quantity demanded divided by the percentage change in income, and a normal "
     "good has a positive value.", CITE(ECO["source_id"], 2), "ACCEPT"),
    ("valid_two_pages_both_needed", "finance",
     "How do present value and future value relate through the discount or interest rate?",
     "Present value equals the future value divided by one plus the discount rate, and future value equals the "
     "present value multiplied by one plus the interest rate.", CITE(FIN["source_id"], 1, 2), "ACCEPT"),
    ("different_concept_answer", "psychology",
     "What does random assignment allow an experiment to conclude?",
     "Random sampling supports generalising findings from the sample to the population.",
     CITE(PSY["source_id"], 2), "REJECT"),
    ("legit_page_plus_irrelevant_third", "finance",
     "How do present value and future value relate through the discount or interest rate?",
     "Present value equals the future value divided by one plus the discount rate, and future value equals the "
     "present value multiplied by one plus the interest rate.", CITE(FIN["source_id"], 1, 2, 3), "REJECT"),
    ("decoy_page_repeats_vocabulary_only", "statistics",
     "How does the size of a sample change the standard error?",
     "A larger sample therefore gives a smaller standard error.", CITE(STA["source_id"], 1, 2), "REJECT"),
]
