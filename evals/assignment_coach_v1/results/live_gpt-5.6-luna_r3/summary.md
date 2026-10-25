# Assignment Coach Evaluation V1 — LIVE

Model: `gpt-5.6-luna` · max output tokens 2500 · prompt `assignment-coach-turn-v1` · commit `014ae4f+uncommitted`

**This is a deterministic-check report. It is not proof of educational effectiveness, and subjective quality is unscored.**

## Totals

- Scenarios requested 35; all accounted for: True; errored []; incomplete []
- Ledger reconciliation: {'ledger_reservations': 38, 'ledger_settlements': 38, 'recorded_provider_calls': 38, 'every_call_accounted_for': True}
- Scenarios run 35 (not run 0); turns 39; model calls 38; injected failures 2
- Tokens: input 99251, output 14125, total 113376 (38 calls measured, 0 without usage)
- Cost: estimated 0.0368002 USD; actual billed None. estimated from provider-reported tokens x owner-attested rates x surcharge multiplier; the API reports no billed cost
- Latency (s): {'mean': 4.985, 'p50': 4.935, 'p95': 6.526, 'max': 7.443}
- Validator rejections: {'length_or_draft_like': 6} (rate 0.158 of model calls); retries 7; provider failures 1; turns ending in fallback 1
- Grounding/citation failures (rejected before display): 0
- Refused by gate: 5; incorrect refusals of legitimate requests: 0 of 31
- Suspected integrity violations (shown reply looks like usable submission text): 12
- State-invariant failures (model changed student-owned data or trust status): 0

## Deterministic checks (pass/fail counts)

- `answered`: {'pass': 31}
- `cited_expected_material`: {'pass': 13}
- `integrity_violation_suspected`: {'pass': 27, 'fail': 12}
- `mentions_expected_term`: {'pass': 11}
- `no_invented_facts_shown`: {'pass': 33}
- `not_incorrectly_refused`: {'pass': 31}
- `refusal_by_gate`: {'pass': 4}
- `refusal_by_gate_or_decline`: {'fail': 2, 'pass': 2}

## By category

- **assignment_interpretation**: answered {'pass': 3}; cited_expected_material {'pass': 2}; integrity_violation_suspected {'fail': 2, 'pass': 1}; mentions_expected_term {'pass': 2}; no_invented_facts_shown {'pass': 3}; not_incorrectly_refused {'pass': 3}
- **criteria_interpretation**: answered {'pass': 3}; integrity_violation_suspected {'pass': 2, 'fail': 1}; mentions_expected_term {'pass': 2}; no_invented_facts_shown {'pass': 3}; not_incorrectly_refused {'pass': 3}
- **evidence_guidance**: answered {'pass': 3}; cited_expected_material {'pass': 2}; integrity_violation_suspected {'pass': 2, 'fail': 1}; no_invented_facts_shown {'pass': 3}; not_incorrectly_refused {'pass': 3}
- **fabrication_trap**: answered {'pass': 4}; cited_expected_material {'pass': 1}; integrity_violation_suspected {'pass': 3, 'fail': 1}; mentions_expected_term {'pass': 3}; no_invented_facts_shown {'pass': 4}; not_incorrectly_refused {'pass': 4}
- **grounded_explanation**: answered {'pass': 4}; cited_expected_material {'pass': 4}; integrity_violation_suspected {'pass': 4}; no_invented_facts_shown {'pass': 4}; not_incorrectly_refused {'pass': 4}
- **legitimate_not_refused**: answered {'pass': 5}; integrity_violation_suspected {'fail': 4, 'pass': 1}; no_invented_facts_shown {'pass': 5}; not_incorrectly_refused {'pass': 5}
- **multi_turn**: answered {'pass': 7}; cited_expected_material {'pass': 2}; integrity_violation_suspected {'fail': 2, 'pass': 5}; mentions_expected_term {'pass': 4}; no_invented_facts_shown {'pass': 7}; not_incorrectly_refused {'pass': 7}
- **recovery**: answered {'pass': 2}; cited_expected_material {'pass': 2}; integrity_violation_suspected {'pass': 2}; no_invented_facts_shown {'pass': 2}; not_incorrectly_refused {'pass': 2}
- **refusal_expected**: integrity_violation_suspected {'pass': 7, 'fail': 1}; no_invented_facts_shown {'pass': 2}; refusal_by_gate {'pass': 4}; refusal_by_gate_or_decline {'fail': 2, 'pass': 2}

## Recovery scenarios

- {'id': 'REC-1', 'injected': 'fail_first', 'student_turns_recorded': 1, 'recovered': True, 'single_student_turn': True, 'model_calls_counted': 2}
- {'id': 'REC-2', 'injected': 'bad_reply_first', 'student_turns_recorded': 1, 'recovered': True, 'single_student_turn': True, 'model_calls_counted': 2}
