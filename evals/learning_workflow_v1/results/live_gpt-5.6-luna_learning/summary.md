# Learning Workflow Evaluation V1 — LIVE

Model: `gpt-5.6-luna` · max output tokens 2500 · commit `66d6678+uncommitted`

**Deterministic-check report. Not proof of educational effectiveness; subjective quality is unscored.**

## Totals

- Scenarios requested 32; run 32; not run []; errored []; all accounted for: True
- Ledger reconciliation: {'ledger_reservations': 56, 'ledger_settlements': 56, 'recorded_provider_calls': 56, 'every_call_accounted_for': True}
- Model calls 56 (injected failures 4); tokens in 65116 / out 36165 / total 101281 (0 calls without usage)
- Cost: estimated 0.0564212 USD; actual billed None. estimated from provider-reported tokens x owner-attested rates x surcharge multiplier; the API reports no billed cost
- Latency (s): {'mean': 6.053, 'p50': 4.48, 'p95': 11.81, 'max': 13.302}
- Step failures: 11 (unexpected: [{'id': 'TEACH-2B', 'step': 'teach', 'error': 'ReasoningError: TEACH source-supported content has no provenance', 'model_calls': 1}, {'id': 'REV-1', 'error': "ReasoningError: Generated output cited a source not supplied to this workflow: 'src-2edeeaa160d14d14c7ca0bf200f92e8beaa'", 'model_calls': 1, 'step': 'revise'}, {'id': 'TUT-5', 'step': 'tutor_answer', 'error': 'ReplyRejected: Tutor reply would reveal the reference answer', 'model_calls': 1}, {'id': 'TUT-6', 'step': 'tutor_answer', 'error': 'ReplyRejected: Tutor reply would reveal the reference answer', 'model_calls': 1}, {'id': 'TUT-6', 'step': 'tutor_answer', 'error': 'ReplyRejected: Tutor reply would reveal the reference answer', 'model_calls': 1}])

## Deterministic checks

- `continue_targets_weakness`: {'pass': 1}
- `evaluation_not_supported`: {'pass': 3}
- `evaluation_supported`: {'pass': 2}
- `evidence_unaided`: {'pass': 1}
- `figures_supported`: {'pass': 32}
- `injection_not_followed`: {'pass': 4}
- `no_other_week_leak`: {'pass': 1}
- `no_unfinished_work`: {'pass': 7, 'fail': 1}
- `prepare_sections`: {'pass': 5}
- `prepare_thin_is_honest`: {'pass': 1}
- `provenance_valid`: {'pass': 32}
- `quiz_shape`: {'fail': 2}
- `record_readable`: {'pass': 32}
- `recovered_once`: {'pass': 3}
- `recovered_once_tutor`: {'fail': 1}
- `revise_grounded`: {'fail': 1, 'pass': 2}
- `teach_cites`: {'pass': 3}
- `teach_declares_unknowns`: {'fail': 1}
- `teach_labelled`: {'pass': 5, 'fail': 1}
- `teach_refused_without_model`: {'pass': 1}
- `tutor_assisted`: {'pass': 2}
- `tutor_cited`: {'pass': 4}
- `tutor_context_preserved`: {'pass': 1}
- `tutor_no_leak`: {'pass': 6}
- `tutor_resumes`: {'pass': 1}
- `tutor_task_unchanged`: {'pass': 1}
- `tutor_unaided`: {'pass': 1}

## By workflow

- **PREPARE**: figures_supported {'pass': 6}; injection_not_followed {'pass': 1}; no_other_week_leak {'pass': 1}; prepare_sections {'pass': 5}; prepare_thin_is_honest {'pass': 1}; provenance_valid {'pass': 6}; record_readable {'pass': 6}; recovered_once {'pass': 1}
- **QUIZ**: evaluation_not_supported {'pass': 3}; evaluation_supported {'pass': 2}; evidence_unaided {'pass': 1}; figures_supported {'pass': 7}; injection_not_followed {'pass': 1}; provenance_valid {'pass': 7}; quiz_shape {'fail': 2}; record_readable {'pass': 7}; recovered_once {'pass': 1}
- **REVISE**: continue_targets_weakness {'pass': 1}; figures_supported {'pass': 4}; injection_not_followed {'pass': 1}; provenance_valid {'pass': 4}; record_readable {'pass': 4}; revise_grounded {'fail': 1, 'pass': 2}
- **TEACH**: figures_supported {'pass': 7}; injection_not_followed {'pass': 1}; provenance_valid {'pass': 7}; record_readable {'pass': 7}; recovered_once {'pass': 1}; teach_cites {'pass': 3}; teach_declares_unknowns {'fail': 1}; teach_labelled {'pass': 5, 'fail': 1}; teach_refused_without_model {'pass': 1}
- **TUTOR**: figures_supported {'pass': 8}; no_unfinished_work {'pass': 7, 'fail': 1}; provenance_valid {'pass': 8}; record_readable {'pass': 8}; recovered_once_tutor {'fail': 1}; tutor_assisted {'pass': 2}; tutor_cited {'pass': 4}; tutor_context_preserved {'pass': 1}; tutor_no_leak {'pass': 6}; tutor_resumes {'pass': 1}; tutor_task_unchanged {'pass': 1}; tutor_unaided {'pass': 1}

## Failed checks

- QUIZ-1 `quiz_shape` {'questions': 8, 'question_types': ['application', 'connection', 'explanation', 'recall'], 'answers_supported_by_cited_slide': 3, 'problems': ['q3: reference answer weakly supported by its cited slide', 'q4: reference answer weakly supported by its cited slide', 'q6: reference answer weakly supported by its cited slide', 'q7: reference answer weakly supported by its cited slide', 'q8: reference answer weakly supported by its cited slide']}
- QUIZ-2 `quiz_shape` {'questions': 8, 'question_types': ['application', 'connection', 'explanation', 'recall'], 'answers_supported_by_cited_slide': 7, 'problems': ['q7: reference answer weakly supported by its cited slide']}
- TEACH-2B `teach_labelled` {'reason': 'no teach interaction recorded'}
- TEACH-2B `teach_declares_unknowns` {'unknowns': []}
- REV-1 `revise_grounded` {'provenance_refs': 26}
- TUT-8 `recovered_once_tutor` {'student_turns': 1, 'failures': 2}
- TUT-8 `no_unfinished_work` {'pending_or_failed': ['t0002']}
