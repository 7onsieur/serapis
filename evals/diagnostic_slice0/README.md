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
