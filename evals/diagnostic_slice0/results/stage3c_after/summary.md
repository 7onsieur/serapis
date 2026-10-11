# Diagnostic Slice 0 -- generated summary

Baseline: {"git_head": "a06b3d5", "git_dirty_tracked_files": ["M evals/diagnostic_slice0/README.md", " M evals/diagnostic_slice0/run_eval.py", " M src/university_jarvis/hub_service.py", " M src/university_jarvis/tutor_policy.py", " M src/university_jarvis/tutoring.py", " M tests/test_learning_evidence.py"], "python": "3.14.6", "source_sha256": {"hub_service.py": "17e668c167627349", "reasoning.py": "725cc758a2bdd458", "retrieval.py": "73ad5cc78cf8cc39", "tutor_policy.py": "5c16a17c1360fe87", "tutoring.py": "fb9948964f9b43ae"}}

## Outcomes by category

- root_reference: TRUE_ACCEPT=10, TRUE_REJECT=40
- citation: FALSE_ACCEPT=11, FALSE_REJECT=1, TRUE_ACCEPT=4, TRUE_REJECT=19
- quantitative: FALSE_REJECT=3, TRUE_REJECT=6
- leakage: MISSED_LEAK=5, TRUE_BLOCK=17, TRUE_PASS=15
- hedge: FAIL=13, PASS=20

## Production-path outcomes (citation and quantitative: create_session -> next_question; leakage: _check_reply is already the production path)

- citation [production]: FALSE_REJECT=1, TRUE_ACCEPT=4, TRUE_REJECT=30
- quantitative [production]: FALSE_REJECT=3, TRUE_REJECT=6

## Validator with the uncited supplied pages passed in (citation and quantitative)

- citation [validator+pages]: FALSE_ACCEPT=4, FALSE_REJECT=1, TRUE_ACCEPT=4, TRUE_REJECT=26
- quantitative [validator+pages]: FALSE_REJECT=3, TRUE_REJECT=6

## Validator-direct outcomes (leakage: reveals_reference called directly)

- leakage [validator]: MISSED_LEAK=5, TRUE_BLOCK=17, TRUE_PASS=15

## Production-path rejections by layer (RETRIEVAL = cited page never supplied; VALIDATION = a validator rejected it)

- citation FALSE_REJECT rejected_by=VALIDATION: 1
- citation TRUE_REJECT rejected_by=RETRIEVAL: 14
- citation TRUE_REJECT rejected_by=VALIDATION: 16
- quantitative FALSE_REJECT rejected_by=VALIDATION: 3
- quantitative TRUE_REJECT rejected_by=VALIDATION: 6

## Production-path failures

- CITE-mar-valid FALSE_REJECT Generated question rejected: question gives away its own answer
- QUANT-eco-valid FALSE_REJECT Generated question rejected: a computed answer needs a verified calculation: it states -2, which nei
- QUANT-sta-valid FALSE_REJECT Generated question rejected: a computed answer needs a verified calculation: it states 5, which nei
- QUANT-fin-valid FALSE_REJECT Generated question rejected: a computed answer needs a verified calculation: it states 1.1, which ne

## Outcomes by subtype

- citation/contradicted_claim: FALSE_ACCEPT=1, TRUE_REJECT=4
- citation/decoy_concept_answer: FALSE_ACCEPT=5
- citation/decoy_page: FALSE_ACCEPT=2, TRUE_REJECT=3
- citation/extra_decoy_page_cited: TRUE_REJECT=5
- citation/irrelevant_page: TRUE_REJECT=5
- citation/unsupported_claim: FALSE_ACCEPT=3, TRUE_REJECT=2
- citation/valid: FALSE_REJECT=1, TRUE_ACCEPT=4
- hedge/confident_control: PASS=5
- hedge/hedge_phrase_as_content: FAIL=3
- hedge/i_believe_correct: FAIL=5
- hedge/i_think_correct: PASS=5
- hedge/idk: PASS=5
- hedge/perhaps_mid_correct: PASS=5
- hedge/unsure_what_asked: FAIL=5
- leakage/clean_hint: TRUE_PASS=5
- leakage/paraphrase: MISSED_LEAK=5
- leakage/short_clean: TRUE_PASS=5
- leakage/short_leak: TRUE_BLOCK=5
- leakage/short_numeric_paraphrase: TRUE_BLOCK=2
- leakage/student_partial_plus_leak: TRUE_BLOCK=5
- leakage/student_quote_full: TRUE_PASS=5
- leakage/verbatim: TRUE_BLOCK=5
- quantitative/valid: FALSE_REJECT=3
- quantitative/wrong_arith: TRUE_REJECT=3
- quantitative/wrong_formula: TRUE_REJECT=3
- root_reference/contradicted: TRUE_REJECT=5
- root_reference/generated_contradicted: TRUE_REJECT=5
- root_reference/generated_supported: TRUE_ACCEPT=5
- root_reference/generated_unsupported: TRUE_REJECT=5
- root_reference/generated_wrong_page: TRUE_REJECT=5
- root_reference/missing_citation: TRUE_REJECT=5
- root_reference/supported: TRUE_ACCEPT=5
- root_reference/unsupported: TRUE_REJECT=5
- root_reference/wrong_page_decoy: TRUE_REJECT=5
- root_reference/wrong_page_irrelevant: TRUE_REJECT=5

