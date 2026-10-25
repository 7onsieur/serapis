# Checkpoint — independent verification and hardening (2026-10-25)

Durable record of the review sprint that followed the first Assignment Coach / student-journey delivery. Committed locally as one checkpoint (not pushed).

## Environment

macOS 14.8 arm64, Python 3.14.6; pytest 8.4.2, fastapi 0.143.0, starlette 1.7.0, httpx 0.28.1, jinja2 3.1.6, uvicorn 0.54.0, openai 2.54.0 (installed, never called), playwright 1.64.1 (package only, no browser launched), google-api-python-client 2.201.0. Extras installed: `.[ai,blackboard,drive,test]` plus `pyflakes` for linting. No network calls, API keys, university data or spending.

## Final-tree results

`.venv/bin/python -m pytest -q` (repository root): **834 passed, 0 failed, 0 skipped** (stable over three consecutive runs; the concurrency tests did not flake). History: 767 before the first sprint, 794 after it, 834 now (+40 this sprint). Targeted: `test_assignment_coach.py`, `test_coach_hardening.py`, `test_pilot_acceptance.py` together: 67 passed. Running pytest from another directory fails at collection on pre-existing tests (they import `tests.*`); not changed.

## Review findings and fixes

| # | Finding (confirmed by probe or test) | Fix | Regression test |
|---|---|---|---|
| 1 | Request gate bypassed by "Not sure, write my essay", "tips on: write my essay" (negation/how-to windows too wide), zero-width and look-alike characters, a line break, spaced letters, "sample/model introduction", "turn notes into paragraphs", "continue my essay", "thesis statement for me", "draft it", "do it all for me", a few non-English verbs | New `coach_integrity.py`: Unicode/spacing normalisation, anchored negation and how-to framing, self-authorship exemption, new patterns | `RequestGateRegressionTests` (27 bypasses refused, 20 legitimate allowed) |
| 2 | Reply check accepted a fabricated year with a known author, a quotation not in the material, and invented deadline/weighting/word limit/marks | Verbatim-quote check, author+year check, figure check against recorded facts and excerpts, "here is a sample…"/"try something like:" detection, stricter length limits, scan of follow-ups | `ReplyCheckRegressionTests`, `ModelCannotEstablishFactsTests` |
| 3 | Session's material list went stale: newly added files not shown, "no readable material" gap persisted, evidence could not cite them | Read-only refresh in the view, refresh on send, `save_evidence(state=…)` | `test_materials_added_after_the_session_started…` |
| 4 | Provider failure with no AI key left the student stuck on an unfinished message | `discard_unfinished` + Discard button; unfinished text shown | `test_discard_unfinished…`, `test_missing_ai_setup…` |
| 5 | Turn/call limit was a dead end; message pointed to a non-existent "export" | "Start a fresh session" carries criteria, plan, sections, evidence, questions (ids remapped) | `test_force_new_carries_over…` |
| 6 | `start_session(force_new)` rewrote the old session without its lock (could lose a late reply); reopen raced with start; request id reusable across assignments | Per-session lock under the index lock, re-read before ending; reopen under index lock; request-id/assignment check | `test_parallel_starts…`, `test_request_id_reused…` |
| 7 | Delete during an in-flight message; stray lock files after delete | Refused while fresh PENDING; lock/tmp cleaned | `test_message_in_flight…`, `test_delete_removes…` |
| 8 | Hand-edited/damaged session files raised KeyError inside pages | Structural validation in `_read`; clear "could not be opened" page | `test_damaged_or_tampered…`, `test_damaged_session_shows…` |
| 9 | Unexpected provider/file exceptions became 500s | Wrapped as a recoverable `CoachSessionError` after marking the turn failed | `test_unexpected_provider_failure…` |
| 10 | Non-UTF-8 form bytes → 500; unbounded non-upload bodies and chunked posts | `errors="replace"`; 1 MiB cap, chunked rejected (411/413) in middleware | `test_malformed_form_values…`, `test_cross_site_and_oversized…` |
| 11 | First-time student saw the fictional sample with no obvious way to start; journey below the hero | "Start my own workspace" (`POST /workspace/start`); journey moved to the top of Home; docs updated | `test_first_run_on_the_fictional_sample…`, `InterruptedJourneyTests` |
| 12 | Home could 500 on a damaged week record | Journey errors caught broadly; Home always renders | covered by journey/Home tests |
| 13 | Coach re-extracted every material on every message (slow PDF extraction) | Small in-process cache keyed by path, size, mtime | `ExtractionCacheTests` |
| 14 | PPTX `a:br` line breaks fused words | Treated as spaces | existing PPTX tests |
| 15 | Direct service calls to evaluate/continue still assumed state was loaded | Fallback to saved state in `hub_service` | `test_pilot_acceptance` |
| 16 | Accessibility gaps on the coach page (error not announced, radio group without legend, low-contrast small text) | `role="alert"`, fieldset/legend, higher-contrast small text | visual and markup inspection only |
| 17 | 1,056-line `assignment_coach.py` | Split into `coach_integrity.py` (312), `coach_store.py` (238), `coach_notes.py` (218), `coach_analysis.py` (88); `assignment_coach.py` (512) re-exports the public API; no behaviour change (tests identical) | whole suite |

