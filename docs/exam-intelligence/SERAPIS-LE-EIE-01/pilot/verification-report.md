# SERAPIS-LE-EIE-01 pilot — verification report

Date: 2026-10-30. Scope: 12 candidate questions in `pilot-questions.md` (45 marks). Research-scale only.

## 1. Methods

1. **Symbolic verification** (`verify_pilot.py`, sympy): recomputes each answer from the question's own algebra (roots, completed-square form, minimum point, discriminant, Pythagoras, rounding, uniqueness, rejection of the other root). Output: `verification_results.json`.
2. **Independent blind solve:** a separate model instance (Sonnet-class subagent, fresh context) was given only the question text and calculator/mark flags, never the solutions or mark schemes, and asked to solve, critique ambiguity, marks, calculator flag and content level. It did not run code; arithmetic was by hand.
3. **Negative control:** the symbolic verifier was re-run on a copy with six deliberately wrong expected values (Q04, Q05, Q07, Q09, Q11, Q12). All six were flagged as FAIL, so the verifier is capable of catching such errors.
4. **Teacher review:** not yet done. See `teacher-review-package.md`.

## 2. Results

| Question | Symbolic | Blind solve answers | Blind-solve comments |
|---|---|---|---|
| Q01–Q08, Q11, Q12 | PASS (all checks) | Agree with draft | No ambiguity reported |
| Q09 | PASS | Agree | Suggests the mark scheme must explicitly credit rejecting w = −7 (it does: B1) and follow-through in (c) (it does) |
| Q10 | PASS | Agree | **Minor ambiguity:** "the value of x" has two algebraic roots; the diagram and context imply a length. Mark scheme already gives B1 for rejecting −7.28. Wording unchanged; recorded as a limitation for teacher decision |
| Q05 | PASS | Agree on answers | Blind solver quoted the unrounded smaller root as 0.2793; correct value is 0.27924… (0.2792). Rounded answer 0.28 unaffected. Solver slip, not a question defect |

Other points raised by the blind solver and recorded as limitations rather than changes: Q08(b) minimum is justified by a > 0 but not asked; Q12 discriminant method is an alternative (mark scheme accepts it); Q03 can also be solved with the formula (discriminant 529).

## 3. Rejected and corrected items

- **Rejected by verification: none.** No question failed the symbolic or blind checks.
- **Pre-verification design changes (not hidden):** during drafting, before any verification run: (a) Q01 mark split changed from 2 to 3 marks; (b) a draft Q11 reusing the rectangle context of Q09 was replaced by the projectile question to improve variety; (c) two wording fixes were made to Q02 and Q04 marking text (removed an awkward rule and referenced the formula sheet). These were authoring edits, not verification failures.
- **Blueprint error corrected (v0.1 to v0.2):** v0.1 claimed "(or two simultaneous equations)" in DfE Alg 21 was bold and that factorising items were plain font. Visual inspection showed the former is underlined (the bold text was in Alg 22) and the latter underlined. See `../blueprint-v0.2.md`.

## 4. Independence and its limits

- The symbolic verifier and the questions were written by the same author; the expected values were mine. The negative control shows it detects wrong values but cannot detect a shared misreading of the intended question.
- The blind solver is the same model family as the author. Hand-reasoned agreement across 12 items is useful but correlated. A teacher is the only genuinely independent check.
- Agreement says nothing about **difficulty, exam-likeness, pedagogy or mark-scheme sufficiency**.
- No Edexcel or other board material was used, so no board-specific conventions are tested.

## 5. Actual usage and cost

- Blind-solve subagent: **37,813 tokens, 1 tool call, about 22 s** (as reported by the harness). Dollar cost is not reported by the harness; at the discovery report's assumed mid-tier prices (unchecked) this is on the order of a few cents.
- Main-session usage (research fetches, drafting, verification, document generation) is **not exposed to me**, so no figure is given. Run `/cost` in the session for the actual total. Web fetch calls use a separate small model that also does not report usage to me.
- The pilot's cost per question is therefore **not established** here; do not extrapolate from the subagent figure.
- Human review time is the dominant cost and has not yet been measured.

## 6. Limitations

- Calculator flags are inferred. Q09 is marked "either".
- Q10 relies on a described diagram; production needs an accurate drawn diagram.
- Difficulty bands are hypotheses [I]; the pilot set mixes grades 4–8 by design and is not balanced to paper-level rules.
- Sheet contents were not verified against a board source (blueprint B2).
