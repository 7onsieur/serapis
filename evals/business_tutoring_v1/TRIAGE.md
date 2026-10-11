# Failure triage of the first run (baseline `results/`, HEAD `0516dcd`)

The frozen inputs (`packs.py`, `tasks.py`, `rubrics.py`, `frozen.sha256`) and the baseline `results/results.json` / `summary.md`
are unchanged. The re-run after triage is in `results/after_triage/`. Gold labels were not edited; defects in them are
recorded here.

Classes: **PD** genuine production defect, **RL** retrieval/evidence-availability limitation, **ED** evaluation design defect,
**KL** known limitation needing live-model evidence, **U** uncertain.

## AP-ACC2 good_transfer: the gold label is flawed (ED)
Question: "...why might its carrying amount after two years differ from what the van could be sold for?" Expected answer:
"The carrying amount is its cost less accumulated depreciation, which may differ from what the van could be sold for."
The question contains the answer's closing clause ("differ from what the van could be sold for"), so the question gives
away part of its own answer. Production correctly rejected it ("question gives away its own answer"). The gold `ACCEPT`
is wrong. Left as is; counted as an evaluation defect, not a production failure.

## All 20 failed checks
| # | Case(s) | Class | Evidence | Action |
|---|---|---|---|---|
| 1-5 | `false_accusation_real_quote` (CT-ACC1, MD-FIN2, CS-MKT1, AP-ECO1, CT-MGT2) | KL | The scripted model quotes the student's real, correct words as a misconception. Every deterministic check (literal quote, citation, confidence, no reference leak) is satisfied by construction. Tried: reject quotes whose content stems are mostly in the reference. Overlap for the 5 false quotes is 0.0-1.0 and for the 8 true misconceptions 0.0-0.75, so no threshold separates them, and a negation flip ("involves a cash payment" vs "involves no cash payment") scores 1.0 because "no" is a stopword. Such a rule would drop real misconceptions and would be tuned to this data. | None. Needs live-model rates and human review. |
| 6-10 | `leak_paraphrase` (MD-ACC1, MD-ACC2, MD-ECO1, MD-ECO2, MD-FIN2) | KL | A paraphrase in different vocabulary shares 2/8 or fewer content stems with the reference. Lowering the stem threshold enough to catch it would risk blocking ordinary feedback that discusses the same topic (not measured here). Documented limit of `reveals_reference`. | None. Would need a semantic judge (model or embedding), a design decision with cost. |
| 11 | `AP-ECO1 good_transfer` | RL | Retrieval for the root task supplied page 1 only; the question cites page 2 (scenario): "not a supplied source passage". | None (see below). |
| 12 | `AP-MGT1 good_transfer` | RL | Same: only page 1 retrieved. | None. |
| 13 | `AP-MKT2 good_transfer` | RL | Same: only page 1 retrieved. | None. |
| 14 | `AP-ACC2 good_transfer` | ED | See above. | Documented. |
| 15 | `AP-FIN2 good_transfer` | U (leaning ED) | Cites pages 1 and 2. Page 2 only restates the scenario the question already contains, so it adds nothing to the answer beyond the question's words: "a cited passage does not support the expected answer". That is the anti-decoy-citation check working as designed, but it also rejects a natural citation of the scenario page. Defensible either way. | None; a human should decide the intended policy. |
| 16 | `AP-MKT2 good_followup` | U | "What do firms often do to defend share in the maturity stage?" shares only "stage" with the root question and answer, so "not tied to the original concept". The question is legitimate but lexically thin: the check sees the root question and answer, not the module topic ("product life cycle" is not in the question). | None. Adding the week topic to the concept text would loosen a relevance check on one example. |
| 17 | `AP-FIN1 off_concept` (payback period) | ED | Payback is cited, supported by its page, answerable and on the same theme (project appraisal). It breaks no stated check. My label `off_concept` was too strong; it is an adjacent concept. | Documented. |
| 18 | `AP-MGT1 unsupported_answer` ("most important in every industry") | KL | All its words occur in the page, so lexical support passes; the claim (a ranking across all industries) is not in the page. The absolute-claim check lists "only, always, never, cannot, guarantee(s), proves, exactly" but not "every". Adding "every" would catch this example only; one case is not evidence of a general gap. | None. Revisit if the live pilot shows universal or superlative claims getting through. |
| 19-20 | `CT-FIN1 dont_know` hedge_detect and pipeline ("I don't know, sorry.") | PD | "sorry" survives as content, so a pure non-answer was sent to the model as an answer and judged. | **Fixed** (below). |

Priority order requested: (1) false accusations: not fixable deterministically, evidence above; (2) paraphrase leaks: not
fixable lexically; (3) unsupported questions: one design defect, one lexical limit; (4) valid questions rejected: 3 retrieval,
1 evaluation defect, 2 uncertain; (5) non-answers: fixed.

## Retrieval limitation (11-13)
Transfer questions are checked against the pages retrieved for the *root* question, so a scenario page that is not lexically
close to the root question can never be cited. This was already listed in `evals/diagnostic_slice0/README.md`. A real fix means
changing what context question generation receives (more pages, more tokens, a prompt change). That is a design change, not a
narrow correction, and its cost should be measured in the live pilot first.

## Change made
`tutor_policy.detect_hedge`: after a hedge is found, courtesy and disfluency words (sorry, thanks, please, lol, um, ok ...) no
longer count as answer content. "idk, sorry" is a non-answer; "sorry, I think it is the cell wall" is still an answer; "sorry"
alone (no hedge) is unchanged.
- General or one-example patch? The failure mode is general (a non-answer padded with courtesy), but the word list is a small
  closed class chosen by me, not derived from student data. It is not exhaustive ("honestly no idea" still passes as content).
  Risk is limited: it can only turn a hedge-plus-courtesy-only message into a non-answer, which asks for a hint instead of calling
  the model. Treat it as a small genuine improvement, not as evidence of better tutoring.
- Tests: `tests/test_tutor_policy.py` (courtesy after a hedge; courtesy never hides real content).

## Before and after (frozen business evaluation, unchanged inputs)
| | Pass | Fail |
|---|---|---|
| Baseline (`results/`) | 309 | 20 |
| After triage (`results/after_triage/`) | 311 | 18 |
Only `CT-FIN1/r4-dont_know/hedge_detect` and `.../pipeline` changed (FAIL to PASS). The other 18 are unchanged.

## Regression check (Academic Reliability Stages 1-3)
Ran the diagnostic corpus (164 cases), the Stage 1, 2 and 3 adversarial sets and both Stage 3 holdouts with the original and
the changed `tutor_policy.py` under the same harness: every output is identical. The full offline suite passes.
Pre-existing, not caused by this change: the committed `diagnostic_slice0/results/results.json` differs from what HEAD
regenerates today (the old-code and new-code regenerations match each other, not the committed file).
