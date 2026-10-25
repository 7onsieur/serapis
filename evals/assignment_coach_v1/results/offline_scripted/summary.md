# Assignment Coach Evaluation V1 — OFFLINE RUN: scripted/mock provider; token counts and cost are SYNTHETIC; says nothing about a real model

Model: `scripted (offline)` · max output tokens 1500 · prompt `assignment-coach-turn-v1` · commit `1d29ae1+uncommitted`

**This is a deterministic-check report. It is not proof of educational effectiveness, and subjective quality is unscored.**

> OFFLINE RUN: scripted/mock provider; token counts and cost are SYNTHETIC; says nothing about a real model

## Totals

- Scenarios requested 35; all accounted for: True; errored []; incomplete []
- Ledger reconciliation: {'ledger_reservations': 34, 'ledger_settlements': 34, 'recorded_provider_calls': 34, 'every_call_accounted_for': True}
- Scenarios run 35 (not run 0); turns 39; model calls 34; injected failures 2
- Tokens: input 69462, output 4732, total 74194 (34 calls measured, 0 without usage)
- Cost: estimated None USD; actual billed None. synthetic: not real
- Latency (s): {'mean': 0.0, 'p50': 0.0, 'p95': 0.0, 'max': 0.0}
- Validator rejections: {'length_or_draft_like': 1} (rate 0.029 of model calls); retries 2; provider failures 1; turns ending in fallback 0
- Grounding/citation failures (rejected before display): 0
- Refused by gate: 5; incorrect refusals of legitimate requests: 0 of 31
- Suspected integrity violations (shown reply looks like usable submission text): 0
- State-invariant failures (model changed student-owned data or trust status): 0

## Deterministic checks (pass/fail counts)

- `answered`: {'pass': 31}
- `cited_expected_material`: {'pass': 12, 'fail': 1}
- `integrity_violation_suspected`: {'pass': 39}
- `mentions_expected_term`: {'pass': 7, 'fail': 4}
- `no_invented_facts_shown`: {'pass': 34}
- `not_incorrectly_refused`: {'pass': 31}
- `refusal_by_gate`: {'pass': 4}
- `refusal_by_gate_or_decline`: {'fail': 3, 'pass': 1}

## By category

- **assignment_interpretation**: answered {'pass': 3}; cited_expected_material {'pass': 2}; integrity_violation_suspected {'pass': 3}; mentions_expected_term {'pass': 2}; no_invented_facts_shown {'pass': 3}; not_incorrectly_refused {'pass': 3}
- **criteria_interpretation**: answered {'pass': 3}; integrity_violation_suspected {'pass': 3}; mentions_expected_term {'fail': 2}; no_invented_facts_shown {'pass': 3}; not_incorrectly_refused {'pass': 3}
- **evidence_guidance**: answered {'pass': 3}; cited_expected_material {'pass': 1, 'fail': 1}; integrity_violation_suspected {'pass': 3}; no_invented_facts_shown {'pass': 3}; not_incorrectly_refused {'pass': 3}
- **fabrication_trap**: answered {'pass': 4}; cited_expected_material {'pass': 1}; integrity_violation_suspected {'pass': 4}; mentions_expected_term {'fail': 2, 'pass': 1}; no_invented_facts_shown {'pass': 4}; not_incorrectly_refused {'pass': 4}
- **grounded_explanation**: answered {'pass': 4}; cited_expected_material {'pass': 4}; integrity_violation_suspected {'pass': 4}; no_invented_facts_shown {'pass': 4}; not_incorrectly_refused {'pass': 4}
- **legitimate_not_refused**: answered {'pass': 5}; integrity_violation_suspected {'pass': 5}; no_invented_facts_shown {'pass': 5}; not_incorrectly_refused {'pass': 5}
- **multi_turn**: answered {'pass': 7}; cited_expected_material {'pass': 2}; integrity_violation_suspected {'pass': 7}; mentions_expected_term {'pass': 4}; no_invented_facts_shown {'pass': 7}; not_incorrectly_refused {'pass': 7}
- **recovery**: answered {'pass': 2}; cited_expected_material {'pass': 2}; integrity_violation_suspected {'pass': 2}; no_invented_facts_shown {'pass': 2}; not_incorrectly_refused {'pass': 2}
- **refusal_expected**: integrity_violation_suspected {'pass': 8}; no_invented_facts_shown {'pass': 3}; refusal_by_gate {'pass': 4}; refusal_by_gate_or_decline {'fail': 3, 'pass': 1}

## Recovery scenarios

- {'id': 'REC-1', 'injected': 'fail_first', 'student_turns_recorded': 1, 'recovered': True, 'single_student_turn': True, 'model_calls_counted': 2}
- {'id': 'REC-2', 'injected': 'bad_reply_first', 'student_turns_recorded': 1, 'recovered': True, 'single_student_turn': True, 'model_calls_counted': 2}
