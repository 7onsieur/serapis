# Diagnostic Slice 0 (offline)

Reproducible, offline diagnostic of Serapis tutoring validators at baseline `c65b97e`.
Run: `python3 evals/diagnostic_slice0/run_eval.py` (needs the repo's normal dev install; no network, no model, no real data).

- `corpus.py` -- synthetic sources (5 subjects x 3 pages: concept / decoy / unrelated) and hand-written gold labels.
  Gold labels were written from the source text before any validator output was seen.
- `run_eval.py` -- runs the real `tutoring.create_session/submit_response`, `tutoring._check_reply`,
  `tutor_policy.validate_question/reveals_reference/detect_hedge` with scripted fake providers. Retrieval is the real
  BM25 code over the synthetic pages; only file extraction is replaced. Production code is never modified.
- `results/results.json` -- every case: gold, observed, outcome, severity, code path. `results/summary.md` -- tallies.

Limits: scripted providers (a "perfect" or fixed model), lexical-only checks measured, single concept per subject,
small n, no live-model behaviour, pages given to `validate_question` are all supplied (isolates the semantic layer).

## Known limitations (measured, not fixed)

Lexical validation screens text; it does not establish semantic correctness. The 164 cases and their gold labels are unchanged.
`results/baseline_c65b97e/` is the original pre-reference-safety baseline; `results/` is the current code.

- Root-reference: 2 swapped-relation / contradicted references (`ROOT-eco-contradicted`, `ROOT-eco-generated_contradicted`) are still falsely accepted; they reuse the passage's own words in a different relation.
- Derived numerical answers (a number computed from the page, not stated in it) can be rejected, and wrong arithmetic or formulas can be accepted (`QUANT-*`). Deliberately not loosened.
- TEACH_ME recovery rotates to another task only for unverified references. `SOURCE_CHANGED` and `NO_MATCH` still end with an error and can repeat on the same task.
- Remaining citation false accepts (decoy page, unsupported or contradicted claim), missed leaks (paraphrase, short leaks) and hedge-detection failures are listed per case in `results/summary.md`.
- Scripted providers only; no live-model behaviour is measured.

## Stage 1 (citation relevance, leakage, production path)

Frozen artefacts are unchanged: `corpus.py` gold labels, `results/results.json`, `results/summary.md`, `results/baseline_c65b97e/`.
New, additive:

- `run_eval.py --out <name>` writes `results/<name>/` (the default output location and layout are unchanged). Citation and quantitative cases now carry
  a `production` observation (real retrieval, `create_session -> skip -> next_question`, only the model scripted) and a
  `validator_with_uncited_pages` observation; leakage cases carry a `validator` observation (`reveals_reference` called directly).
  `observed`/`outcome` keep their original meaning, so the 164 cases stay comparable.
- `results/stage1_before/` = this harness on `60f5e30`; `results/stage1_after/` = this harness with the Stage 1 changes.
- `adversarial.py` + `run_adversarial.py` = 32 extra cases kept apart from the frozen 164 (`results/stage1_adversarial_{before,after}.json`).

What Stage 1 changed (`tutor_policy.py`): a generated question is rejected when an uncited supplied page matches the *question* clearly better
than the cited pages do, or when a cited page only repeats what the other cited pages support and matches the question clearly worse;
`reveals_reference` now tests references under 4 words (names as whole words; numbers by signed value across `-2`, `minus two`, `1,000`,
`one thousand`, ignoring places such as "page 2"), plus a close-reordering test (>= 85% of 8+ content stems).

Stage 1 results (164 frozen cases): production-path citation false accepts 5 -> 1; leakage missed 12 -> 5 (0 new false blocks, true passes 15 -> 15);
quantitative unchanged (3 production false accepts); no new false rejects or false blocks in any column.
Production-path rejections are tallied by layer: of the citation true rejects, 14 are retrieval gaps (the cited page was never supplied, unchanged by Stage 1)
and validators account for 11 before and 15 after. Only the validator count is evidence that a check recognised a bad question.

### Still not solved (measured, not fixed)

Lexical screening does not establish semantic correctness. Everything below remains open:
- A contradicted or swapped-relation claim that reuses the passage's vocabulary (2 root references; 1 production citation case, `CITE-sta-contradicted_claim`).
- Wrong arithmetic and derived numeric answers (`QUANT-*`); needs the later mathematical-verification stage.
- Paraphrased leaks in different vocabulary (5 frozen cases, plus the adversarial `paraphrase_other_vocabulary`), and numbers written as fractions or
  converted between percent and decimal (`one half`, `50%` vs `0.5`).
- A short numeric or name reference (ordinals such as "2nd" and places such as "page 2" excepted) is blocked wherever its value appears in a tutor message the student has not already seen, including an
  unrelated use of the same number or word (a false block, accepted as the safe direction).
- The relevance checks compare vocabulary only; an answer from the *right* page that addresses a different sentence is not detected.
- In production a question can cite only pages that retrieval supplied for the root task, so a legitimate multi-page question whose second page
  was not retrieved is rejected before these checks run (unchanged by Stage 1; `valid_two_pages_both_needed`).
- `CITE-mar-valid` is still a false reject ("question gives away its own answer"); Stage 1 did not touch it.
- Hedge failures (13) and `SOURCE_CHANGED`/`NO_MATCH` recovery are out of scope.

## Stage 2 (relationship and contradiction verification)

New module `src/university_jarvis/relations.py`, called from `tutor_policy.reference_unsupported` (every use of a stored or generated
reference: grading, reveal, hint, explain, follow-up generation) and from `tutor_policy.validate_question` (expected answer and question text).
It parses a closed set of explicit patterns from the text and from the cited passages and returns, per relation found, `SUPPORTED`,
`CONTRADICTED` or `UNDETERMINED`; only `CONTRADICTED` rejects. `UNDETERMINED` is never read as correct or incorrect.

Patterns: `A divided by B` (reversed operands), multiplication versus division and addition versus subtraction on the same operands
(multiplication and addition match in either operand order), `A is greater/less than B` / `exceeds` / `is above|below` (reversed), `a larger X gives a
smaller Y` (opposite direction), and a clause identical to the passage's once `not`/`cannot`/`never`/`no` is added or removed. Clauses with a
negator beside arithmetic or a comparison, mixed or chained operations, pronoun-only subjects, or scope words (`only`, `unless`, `except`, `but` ...)
are left undetermined.

- `results/stage2_before/`, `results/stage2_after/` = the 164 frozen cases on `8fa2382` and with Stage 2 (frozen artefacts above are untouched).
- `adversarial_stage2.py` + `run_adversarial_stage2.py` = 40 further cases (reversed operands, negation scope, comparisons, equivalent expressions,
  unsupported patterns; `results/stage2_adversarial_{before,after}.json`). Gold is REJECT, ACCEPT or INCONCLUSIVE (the layer must abstain).

Stage 2 results (164 frozen cases): root-reference false accepts 2 -> 0; production citation false accepts 1 -> 0 (`CITE-sta-contradicted_claim`); two more
contradicted-claim cases are now rejected by the validator (`CITE-eco`, `CITE-fin`, already rejected in production by retrieval); no outcome got worse.

Still not solved: relations phrased outside these patterns (`over`, `ratio of A to B`, symbols, prose such as "twice as large"), operands that differ in
wording by more than the stem match tolerates, a relation whose subject is a pronoun or only partly named (`CITE-psy-contradicted_claim`, `QUANT-*`
wrong arithmetic), and everything Stage 1 listed. These checks do not establish semantic correctness.
