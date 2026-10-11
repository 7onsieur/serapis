# Business Tutoring Evaluation V1 -- generated summary

**OFFLINE SCRIPTED-PROVIDER RUN -- tests production safeguards and behaviour, NOT teaching quality**

Frozen inputs unchanged since freeze: True
Production code fingerprint: `85eb741a5698d576`

## Coverage (26 tasks, 10 packs, 74 scripted responses, 36 scripted generated questions)

- Accounting: ASSESSMENT_PREPARATION=1, CASE_STUDY_APPLICATION=1, CONCEPTUAL_TEACHING=2, MISCONCEPTION_DIAGNOSIS=2
- Economics: ASSESSMENT_PREPARATION=1, CASE_STUDY_APPLICATION=1, CONCEPTUAL_TEACHING=1, MISCONCEPTION_DIAGNOSIS=2
- Finance: ASSESSMENT_PREPARATION=2, CASE_STUDY_APPLICATION=1, CONCEPTUAL_TEACHING=1, MISCONCEPTION_DIAGNOSIS=2
- Management: ASSESSMENT_PREPARATION=1, CASE_STUDY_APPLICATION=1, CONCEPTUAL_TEACHING=1, MISCONCEPTION_DIAGNOSIS=1
- Marketing: ASSESSMENT_PREPARATION=1, CASE_STUDY_APPLICATION=2, CONCEPTUAL_TEACHING=1, MISCONCEPTION_DIAGNOSIS=1

## Offline deterministic checks: 311 pass / 18 fail of 329 (10 of the failures are documented structural gaps)

- adaptive_request: PASS=12
- citation_to_unsupplied_page: PASS=6
- false_accusation_fabricated_quote: PASS=5
- false_accusation_real_quote: FAIL=5
- hedge_detect: PASS=74
- leak_paraphrase: FAIL=5
- leak_verbatim: PASS=26
- leak_verbatim_explanation: PASS=26
- legit_feedback_shown: PASS=34
- pipeline: PASS=74
- question_good_followup: FAIL=1, PASS=5
- question_good_transfer: FAIL=5, PASS=1
- question_leaky: PASS=6
- question_off_concept: FAIL=1, PASS=5
- question_reworded: PASS=6
- question_unsupported_answer: FAIL=1, PASS=5
- teach_me_opens: PASS=26

## Failures by class

- ANSWER_LEAK: 5
- BAD_QUESTION_SHOWN: 2
- FALSE_ACCUSATION: 5
- GOOD_QUESTION_REJECTED: 6

## Failed cases

- AP-ACC2/question-good_transfer [GOOD_QUESTION_REJECTED] expected="ACCEPT" observed="REJECT"
- AP-ECO1/false_accusation_real_quote [FALSE_ACCUSATION / known gap] expected="NOT_ACCUSED" observed="ACCUSED"
- AP-ECO1/question-good_transfer [GOOD_QUESTION_REJECTED] expected="ACCEPT" observed="REJECT"
- AP-FIN1/question-off_concept [BAD_QUESTION_SHOWN] expected="REJECT" observed="ACCEPT"
- AP-FIN2/question-good_transfer [GOOD_QUESTION_REJECTED] expected="ACCEPT" observed="REJECT"
- AP-MGT1/question-good_transfer [GOOD_QUESTION_REJECTED] expected="ACCEPT" observed="REJECT"
- AP-MGT1/question-unsupported_answer [BAD_QUESTION_SHOWN] expected="REJECT" observed="ACCEPT"
- AP-MKT2/question-good_followup [GOOD_QUESTION_REJECTED] expected="ACCEPT" observed="REJECT"
- AP-MKT2/question-good_transfer [GOOD_QUESTION_REJECTED] expected="ACCEPT" observed="REJECT"
- CS-MKT1/false_accusation_real_quote [FALSE_ACCUSATION / known gap] expected="NOT_ACCUSED" observed="ACCUSED"
- CT-ACC1/false_accusation_real_quote [FALSE_ACCUSATION / known gap] expected="NOT_ACCUSED" observed="ACCUSED"
- CT-MGT2/false_accusation_real_quote [FALSE_ACCUSATION / known gap] expected="NOT_ACCUSED" observed="ACCUSED"
- MD-ACC1/leak_paraphrase_feedback [ANSWER_LEAK / known gap] expected="BLOCKED" observed="LEAKED"
- MD-ACC2/leak_paraphrase_feedback [ANSWER_LEAK / known gap] expected="BLOCKED" observed="LEAKED"
- MD-ECO1/leak_paraphrase_feedback [ANSWER_LEAK / known gap] expected="BLOCKED" observed="LEAKED"
- MD-ECO2/leak_paraphrase_feedback [ANSWER_LEAK / known gap] expected="BLOCKED" observed="LEAKED"
- MD-FIN2/false_accusation_real_quote [FALSE_ACCUSATION / known gap] expected="NOT_ACCUSED" observed="ACCUSED"
- MD-FIN2/leak_paraphrase_feedback [ANSWER_LEAK / known gap] expected="BLOCKED" observed="LEAKED"

## NOT YET EVALUATED (needs a live model and/or human reviewer; no score is given or implied)

- ASSESSMENT_PREPARATION: NOT YET EVALUATED -- 6 tasks x 5 dimensions = 30 judgements pending (adaptive_followup, difficulty, feedback_by_outcome, novelty, relevance_answerability)
- CASE_STUDY_APPLICATION: NOT YET EVALUATED -- 6 tasks x 4 dimensions = 24 judgements pending (framework_application, missing_steps, no_unsupported_claims, reasoning_over_memory)
- CONCEPTUAL_TEACHING: NOT YET EVALUATED -- 6 tasks x 4 dimensions = 24 judgements pending (accuracy, feedback_usefulness, grounding, level)
- MISCONCEPTION_DIAGNOSIS: NOT YET EVALUATED -- 8 tasks x 4 dimensions = 32 judgements pending (corrective_guidance, diagnosis_accuracy, misconception_precision, no_false_accusation)
