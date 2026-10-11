# Live-model pilot proposal (for owner approval -- NOT approved, NOT run)

Nothing in this document has been executed. No API key was used, no network call was made, no money was spent.

## Question the pilot answers
Does the production tutoring path, driven by a real model, produce explanations, diagnoses, feedback and follow-up
questions that a human reviewer rates acceptable on the frozen rubrics (`rubrics.py`)? The offline run cannot answer this.

## Scope: 8 of the 26 frozen tasks (2 per capability), at least one per subject
| Capability | Tasks |
|---|---|
| Conceptual teaching | CT-FIN1, CT-MGT2 |
| Misconception diagnosis | MD-ECO1, MD-FIN2 |
| Case-study application | CS-ACC1, CS-MGT1 |
| Assessment preparation | AP-MKT2, AP-ACC2 |

Subjects covered: Finance, Management, Economics, Accounting, Marketing. The same frozen packs, references and scripted
student responses (`tasks.py`) are used. No real students, no real student data, no copyrighted material.

Per task: one TEACH_ME session (explanation), then every scripted student response through `submit_response`
(about 3 each), then one `next_question` after the first response. About 40-45 tutor calls in total.

## What is measured
1. **Deterministic layer, live model**: the same probes as the offline run, but the model supplies the replies: leak rate,
   citation validity, rejected-reply rate (`rejected_replies`, fallback frequency), question-validator acceptance rate.
   Reported as counts out of N, with the model, prompt versions (`tutor-turn-v2`, `tutor-question-v3`) and date.
2. **Diagnosis agreement**: model diagnosis vs the frozen expected diagnosis per response kind; false accusations
   (any misconception claim on a correct/hedged-correct answer) reported separately.
3. **Rubric scores (0-3)**: given by one human reviewer on all 8 tasks. A model judge may add a second score only after
   being compared with the human on these same 8 tasks. Hard-fail rules in `rubrics.py` apply.
4. **Not claimed**: learning gains, retention, comparison with a human tutor, generalisation beyond these 8 tasks.
   n = 8 supports finding gross failures, not estimating quality.

## Token measurement
The provider already exposes per-call `last_usage`; `tutoring._add_usage` accumulates it in `session["usage"]`. The pilot
runner records input/output (and cached/reasoning, if the provider reports them) tokens per call, per task and in total,
plus call counts and the model id. If usage is not returned for a call, that call is listed as unmeasured instead of estimated.

## Permissions needed from the owner
- Use of `OPENAI_API_KEY` (the only implemented provider) from the owner's environment, for this pilot only.
- Sending the synthetic pack excerpts, scripted student responses and tutor prompts to the provider. These are original
  synthetic text; nothing personal or institutional is sent.
- Choice of model (owner to name it) and confirmation of the current price per token.
- Permission to write pilot outputs (including raw model replies) under `evals/business_tutoring_v1/results/live_pilot_<date>/`.
- A named human reviewer for the rubric scoring (the owner or a delegate).

## Proposed spending cap
- **Hard cap: 600,000 tokens total (input + output) and US$5, whichever is reached first.** The runner stops, writes what it
  has, and marks the rest NOT RUN.
- Rough planning figure: about 45 tutor calls at roughly 4k input and 0.5k output tokens, about 200k tokens, i.e. a
  cap of about three times the expectation. The estimate is unverified; the first 5 calls will be measured, and the run
  halts for owner review if their average implies the cap would be exceeded.
- No retries beyond the existing production limits (`MAX_REJECTED_REPLIES`, `MAX_MODEL_CALLS`). No second run without approval.
- An optional model-judge pass is excluded from this cap and needs separate approval.

## Stop conditions
Any attempted network call outside the provider; any real personal data detected in a prompt; cap reached; more than 3
consecutive provider errors.

## Deliverable
`results/live_pilot_<date>/` with raw replies, per-call token counts, deterministic tallies, the reviewer's rubric sheet, and
a one-page summary stating N, the model, the date and what the sample cannot show.

## Spending controls (revised; supersedes the earlier "first-5-call projection" idea, which was not a hard cap)
Implemented in `pilot_budget.py`, used by `pilot_runner.py`; nothing live has run.
- **Reserve before send.** Each request's worst-case cost is written (fsynced) to an append-only ledger and must fit inside BOTH the
  token cap and the dollar cap, or the request is refused and the pilot halts. Worst case = byte-bounded input (a token spans at
  least one byte; an assumption about the tokenizer, not measured) + a fixed 1,000-token overhead + the explicit
  `max_output_tokens` sent with the request (`OpenAIReasoningProvider.max_output_tokens`, the one production change; it also bounds
  reasoning tokens), priced at the owner-attested input and output rates times an owner-stated surcharge multiplier (>= 1).
  Cached-input discounts are ignored, which only over-reserves.
- **Settle after.** Measured provider usage replaces the reservation. Missing or malformed usage, usage above the reservation, an error
  with no usage, or a KeyboardInterrupt charges the worst case and halts. Retries are separate reservations.
- **No reset.** The ledger is replayed on start: unsettled (interrupted) reservations count at worst case, a halt persists, a ledger
  from another approval id is refused, and a new approval file cannot raise the caps recorded when the ledger was opened. Approval
  files can only lower the hard ceilings (600,000 tokens, US$5, 4,000 output tokens, 80 calls).
- **Pricing is attested, not fetched.** The runner has no network and cannot verify prices. The approval file must carry model-specific
  input/output rates, a source, who verified them, a verification date within 30 days, and a surcharge multiplier. No tools or
  web-search are used in these requests, so no tool fees apply.
- **Limit.** The ledger is a local file; anyone with file access can delete it. Set a provider-side spend limit on the API key/project
  as the independent backstop.
- Dry run (default): `results/pilot_dry_run/` (synthetic rates and token counts, not real usage). `--live` also needs
  `SERAPIS_PILOT_LIVE=1` and an owner-written approval file (`approved: true`, `approval_id`, `model`, `reviewer`,
  `max_output_tokens`, optional lower `token_cap`/`usd_cap`, and the `pricing` object).
- Reporting always lists the known limitations, including per-task retrieval gaps (pages the candidate good questions need but root
  retrieval does not supply; currently AP-MKT2 page 2).
- The pilot uses the V1.1 correction of AP-ACC2 (`corrections/v1_1.py`); V1.0 files, labels and results are unchanged.