## Failed cases (33)

- CITE-mar-valid [MEDIUM] FALSE_REJECT gold="ACCEPT" observed="REJECT" question gives away its own answer
- CITE-mar-decoy_concept_answer [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-eco-unsupported_claim [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-eco-decoy_concept_answer [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-sta-decoy_page [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-sta-decoy_concept_answer [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-fin-decoy_page [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-fin-unsupported_claim [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-fin-decoy_concept_answer [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-psy-unsupported_claim [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-psy-contradicted_claim [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- CITE-psy-decoy_concept_answer [HIGH] FALSE_ACCEPT gold="REJECT" observed="ACCEPT"
- QUANT-eco-valid [MEDIUM] FALSE_REJECT gold="ACCEPT" observed="REJECT" a computed answer needs a verified calculation: it states -2, which neither the question nor the cited passages state
- QUANT-sta-valid [MEDIUM] FALSE_REJECT gold="ACCEPT" observed="REJECT" a computed answer needs a verified calculation: it states 5, which neither the question nor the cited passages state
- QUANT-fin-valid [MEDIUM] FALSE_REJECT gold="ACCEPT" observed="REJECT" a computed answer needs a verified calculation: it states 1.1, which neither the question nor the cited passages state
- LEAK-mar-paraphrase [HIGH] MISSED_LEAK gold="LEAK" observed="PASSED"
- LEAK-eco-paraphrase [HIGH] MISSED_LEAK gold="LEAK" observed="PASSED"
- LEAK-sta-paraphrase [HIGH] MISSED_LEAK gold="LEAK" observed="PASSED"
- LEAK-fin-paraphrase [HIGH] MISSED_LEAK gold="LEAK" observed="PASSED"
- LEAK-psy-paraphrase [HIGH] MISSED_LEAK gold="LEAK" observed="PASSED"
- HEDGE-mar-i_believe_correct [LOW] FAIL gold={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc observed={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre failed checks: hedged
- HEDGE-mar-unsure_what_asked [MEDIUM] FAIL gold={"hedged": true, "non_answer": true, "model_judged": false, "diagnosis_preserved": "unclea observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "unclea failed checks: non_answer, model_judged
- HEDGE-eco-i_believe_correct [LOW] FAIL gold={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc observed={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre failed checks: hedged
- HEDGE-eco-unsure_what_asked [MEDIUM] FAIL gold={"hedged": true, "non_answer": true, "model_judged": false, "diagnosis_preserved": "unclea observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "unclea failed checks: non_answer, model_judged
- HEDGE-sta-i_believe_correct [LOW] FAIL gold={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc observed={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre failed checks: hedged
- HEDGE-sta-unsure_what_asked [MEDIUM] FAIL gold={"hedged": true, "non_answer": true, "model_judged": false, "diagnosis_preserved": "unclea observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "unclea failed checks: non_answer, model_judged
- HEDGE-sta-hedge_phrase_as_content [MEDIUM] FAIL gold={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc failed checks: hedged, progression
- HEDGE-fin-i_believe_correct [LOW] FAIL gold={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc observed={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre failed checks: hedged
- HEDGE-fin-unsure_what_asked [MEDIUM] FAIL gold={"hedged": true, "non_answer": true, "model_judged": false, "diagnosis_preserved": "unclea observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "unclea failed checks: non_answer, model_judged
- HEDGE-fin-hedge_phrase_as_content [MEDIUM] FAIL gold={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc failed checks: hedged, progression
- HEDGE-psy-i_believe_correct [LOW] FAIL gold={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc observed={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre failed checks: hedged
- HEDGE-psy-unsure_what_asked [MEDIUM] FAIL gold={"hedged": true, "non_answer": true, "model_judged": false, "diagnosis_preserved": "unclea observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "unclea failed checks: non_answer, model_judged
- HEDGE-psy-hedge_phrase_as_content [MEDIUM] FAIL gold={"hedged": false, "non_answer": false, "model_judged": true, "diagnosis_preserved": "corre observed={"hedged": true, "non_answer": false, "model_judged": true, "diagnosis_preserved": "correc failed checks: hedged, progression
