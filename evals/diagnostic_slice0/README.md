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

## Stage 3 (independent mathematical verification)

Frozen artefacts are unchanged: `corpus.py`, the 164 cases, all earlier `results/` folders. `results/stage3_before/` is this harness on `a06b3d5`
(before any Stage 3 code); `results/stage3_after/` is the same harness with Stage 3. Every category, subtype and production-path tally is identical
(`quantitative` production: 3 false accepts before and after). The frozen QUANT cases carry free text only, so the verifier has nothing to check in them.
That is the design: a question without a `calculation` behaves exactly as before.

Measured separately, not in the frozen set (`adversarial_stage3.py`, `run_adversarial_stage3.py`, `summarise_stage3.py`; results in
`results/stage3_adversarial_{before,after}.json` and `results/stage3_summary.md`):

- `python3 evals/diagnostic_slice0/run_adversarial_stage3.py after` and `... before --before`, then `python3 evals/diagnostic_slice0/summarise_stage3.py`.
- GENERATED rows (12): the frozen QUANT texts given a structured `calculation`, plus two numeric-heavy cases; real production path.
- ENGINE rows (about 100): the verifier called directly. Their "before" is the Stage 1/2 reference gate applied to the expected answer, a stand-in,
  because the old system had no way to receive a formula. Treat the engine "before" numbers as indicative only.

What the numbers do and do not show: the gold labels were written by the author of the verifier and the verifier was adjusted while the cases were
run (a few gold labels were also corrected). There is no held-out set, so "0 false rejects" describes this synthetic set, not real tutoring.
The cases named `KNOWN_LIMIT` are reported as the false accepts they are.

### Supported mathematics

`+ - * / ^` (integer powers up to 16, and `^0.5`), `sqrt()`, parentheses, unary minus, decimals, `%` literals; named inputs and up to five
steps, each step's formula checked against the cited passage. Units: mm cm m km, s min h hr day, mg g kg and percent are converted exactly;
any other unit name is an opaque label that must match exactly (a mismatch is INCONCLUSIVE, not rejected). Rounding is half-up and must be stated
unless the result is exact.

### Not supported (returns INCONCLUSIVE or REJECTED; never accepted)

Temperature scales, logarithms, exponentials, trigonometry, factorials, sums or products over data, statistics tables or tests, symbolic algebra,
equation solving, calculus, geometry that needs a figure, currency conversion, fractional powers other than 0.5, formulas stated in the passage only
as symbols (`PV = FV/(1+r)`) or with more than one multiplication or division in a clause, and any passage wording the Stage 2 relation patterns
cannot parse. Questions whose answer is a number but carry no `calculation` are not verified at all (see the limitations below).

### Limitations that remain

- A calculation is only checked when the model supplies one. A numeric answer with no specification is judged as before, lexically.
- Verification shows a stated computation is internally correct and grounded in the cited text. It does not show the question asks for the right
  computation, or that the right quantities were chosen when the question offers several.
- Inputs are matched to the question or passage by value, plus a check that the number does not sit directly after a different input's name.
  A number written before its name, or inputs that share a value, are not caught if swapped.
- The direction of change ("falls by 20%") is only read through a short list of decrease words; the verifier cannot tell that a sign the text
  implies was dropped when the number matches (`negative_direction_ignored`).
- The formula check inherits the limits of `relations.py`: an operand it cannot match is INCONCLUSIVE, so some correct calculations are not verified.
- Real-model behaviour is unmeasured: how often a model produces a well-formed, groundable specification is unknown.

### Stage 3 safety review and independent holdout

`holdout_stage3.py` (73 cases, expected outcomes ACCEPT or BLOCK written from the mathematics before any verifier change) and
`run_holdout_stage3.py` run every case through the full `validate_question` gate. Frozen-implementation hashes:
`results/holdout_stage3/frozen_implementation.sha256`. Results:

- `frozen.json`: the implementation as first reported. 11 false accepts, 8 false rejects, 18 true accepts, 36 true blocks. This is the only
  uncontaminated measurement.
- `iteration_*.json`: the same set after each fix round, kept so the sequence is visible.
- `final.json`: current code. 1 false accept (`i_relabelled_inputs`), 3 false rejects, 23 true accepts, 46 true blocks. The fixes were written
  after seeing the frozen failures, so this is a regression result, not an independent one; a fresh set is needed to confirm it.
- Of the 3 final false rejects, 2 are `non_computational` cases that the older Stage 1 lexical rules refuse (`question gives away its own answer`,
  support below threshold) and 1 is a valid calculation (`v_rounding_tie_half_up`) refused by the same lexical support rule. None comes from the
  Stage 3 checks. They are reported, not edited away.

`results/stage3_adversarial_revised.json` is the earlier adversarial set re-run on the current code (originals untouched); only the two former known
false accepts changed, both to INCONCLUSIVE. `results/stage3b_after/` is the frozen 164 on the current code: it differs from `stage3_before/` only in the
`QUANT-*` rows, because a computed answer with no calculation is now refused (see below).

