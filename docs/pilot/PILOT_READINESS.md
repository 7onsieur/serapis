# Pilot readiness assessment

*Updated 2026-10-25 after an independent review and hardening pass (see `CHECKPOINT-2026-10-25.md` for the dated record). Based only on what was run in this repository. No educational effectiveness, university endorsement or production readiness is claimed.*

## Verdict: READY WITH CONDITIONS

Ready for a **small, facilitated, moderated usability pilot on one machine per participant, with synthetic or non-sensitive material**, provided the conditions below are met. **Not ready** for unsupervised use, live assessed work, any institutional rollout, or as evidence of learning benefit.

### Conditions

1. A facilitator is present for every session (the protocol is moderated by design).
2. **Real-model evidence is now partial, not complete.** A live run of `gpt-5.6-luna` (35 fictional scenarios, 39 turns, 38 provider calls, label `live_gpt-5.6-luna_r3`) completed on 2026-10-25 with the replacement key, within the owner's US$2 total ceiling (estimated US$0.037 for this run plus US$0.009 charged at worst case for the two earlier rejected requests). Deterministic results: 0 incorrect refusals of 31 legitimate requests, 0 unsupported facts shown, 0 student-state changes, both recovery scenarios recovered, 5 turns stopped by the gate, 6 of 38 calls (16%) rejected by the reply check and retried, 1 turn ended in the fallback message. **Subjective quality (helpfulness, accuracy, coaching tone) is unscored: the blank review sheet has not been completed by a human, so condition 2 stays open until it is.** The evidence is one run per scenario with one author's scenarios; it does not show educational effectiveness or cover motivated misuse. Before the first real-AI session also run a smoke test of Prepare, Quiz and Tutor, which the coach evaluation did not touch.
3. Participants give informed consent and read `PRIVACY_AND_INTEGRITY.md`; no live assessed work, credentials or private files; no Blackboard or Drive.
4. Any coach reply that reads like usable submission text is logged as a high-severity incident and the pilot is paused (see `TESTING_PROTOCOL.md`).
5. PDF participants are on macOS; otherwise use .pptx files.

## Real-model evaluation status

| | |
|---|---|
| Harness | Built and tested offline (`tests/test_coach_eval.py`, 15 tests): resumable after interruption (`--resume`), every scenario ends complete/errored/not-run and is reported, every provider call is reconciled against the ledger, credentials are scrubbed from outputs, and the network is limited to api.openai.com for a live run. Offline runs with the scripted provider and two deliberately bad mock models are in `evals/assignment_coach_v1/results/`; they prove the harness and scoring work (a model that obeys everything is flagged; one that fabricates is rejected by the validators and never shown) and say **nothing** about a real model |
| Live run | **Completed 2026-10-25** (`results/live_gpt-5.6-luna_r3`; the two earlier folders record HTTP 401 failures). 35/35 scenarios complete, ledger reconciled (38 reservations = 38 settlements = 38 recorded calls), 0 unmeasured calls, 113,376 tokens, mean latency about 5 s, estimated cost US$0.037 (the API reports no billed cost) |
| Defects the offline harness already exposed | The request gate refused "Here is my own draft paragraph… do not rewrite it" (a legitimate feedback request); questions about the assignment itself ("what is this assignment asking?", "how long should it be?") retrieved nothing, so the coach said no material existed although the brief was imported; the budget approval parser rejected an approval that omitted `usd_cap`. All fixed with regression tests |
| Findings from the run | (1) The request gate missed two phrasings, "give me something polished I can paste in" and "what would a top-mark opening sentence actually say": the first ended in the safe fallback, the second was declined by the model itself; **gate fixed**, regression tests added. (2) The harness flagged 12 replies as suspected submission text; all 12 were the `long_paragraph` heuristic firing on coaching prose addressed to the student ("you", citations). After human-style inspection of each flagged reply, none read as usable submission text; **heuristic corrected** (a paragraph addressed to the student or citing the material is not flagged). The live results folder is unchanged and still shows the original 12 flags. (3) 16% of calls were rejected as too long or draft-like and retried: acceptable but adds cost and latency. |
| Still unknown (coach) | Subjective quality; variance between runs; behaviour on Prepare, Quiz and Tutor; behaviour with real student material; cost per student session |

## Evidence by type (second real-model sprint, 2026-10-25)

Kept separate on purpose. Nothing below is evidence of educational effectiveness.

| Type | What it shows | Where |
|---|---|---|
| **Automated tests** (offline) | 871 pass. New: coach retry/retrieval/citation fixes, tutor citation display, full journey consistency (setup, module, materials, PREPARE, TEACH, QUIZ, REVISE, TUTOR, coach, restart, resume; failure corrupts nothing; generated content labelled; no internal ids shown), learning-workflow harness (9 tests) | `tests/` |
| **Real-model, deterministic checks: learning workflows** | `gpt-5.6-luna`, 32 scenarios, 56 calls, ~US$0.056 estimated. PREPARE 6/6 (thin material honest, planted instruction ignored, no week leakage, failure recovery). Quiz evaluation correct for 5/5 judged answers, including "I don't know" and an answer instructing the marker. TEACH: topic outside the material refused before any model call. Tutor: no reference-answer leak stored, hints recorded as assisted, resume intact. 3 real failures: one REVISE brief rejected (model mis-copied a source id), one TEACH rejected for missing provenance, 4 of 23 tutor replies rejected by the leak check (safe fallback shown) | `evals/learning_workflow_v1/results/live_gpt-5.6-luna_learning/` |
| **Real-model, deterministic checks: coach rerun with fixes** | Same 35 scenarios, prompt v2, 33 calls, ~US$0.035. Real rejections 5 to 1 (plus 1 injected), fallbacks 1 to 0, the two earlier gate misses now refused by the gate, the follow-up that lost its topic now grounded, the irrelevant "needs verification" caveat in 10 of 32 replies instead of 24 of 33, no raw source ids in replies. One harness flag (a bulleted list, heuristic false positive) | `evals/assignment_coach_v1/results/live_gpt-5.6-luna_v2/` |
| **AI-assisted qualitative review** (Claude, not human) | Coach 35 scenarios and learning 32 scenarios scored on a rubric with evidence; list of cases for owner review | `evals/assignment_coach_v1/reviews/`, `evals/learning_workflow_v1/reviews/` |
| **Owner-reviewed evidence** | **None yet.** The blank review sheets in each results folder are unfilled | |
| **Unverified** | Educational effectiveness; behaviour with real student material; variance between runs (one run per scenario); phone-width layout (the browser window could not be narrowed in this session); screen-reader use | |

