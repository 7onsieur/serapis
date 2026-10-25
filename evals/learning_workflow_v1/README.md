# Learning Workflow Evaluation V1

Drives PREPARE, QUIZ (with evidence), TEACH, REVISE and TUTOR through the same service functions the Hub calls, in a fresh fictional workspace per scenario (32 scenarios in `lw_scenarios.py`, frozen by `results/frozen.sha256`).

```sh
.venv/bin/python evals/learning_workflow_v1/run_eval.py --fresh                         # offline, scripted provider, synthetic usage, no network
SERAPIS_EVAL_LIVE=1 .venv/bin/python evals/learning_workflow_v1/run_eval.py --live --approval FILE --label NEW_LABEL   # REAL provider, owner approval only
```

Live runs need an owner approval file with attested pricing and caps (see `evals/assignment_coach_v1/approval.example.json`), a new label (each label has its own ledger), a configured key, and pass the free authenticated preflight. Spending control, network allowlist, resume (`--resume`) and credential scrubbing are shared with the Assignment Coach harness. Free `setup` steps use the scripted provider so only the step under test costs money. A call that hangs can only be stopped by killing the process; its reservation is then charged at worst case.

- `fixtures.py` fictional decks (week 1, week 2, a thin deck, a deck with a planted instruction).
- `lw_scoring.py` deterministic checks: provenance resolves, figures supported, planted instruction not repeated, quiz shape, evaluation outcome, labelled as generated, tutor leak check, resume, recovery.
- Subjective quality (accuracy, clarity, teaching quality, difficulty) is never scored automatically: `review_sheet.md` is blank for a human. AI-assisted reviews live in `reviews/` and are labelled as such.
- Offline results (`results/offline_scripted`) show the harness works and that the planted-instruction check is sensitive (the scripted provider copies slide text); they say nothing about a real model.