### Stage 3 closure review (second holdout, anchoring, what is not verified)

`holdout2_stage3.py` is a second, smaller set (50 business-school cases: margins, break-even, ROI, percentage change, elasticity, financial
ratios, omitted specifications, non-computational questions with numbers). Its expected outcomes were fixed before it was run, and
`results/holdout2_stage3/frozen_implementation.sha256` records the code it first ran against.

| run | false accepts | false rejects | true accepts | true blocks |
|---|---|---|---|---|
| `holdout2_stage3/frozen.json` (code before this round; independent) | 2 | 5 | 16 | 27 |
| `holdout2_stage3/final.json` (after this round's fixes; not independent) | 1 | 2 | 19 | 28 |
| `holdout_stage3/final_round3.json` (first holdout, current code) | 0 | 3 | 23 | 47 |

Changes this round: a number after "from" or "to" is a level, not a change; rate words ("per", "each", "unit", "percent") no longer name a quantity;
time-unit words are narration; numbers an answer may quote now come only from the formula, inputs, intermediate values, stated numbers and the
stated number of decimals (no free constants); and fewer than half of the question's inputs named in the question, or "from A to B" inputs listed in
the opposite order, is INCONCLUSIVE (`_check_anchoring`). `REQUIRE_NAMED_INPUTS` stays off. Cost of the anchoring rule across all three sets: one
correct adversarial case (`units_conversion_valid`, "A runner covers 1500 m ...") is now INCONCLUSIVE; no holdout case was lost.

The 164 frozen cases (`results/stage3c_after/`, current code) differ from `stage3_before/` only in the nine `QUANT-*` rows: the three valid free-text
answers (`QUANT-eco-valid`, `QUANT-sta-valid`, `QUANT-fin-valid`) are now blocked because a computed answer without a calculation is refused (false rejects
against the frozen labels); the three wrong-arithmetic answers (`QUANT-*-wrong_arith`) are now true rejects instead of false accepts; the three
wrong-formula rows were already rejected and still are. Quantitative production tally: before 3 true accepts / 3 false accepts / 3 true rejects;
after 3 false rejects / 6 true rejects. Every other category is identical.

### What Stage 3 does not verify

- **That the formula answers the student's question.** The final step's name must contain the quantity the question seems to ask for, and the formula
  must be one the cited passage states, but a passage can state a correct formula for a quantity other than the one the student needs (using the
  wrong ratio, an inappropriate measure, a different period), and the verifier cannot tell. It checks that a stated computation is right and
  grounded, not that it is the right computation.
- Which of several similar quantities the question means, when the passage names more than one that fit.
- Whether the question is well posed, its units realistic, or its numbers sensible.
- Inputs whose names are missing from the question: a relabelling that fits the passage is detected only when most inputs are unnamed
  (`w_relabelled_one_input` is accepted).
- Any computation with no calculation: a computed answer is refused, but a question that merely sounds non-numerical while hiding a computation
  (a result that coincides with a stated number and is not phrased as "calculate") is not detected.
- Anything outside the supported operations: statistics, tests, regression, symbolic algebra, calculus, tables, currency conversion, dates.
- Interpretation: conclusions drawn from the number ("so demand is elastic") are only checked as ordinary words against the passage.
- Real-model behaviour: how often a model writes a usable specification, or follows the sign and naming conventions, is unmeasured.

### Stage 3 status at commit

- **Frozen-benchmark regression (accepted by the owner).** Requiring a verified calculation for newly generated computational questions turns three
  valid free-text `QUANT` rows (`QUANT-eco-valid`, `QUANT-sta-valid`, `QUANT-fin-valid`) from true accepts into false rejects. They are the documented
  consequence of the rule, not a defect. Three wrong-arithmetic rows become true rejects. Frozen artefacts are untouched; see `results/stage3c_after/`.
- **Remaining known false accept.** An input relabelled to fit the passage is not detected when at least half of the question's inputs are named in the
  question (`holdout2_stage3` `w_relabelled_one_input`). No further heuristic is planned for Stage 3. The sign convention is provisional.
- **Unsupported mathematics.** Only the operations listed under "Supported mathematics" exist. Statistics, tests, regression, symbolic algebra, calculus,
  tables, currency, dates and temperature scales are not verified, and stage 3 does not check that the chosen formula is the one the student needs.
- **No real-model validation.** Everything here uses scripted providers and synthetic text. How often a real model produces a usable calculation
  specification, or follows the naming and sign conventions, has not been measured. The holdout sets were tuned against after their first run; only their
  `frozen.json` files are independent measurements.
- The `final.json` figures above are snapshots of the round they were written in; `final_round3.json` is the first holdout on the committed code
  (0 false accepts, 3 false rejects, all from older lexical rules).