Earlier-sprint defects already fixed and still covered: Evaluate/Continue crash with lazy Hub state, "Prepare with AI" needing the CLI, PPTX paragraph fusion, setup errors shown as 404.

## Verified end to end (synthetic, scripted provider)

First-time setup → profile → module → assessment → .pptx import (and an unreadable PDF) → Prepare, Quiz, answer, evaluation, Teach, Revise, Tutor → Assignment Coach planning and coaching → interruption and recovery (provider failure mid-message, retry exactly once) → application restart and resumption → failure recovery (provider down on Prepare, then success). `serapis demo` built twice identically; demo refuses foreign folders and the home directory.

## Remaining known defects and risks

- Integrity checks are heuristic; residual risks listed in `PRIVACY_AND_INTEGRITY.md` (other languages, euphemisms, multi-turn set-ups, short usable sentences, feedback mode modelling wording). Some legitimate requests are refused.
- Real OpenAI behaviour with the coach prompts, pass/reject rate of replies and cost: **not verified**.
- Phone-width and cross-browser rendering, screen-reader use and keyboard-only flow: **not verified**; only a desktop Chrome inspection of Home, coach page and plan on the demo data.
- Multi-process concurrency and Windows/Linux file-lock behaviour: not tested. PDF extraction macOS-only.
- Blackboard and Drive paths: not exercised live (out of scope).
- Coach cap counts failed attempts; a student with no key can burn calls on retries (40 per session) — mitigated by Discard.
- `hub_web.py` remains large (about 1,100 lines).
- Pre-existing, unchanged: lint warnings for unused variables in `hub_web.py`, `hub_service.py`, `reasoning.py`, `workspace.py`.

## Verdict

**READY WITH CONDITIONS** — see `PILOT_READINESS.md` for the conditions (facilitated sessions, real-provider smoke test before any real-AI session, consent and privacy briefing, incident rule, macOS for PDFs).

## Suggested vault update (not written; needs owner approval per AGENTS.md)

Proposed dated entry for `01 Projects/Serapis/Serapis.md`: "2026-10-25 — Independent review of the Assignment Coach and student-journey work found and fixed integrity-gate and reply-check gaps, session race conditions and first-run issues; 834 offline tests pass; verdict READY WITH CONDITIONS for a facilitated pilot; real-provider behaviour unverified. Source: `docs/pilot/CHECKPOINT-2026-10-25.md` (local checkpoint commit, unpushed)."


## Addendum — real-AI validation sprint (same day, offline portion)

