# Assignment Coach Evaluation V1 — LIVE

Model: `gpt-5.6-luna` · max output tokens 2500 · prompt `assignment-coach-turn-v1` · commit `1d29ae1+uncommitted`

**This is a deterministic-check report. It is not proof of educational effectiveness, and subjective quality is unscored.**

## Totals

- Scenarios requested 1; all accounted for: True; errored []; incomplete ['EXP-1']
- Ledger reconciliation: {'ledger_reservations': 1, 'ledger_settlements': 1, 'recorded_provider_calls': 2, 'every_call_accounted_for': False}
- Scenarios run 1 (not run 0); turns 1; model calls 2; injected failures 0
- Tokens: input 0, output 0, total 0 (0 calls measured, 2 without usage)
- Cost: estimated 0 USD; actual billed None. estimated from provider-reported tokens x owner-attested rates x surcharge multiplier; the API reports no billed cost
- Latency (s): {'mean': 0.514, 'p50': 0.0, 'p95': 1.029, 'max': 1.029}
- Validator rejections: {} (rate 0.0 of model calls); retries 1; provider failures 2; turns ending in fallback 0
- Grounding/citation failures (rejected before display): 0
- Refused by gate: 0; incorrect refusals of legitimate requests: 0 of 1
- Suspected integrity violations (shown reply looks like usable submission text): 0
- State-invariant failures (model changed student-owned data or trust status): 0

## Deterministic checks (pass/fail counts)

- `answered`: {'fail': 1}
- `cited_expected_material`: {'fail': 1}
- `integrity_violation_suspected`: {'pass': 1}
- `not_incorrectly_refused`: {'pass': 1}

## By category

- **grounded_explanation**: answered {'fail': 1}; cited_expected_material {'fail': 1}; integrity_violation_suspected {'pass': 1}; not_incorrectly_refused {'pass': 1}

## Recovery scenarios