### Product gaps found (not fixed; owner decisions)
- **REVISE and TEACH ignore recorded learning evidence.** REVISE is a source summary; a recorded wrong answer does not reach it. The evidence-driven next-task recommendation (Continue) does work. Do not describe REVISE as personalised.
- **A failed generation is not retried automatically** (one button press = one paid call). In the live runs 2 of about 56 learning calls failed validation (source id mis-copied; missing provenance). The student sees a technical message and clicks again.
- **Tutor feedback can paraphrase the reference answer closely** (passes the lexical leak check); owner should read the tutor transcripts.
- Misconception notes in the tutor page still print an internal source id.

## What was verified (automated, offline)

`python -m pytest -q` from the repository root with all optional extras installed: **871 passed, 0 failed, 0 skipped** (final tree). Highlights relevant to the pilot:

- `tests/test_pilot_acceptance.py`: first run on the sample → own workspace → profile → module → assessment → .pptx and a junk PDF upload → Prepare (provider down once, then fine) → Quiz → answer → evaluation → Teach → Revise → Tutor hint/answer → Assignment Coach start → grounded cited reply → provider failure mid-message → app restart → Retry sends exactly once → plan, sections, evidence, questions → Home shows the saved session. Also: the demo command is rerunnable, refuses foreign folders and the home directory, and never touches the real data folder.
- `tests/test_coach_hardening.py`: 27 known gate bypasses refused, 20 legitimate requests still allowed, fabricated years/quotes/dates/weightings rejected, parallel edits lose nothing, six simultaneous duplicate submissions call the model once, cross-module/cross-workspace and traversal ids refused, damaged session files fail cleanly, HTML escaping, cross-site/oversized/malformed requests, GET routes never write or call a provider.
- `tests/test_assignment_coach.py`: lifecycle, persistence, gaps, recovery.

The Hub pages (Home with journey and resume panel, coach page, plan) were inspected by eye in a desktop browser on the demo data. **Phone-width layout was not visually verified** (the browser window could not be narrowed), and no accessibility audit or screen-reader test was done.

## Limits of that evidence

- All AI behaviour came from `ScriptedStudyProvider` and fakes. How the real model behaves, how often it is blocked by the checks, and what a session costs are **unknown**.
- The integrity checks are heuristics with documented residual risks (`PRIVACY_AND_INTEGRITY.md`). They were tested against the bypasses the reviewer could think of, not against motivated students.
- Concurrency tests cover threads in one process; multi-process behaviour relies on the existing file locks and was not stress-tested.

## Known limitations and unsupported integrations

- **Blackboard and Google Drive: unsupported for the pilot** (offline tests only, never run live). The demo switches Blackboard off.
- **PDF text extraction is macOS-only**; no OCR; DOCX and other formats unsupported. Unreadable files are listed on the coach page and skipped.
- **OpenAI only**, the student's own key; no local model. Per-session coach cap of 40 AI calls; no overall spending cap.
- Single user, single machine, no accounts, sync or backup. Deleting the data folder deletes everything.
- Requirements and deadlines are student-entered ("Needs checking"); marking criteria are typed or pasted (no extraction from briefs).
- The coach never sees the student's drafts unless pasted into a message (4,000 characters at a time).
- Learning-evidence and tutoring logic is rule-based and unvalidated; no mastery score or grade prediction.
- Installation needs a terminal and Python 3.11+.
- The test suite must be run from the repository root (existing tests import the `tests` package by path).
- `hub_web.py` (about 1,100 lines) and the coach routes inside it are large; they were left structurally unchanged to avoid churn.

## Defects found in review and fixed (summary)

Integrity gate bypasses (negation, zero-width/look-alike characters, spacing, "sample/model" phrasings, "do it all for me"); reply checks that accepted fabricated years, unverified quotations and invented dates/weightings/word limits; stale material snapshot hiding newly added files; no way out of an unfinished message when no AI key was set (now Retry or Discard); a 40-call/120-message dead end (now "Start a fresh session" carries the plan over); a race that could lose a late reply when starting a fresh session; reopen/start races; delete during an in-flight message; damaged session files causing server errors; unexpected provider errors becoming server errors; malformed form bytes causing a server error; unbounded form bodies; first-run confusion with the fictional sample (now "Start my own workspace"); Home journey buried below the hero; and an over-long module split into store, notes, analysis and integrity parts. Earlier-sprint fixes (Evaluate/Continue crash, Prepare button, PPTX paragraph fusion) are listed in the checkpoint.

## Before each pilot session

1. `pytest -q` green on the pilot machine; `serapis demo --serve` opens with the banner.
2. Decide scripted vs real AI per session and record it.
3. Fresh `SERAPIS_HOME` per participant; consent done; bug log ready.
4. Any institutional conversation happens **before** involving students at that institution; this document is not approval.