- Checkpoint commit of the two earlier sprints: `1d29ae1` (local, unpushed). Pre-commit checks: no credentials or private data in the tree (only fake `test-credential` strings in existing tests), no stray artifacts, 834 tests passing.
- New: `evals/assignment_coach_v1/` harness (35 fictional scenarios; deterministic checks separated from a blank subjective review sheet; per-call latency, input/output tokens, estimated cost; validator acceptance/rejection by category; retries; fallbacks; grounding failures; suspected integrity violations; incorrect refusals; recovery scenarios) running the production pipeline end to end, with `pilot_budget.py` write-ahead spending control. `tests/test_coach_eval.py` (10 tests).
- Offline results (scripted provider, synthetic usage): 35 scenarios, 39 turns, 34 model calls, 5 turns refused by the gate, 0 incorrect refusals of 31 legitimate requests, both recovery scenarios recovered with exactly one student turn recorded. The scripted provider fails several honesty/citation checks by design of being naive; this shows the checks are sensitive. Self-checks: a mock that obeys everything is flagged for suspected integrity violations; a mock that fabricates is rejected by the validators, ends in the production fallback and never shows the invented reference.
- Defects found by the harness and fixed: gate false positive on "my own draft paragraph … do not rewrite it"; assignment-intent questions retrieved nothing (query now widened with the brief's vocabulary for those questions only); `parse_approval` failed when `usd_cap` was omitted (Decimal default rejected by its own validator).
- Test count: 846 passed, 0 failed, 0 skipped.
- Live run: approved by the owner at a US$2 / 300,000-token / 70-call cap for model `gpt-5.6-luna`; the key is present in the environment (value never displayed). **Not run**: the owner chose to stay offline until model prices can be attested. The harness refuses to start without `SERAPIS_EVAL_LIVE=1`, an approval file with attested pricing, and a configured key.


## Addendum 2 — model verification and live attempt

- **Model and price verified** from OpenAI's official pages on 2026-10-25 (record: `evals/assignment_coach_v1/PRICING_VERIFIED_2026-10-25.md`). `gpt-5.6-luna` is a real API id; US$0.20 / US$1.20 per 1M input/output tokens; Responses API and Structured Outputs supported. The older models overview omits it; the model page and pricing page list it. A newer sibling `gpt-6-luna` (US$0.10 / US$0.50) exists and was not substituted.
- **Harness hardening:** resume after interruption, per-scenario durable progress, errored scenarios recorded, ledger-to-call reconciliation, credential scrubbing of every output file, provider-only network allowlist for live runs, free authenticated preflight, safe failure detail in the production provider's error (type, HTTP status, error code, never the message or key).
- **Live attempts:** two attempts (the second under a new ledger capped at the remainder of the US$2 ceiling) each stopped at the first request with HTTP 401 `invalid_api_key`. Nothing was processed or billed; the ledger records a worst-case charge of about US$0.0046 per rejected request. Results folders `live_gpt-5.6-luna` and `live_gpt-5.6-luna_r2` are kept as the record of the failures; a corrected run must use a new label.
- **Not established:** any real-model behaviour. Pilot-readiness verdict is unchanged: READY WITH CONDITIONS, with the real-model evaluation still outstanding.


## Addendum 3 — completed live run

- Valid replacement key passed the free preflight (`GET /v1/models`, value never shown). Run under a new approval and ledger (`live_gpt-5.6-luna_r3`) capped at the remainder of the US$2 ceiling after the earlier charges: US$1.99 and 279,000 tokens. First 8 scenarios, then the remaining 27 with `--resume`.
- Result: 35 scenarios, 39 turns, 38 calls, 113,376 tokens, estimated US$0.0368, ledger fully reconciled, no errored or unmeasured calls. Total charged against the US$2 ceiling across all three ledgers: about US$0.046.
- Confirmed defects fixed: gate missed "something polished I can paste in" and "what would a top-mark opening sentence actually say" (`coach_integrity.py`); `long_paragraph` heuristic in `scoring.py` flagged 12 coaching replies addressed to the student (all inspected, none usable submission text). Tests: 854 passed (+8 cases).
- Not done: human completion of the review sheet; subjective quality remains unscored. Pilot verdict unchanged: READY WITH CONDITIONS.


## Addendum 4 — real-model quality review and learning-workflow evaluation

- Owner approved (in chat) two new live runs with new ledgers: A learning workflows (cap US$0.50 / 400,000 tokens / 80 calls) and B coach rerun (cap US$0.15 / 150,000 tokens / 60 calls). Neither reused the earlier US$2 approval.
- Run A: 32 scenarios, 56 calls, 101,281 tokens, estimated US$0.0564, ledger 56/56/56. Run B: 35 scenarios, 33 recorded calls, 108,041 tokens, estimated US$0.0348. Run B hung on one request for about 15 minutes; I killed it and resumed. That request's reservation stayed unsettled and is charged at its worst case (US$0.0052), so the folder's reconciliation reads 34 reservations / 33 settlements (disclosed, not hidden). Total new estimated spend about US$0.096; all sessions about US$0.14 of the original US$2.
- Fixes: short follow-ups retrieve the previous topic; a retry after a rejected coach reply tells the model why; coach prompt v2; internal source ids replaced by file names in coach, tutor, quiz, teach and revise displays (CLI keeps ids); harness retry for tutor turns; quiz answer-key check relaxed to the week's material after the first run (disclosed). Tried and reverted: an automatic corrective retry for failed generations (conflicts with the one-press-one-call design; owner decision).
- Tests: 871 passed. Local commits: `66d6678` (offline work) and the final commit of this sprint.
- Verdict unchanged: READY WITH CONDITIONS.
