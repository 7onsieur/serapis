# Business Tutoring Evaluation V1 (offline foundation)

Run: `python3 evals/business_tutoring_v1/run_eval.py` (no network, no model, no real data; about 1 s). Add `--out <dir>` to write elsewhere.

**This run uses scripted providers. Success here does not establish that Serapis teaches effectively.** It shows that
the production safeguards and routing behave as intended when a model returns a known reply. Teaching quality is
**NOT YET EVALUATED**; the rubrics exist, no scores do.

## Layout
- `packs.py` -- 10 original synthetic source packs (2 per subject: Accounting, Finance, Economics, Marketing, Management), 3 pages each:
  concept, business scenario, related-but-different decoy. No copyrighted material; fictional firms.
- `tasks.py` -- 26 frozen tasks: reference answer, reference explanation, common misconceptions, 74 scripted student responses
  (correct, correct-but-hedged, partial, misconceived, off-topic, "don't know"), 36 scripted generated questions
  (good follow-up, good transfer, off-concept, unsupported answer, reworded, answer-leaking), and the expected outcome for each kind.
- `rubrics.py` -- 0-3 rubrics with anchors and hard-fail rules for the four capabilities. All **NOT YET EVALUATED**.
- `run_eval.py` -- runner. Imports production `tutoring`, `tutor_policy` and `retrieval`; never modifies them. Retrieval is the real BM25 code over the pack text; only file extraction is replaced. Blocks sockets.
- `results/` -- `results.json`, `summary.md`, `frozen.sha256` (hash of packs, tasks and rubrics taken before the first run).
- `LIVE_PILOT_PROPOSAL.md` -- proposed 8-task live pilot for owner approval (not run).
- Test: `tests/test_business_tutoring_eval.py`.

## What each production behaviour test covers
| Probe | Production path | Tells us |
|---|---|---|
| hedge_detect | `tutor_policy.detect_hedge` | hedged / "don't know" detection |
| pipeline | `create_session` -> `submit_response` | stored diagnosis, hedge flags, next action, planned next step, model-not-called for non-answers, grounded misconception kept. The diagnosis is the scripted gold fed back in: this tests routing, not diagnostic skill |
| legit_feedback_shown | `_check_reply` | no unnecessary refusal of feedback that quotes the student or gives non-leaking guidance |
| leak_verbatim / leak_paraphrase (+ explanation) | `reveals_reference` | answer-leak blocking in feedback and TEACH_ME explanations |
| false_accusation_fabricated_quote / real_quote | `validate_misconception` | a misconception claim must quote the student; a real quote on a correct answer is not caught |
| citation_to_unsupplied_page | `_check_reply` | citations must be supplied pages (not that the claim is true of the page) |
| teach_me_opens | TEACH_ME `create_session` | a well-supported task opens and explains |
| question_* | `create_session -> submit_response -> next_question -> validate_question` | generated follow-ups: accepted when answerable and new, rejected when off-concept, unsupported, reworded or answer-leaking |
| adaptive_request | `plan_next` -> NEXT_QUESTION request | the request to the model carries the step/reason/diagnosis implied by the student's last answer |

> After triage (`TRIAGE.md`): 311 pass / 18 fail in `results/after_triage/`; the baseline below is preserved in `results/`.

## Result of the first run (see `results/summary.md`)
309 of 329 checks pass, 20 fail. Failures are recorded, not tuned away; gold outcomes were not edited after the first run.

- **Answer leaks, 5:** paraphrases of the reference in different vocabulary pass the lexical leak check (documented limit).
- **False accusations, 5:** a model claim of a misconception that quotes the student's (correct) words verbatim is kept. Only a better model or a reviewer can catch it.
- **Good questions rejected, 6 of 12 good questions:** 3 are retrieval gaps (the cited page was not among the retrieved pages for the root task: ECO1, MGT1, MKT2 transfer), 1 is validator strictness on a two-page answer (FIN2), 1 is "not tied to the original concept" on a legitimate follow-up (MKT2), and 1 (ACC2) is probably my wording: the question repeats a phrase of its own answer, so "gives away its own answer" may be correct. That last one needs human review before it counts as a production fault.
- **Bad questions shown, 2:** a related-but-different concept (FIN1 payback) and an absolute unsupported claim phrased as a question (MGT1 "most important in every industry").
- **Hedge/non-answer, 1 (two checks):** "I don't know, sorry." is hedged but "sorry" survives as content, so it is sent to the model as an answer instead of treated as a non-answer.

Everything else passed: all verbatim leaks blocked (26 feedback, 26 explanation), no unnecessary refusal of 34 legitimate replies, all fabricated misconception quotes dropped, all citations to unsupplied pages rejected, 26/26 TEACH_ME sessions opened, 12/12 follow-up requests shaped by the student's last answer, reworded and answer-leaking questions all rejected.

## Not evaluated here (needs a live model and/or a human reviewer)
Explanation accuracy and level; whether feedback helps; whether a real model diagnoses real student answers; whether partial answers get the missing reasoning steps named (frozen in each partial response's `missing_steps`); whether case-study feedback evaluates reasoning and avoids invented business claims; question difficulty and exam-likeness; whether a generated follow-up targets the student's gap. 110 rubric judgements (26 tasks x their capability's dimensions) are pending.

## Limits
Scripted providers; one author wrote packs, gold and probes; 26 tasks, 74 responses; lexical validators only; pack text is short and clean; no real student language; single run configuration; some "good question" gold labels are untested judgement calls (see ACC2 above). Reproducibility: two consecutive runs produce byte-identical `results.json`.

## Freeze note
`packs.py`, `tasks.py` and `rubrics.py` were hashed (`results/frozen.sha256`) before the first run. Their content has not changed since. Reference answers were checked against the production reference gate (`tp.reference_unsupported`) before freezing; all 26 passed.
