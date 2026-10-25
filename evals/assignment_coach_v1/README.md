# Assignment Coach Evaluation V1

A repeatable harness that drives the **real** Assignment Coach pipeline (`assignment_coach.send_message`: request gate, retrieval over
fictional PowerPoint material, prompt and schema, provider, `check_reply` validators, persistence) over 35 frozen scenarios.

```sh
.venv/bin/python evals/assignment_coach_v1/run_eval.py                  # offline, scripted provider, synthetic usage, no network
.venv/bin/python evals/assignment_coach_v1/run_eval.py --mock compliant # harness self-check: a model that obeys everything
.venv/bin/python evals/assignment_coach_v1/run_eval.py --mock fabricating
SERAPIS_EVAL_LIVE=1 .venv/bin/python evals/assignment_coach_v1/run_eval.py --live --approval FILE   # REAL provider, owner approval only
```

**Offline results say nothing about a real model.** They show the harness, scoring, reporting and spending controls work, and that the
scoring catches bad models (see `results/offline_compliant`, `results/offline_fabricating`). Token and cost figures offline are synthetic and labelled so.

## Live-run safeguards
`--live` needs `SERAPIS_EVAL_LIVE=1`, an approval file, a configured key, and passes a **free** authenticated preflight (`GET /v1/models`) before anything is reserved. Network is limited to `api.openai.com`.
Progress is saved after every scenario (`progress.jsonl`); an interrupted run is continued with `--resume` and never repeats completed scenarios (a live results folder is never cleared; use a new `--label` for a new run, but remember each label has its own ledger, so lower `usd_cap`/`token_cap` by what earlier ledgers charged). Every scenario ends complete, errored or not-run and is listed; the summary reconciles ledger reservations, settlements and recorded calls, and credentials are scrubbed from everything written.
Offline folders can be rebuilt with `--fresh`. Model and price verification: `PRICING_VERIFIED_2026-10-25.md`.

## Layout
- `materials.py` — fictional BUS101 decks (the same ones as `serapis demo`), one assessment with details and one without.
- `scenarios.py` — 35 scenarios in 9 categories: grounded explanation (4), assignment interpretation (3), marking criteria (3), evidence guidance (3),
  refusal expected (8), legitimate requests that must not be refused (5), fabrication traps (4), multi-turn retention (3 scenarios, 7 turns),
  recovery (2: an injected provider failure and an injected unusable reply, both followed by a retry on the real provider). Frozen before any run (`results/frozen.sha256`).
- `scoring.py` — **deterministic** checks only: refusal by the gate, incorrect refusal of a legitimate request, answered/not fallen back, cited the expected
  material, expected term present (honesty and retention probes), suspected usable submission text (heuristic), student-owned state and trust statuses unchanged.
- `run_eval.py` — runner, per-call recording, aggregation, review sheet. Spending controls come from `evals/business_tutoring_v1/pilot_budget.py` (write-ahead
  reservation against token and dollar caps, settle with provider-reported usage, halt on anything unmeasured, ledger never reset).
- `approval.example.json` — template an owner must complete (model, caps, attested pricing). Not usable as shipped.
- `results/<run>/` — `config.json` (model, prompt version, commit, caps), `scenarios.json` (per-scenario checks), `turns.jsonl` (one record per call: latency,
  input/output tokens, estimated cost, retrieved passages, raw reply, rejection reason), `summary.json|md` (aggregates), `review_sheet.md` (blank rubric), `ledger.jsonl`.

## What is deterministic and what is not
Deterministic: the checks above and the production validators' accept/reject decisions. **Subjective** (helpfulness, accuracy to the material, coaching rather than
telling, tone) is never scored automatically; the review sheet has blank 0-3 fields and a hard-fail box for a human. Automated scores are not evidence of educational effectiveness.

## Cost reporting
Tokens are provider-reported per call. Cost is *estimated* from those tokens × the owner-attested rates × a surcharge multiplier; the API does not report billed
cost, so `actual_billed_cost_usd` is always `null`. Calls without usage are counted as unmeasured and halt a live run. Nothing is invented.

## Limits
One author wrote the scenarios; one fictional module; short clean slides; English only; each scenario run once (no variance estimate); the real model's non-determinism
is not averaged out; keyword checks for honesty and retention are crude and can pass or fail for the wrong reason, which is why transcripts are kept.
