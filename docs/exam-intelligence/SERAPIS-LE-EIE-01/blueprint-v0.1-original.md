# SERAPIS LE — Exam Intelligence Report (SERAPIS-LE-EIE-01)

Blueprint v0.1 — GCSE Mathematics (England, 9–1), Higher tier, Quadratic equations
Prepared: 2026-10-30. Status: DRAFT for independent Maths teacher review. Not for student release.
Scope: DfE/Ofqual-only route. No exam-board papers, mark schemes or board specifications were used.

Evidence tags: **[V]** stated in an inspected source (cited by ID); **[I]** inferred by the analyst from sources (reasoning shown); **[A]** assumption / Serapis design choice, not evidenced; **[U]** unknown.

---

## A. Source audit

### A1. Documents inspected

| ID | Document | Reference | Publisher | Version evidence | SHA-256 of inspected file |
|---|---|---|---|---|---|
| S1 | GCSE mathematics: subject content and assessment objectives (17 pp) | DFE-00233-2013 | DfE | Published 1 Nov 2013 (page). PDF footer: © Crown copyright 2013 | 647a751b51c71d9ced1c9356aa70b15ceb1a4acb2fd5bc9af49619ead06d0ee6 |
| S2 | GCSE (9 to 1) Subject Level Conditions and Requirements for Mathematics (39 pp) | Ofqual/16/6160 | Ofqual | Published 9 Apr 2014, updated 16 Feb 2017 (page). PDF footer: © Crown copyright 2017 | ea7f34e22be32aaeecce301fcf190f84202648990cacb8d16738ae09fbc6a53c |
| S3 | GCSE (9 to 1) Subject Level Guidance for Mathematics (16 pp) | Ofqual/15/5722 | Ofqual | Published 23 May 2014, revised 30 Jun 2015 (page and document revision table). PDF footer: © Crown copyright 2015 | 0f84e6dae5947e008748633d37dad9c9b2cffe124b3d14d6062498effd5aaf44 |

Files were fetched from the assets.publishing.service.gov.uk links on the gov.uk publication pages and text-extracted locally. Page counts of the downloaded PDFs match the page listings (17 / 39 / 16).

### A2. Licence verification

- Publication pages: "All content is available under the Open Government Licence v3.0, except where otherwise stated" (all three).
- Inspected PDF footers:
  - S2 (2017 footer) and S3 (2015 footer): "licensed under the terms of the Open Government Licence v3.0 except where otherwise stated."
  - S1 footer: "under the terms of the Open Government Licence" (version not stated in the PDF; the publication page states v3.0). **Minor discrepancy, recorded, not material.**
  - S2 also contains a second, earlier footer (© Crown copyright 2013, "Open Government Licence", no version) at an internal appendix, because Appendix 1 reproduces S1. The licence position for that appendix is the same as S1.
- Third-party material: all three PDFs carry the standard line that any identified third-party copyright must be cleared separately. **No third-party material was identified in the extracted text of the sections used.** Figures in S1's appendix (triangles) were not extracted as images; they are standard mathematical diagrams and are not relied upon.
- OGL v3.0 permits copying, adapting and commercial exploitation with attribution. It does not by itself address AI processing; it contains no restriction on it. **[I]** Founder/legal should still confirm they are comfortable that OGL v3.0 covers AI processing and derivative blueprints (low risk, but not a legal opinion).
- Required attribution (OGL v3.0): "Contains public sector information licensed under the Open Government Licence v3.0." Serapis outputs derived from S1–S3 should carry this.

### A3. Currency of sources — UNVERIFIED

- S2 was last updated Feb 2017 and S3 June 2015 per the publication pages. I did not check whether Ofqual or DfE have since amended or withdrawn them (for example in a later consolidated conditions document).
- **[U] Action: confirm these remain the current governing documents before release.**

### A4. Content excluded

- No Edexcel (or other board) specification, sample assessment materials, past papers, mark schemes, examiner reports or third-party websites. None were consulted or recalled.
- I am aware from general knowledge that Edexcel 1MA1 uses three 80-mark papers; this was deliberately **not used** in the blueprint and no Edexcel-specific claim is made.

### A5. Coverage gaps

- Pattern evidence (Phase 2): **none available** (no authorised assessment examples).
- No board-level interpretation of the DfE content, no command-word list, no mark-scheme conventions, no board formula or notation conventions.

---

## B. Specification map (quadratics)

Source: S1, Algebra section (statement numbers are the DfE's own, within the Algebra section), tier areas per S2 ¶15.

Tier-area key (S2 ¶15, [V]): Area 1 = standard font, assessed at both tiers. Area 2 = underlined, assessed at both tiers; higher-tier students expected confident and competent. Area 3 = **bold**, assessed at **Higher tier only**.

Method used: font weight was machine-read from the PDF font data (bold vs regular). **Underlining cannot be detected this way, so Area 1 vs Area 2 is not distinguished.** This does not affect Higher-tier eligibility (both are assessed), but it matters for the Foundation overlap; a human should check against the PDF visually.

| Ref | Requirement (S1 wording abbreviated) | Detected weight | Tier consequence |
|---|---|---|---|
| Alg 4a | Expand products of two binomials | regular | Both tiers [V] (font), underline [U] |
| Alg 4a' | ...expand products of more than two binomials ("or more") | **bold** | **Higher only** |
| Alg 4b | Take out common factors | regular | Both tiers |
| Alg 4c | Factorise x² + bx + c, including difference of two squares | regular | Both tiers |
| Alg 4d | Factorise ax² + bx + c | **bold** | **Higher only** |
| Alg 5 | Rearrange formulae to change the subject | regular | Both tiers (prerequisite, [I]) |
| Alg 11 | Identify and interpret roots, intercepts, turning points of quadratic functions graphically | regular | Both tiers |
| Alg 11 | ...deduce roots algebraically | regular | Both tiers |
| Alg 11' | ...turning points by completing the square | **bold** | **Higher only** |
| Alg 18a | Solve quadratic equations algebraically by factorising | regular | Both tiers |
| Alg 18a' | ...including those that require rearrangement (parenthetical) | **bold** (per text run; see H1) | **Higher only** [V] font |
| Alg 18b | ...by completing the square | **bold** | **Higher only** |
| Alg 18c | ...by using the quadratic formula | **bold** | **Higher only** |
| Alg 18d | ...find approximate solutions using a graph | not bold | Both tiers (underline [U]) |
| Alg 19 | Solve linear/quadratic simultaneous equations algebraically | linear/quadratic detected **bold** | **Higher only**; adjacent topic, outside the requested coverage |
| Alg 21 | Translate situations into expressions/formulae; derive an equation, solve and interpret | single equation regular; "(or two simultaneous equations)" **bold** | Single-equation modelling: both tiers; simultaneous: Higher only |
| Alg 22 | Quadratic inequalities in one variable | **bold** | **Higher only**; adjacent topic, outside the requested coverage |
| Alg 6 | Show expressions equivalent; use algebra to support and construct arguments | regular | Both tiers |
| Alg 6' | ..."and proofs" | **bold** | **Higher only**, consistent with S3 AO2 4b |
| Num 7/8 | Calculate exactly with surds; simplify surd expressions; rationalise denominators | **bold** | **Higher only**; exact-surd answers to formula questions are Higher content [I] |
| Num 15 | Round to specified dp / sf | not bold | Both tiers; needed for decimal answers [I] |
| App 1 | Quadratic formula x = (−b ± √(b² − 4ac)) / 2a: candidates must know it; **must not be given in the assessment** | n/a | [V] S1 Appendix item 1 |

### Prerequisite relationships — **[I]**

S1 does not list prerequisites. The following are inferred from the content statements and must be confirmed by the reviewer:
- Solving by factorising ← factorising quadratics (Alg 4c/4d), solving linear equations (Alg 17), zero-product reasoning (not stated in S1).
- Quadratic formula ← substitution (Alg 2), arithmetic with negatives and roots (Num 2, 6), surds (Num 8), rounding (Num 15).
- Completing the square ← expanding binomials (Alg 4a), square roots (Num 6).
- Multi-step problems ← forming equations (Alg 21), interpreting solutions in context (S3 AO3 strand 3), rejecting inadmissible roots (S3 AO3 strand 4b, [I]).

### Out of scope for this blueprint (adjacent)

Quadratic inequalities (Alg 22), linear/quadratic simultaneous equations (Alg 19), quadratic sequences (Alg 24–25), graph sketching of quadratics (Alg 12), iteration (Alg 20). Recorded so the generator does not drift into them unless explicitly requested.

---

## C. Assessment-pattern findings

### C1. Pattern evidence from exam papers: NONE — [U]

No authorised assessment examples were provided. Therefore the following cannot be established and **must not be asserted**:
- Frequency of quadratics question types in any series or at any board.
- Typical mark allocations per question type.
- Typical command words, phrasing, layout or answer-format conventions.
- Edexcel-specific conventions or examiner expectations.
- Item-level difficulty or facility.

### C2. Regulatory structural constraints that ARE evidenced

| Finding | Source |
|---|---|
| Higher-tier assessments must be targeted at grades 4–9; 50% of marks at grades 4–6 and 50% at grades 7–9. This applies to each assessment as a whole, not to each question. | S2 Tiering ¶5, ¶9 [V] |
| AO weightings (Higher): AO1 40%, AO2 30%, AO3 30%. | S1 AO table; S3 [V] |
| Tolerance on AO weighting per series: ±3 percentage points (an awarding-organisation obligation, shown for context). | S2 weighting section [V] |
| Algebra is 30% of Higher-tier marks (±3%). Quadratics are a subset; its share is not specified. | S2 Tiering ¶22–23 [V] |
| Between 33% and 50% of total marks must be on non-calculator questions. Per-question calculator status is not prescribed. | S2 Condition GCSE(Mathematics)4 [V] |
| Content assessed must not be predictable; boards sample across series. | S2 ¶16, ¶18, ¶21 [V] |
| Higher tier assesses Areas 1, 2 and 3 (including bold content). | S2 ¶15–16 [V] |
| Quadratic formula must be recalled, not provided. | S1 Appendix 1 [V] |

### C3. AO interpretations relevant to quadratics (S3)

- **AO1** (Higher 40%): strand 3a/3b (routine procedures / multi-step set tasks) must be at least 80% of AO1 marks; at Higher there should be more 3b than 3a. Routine procedure = procedure made clear by the task, no significant context, familiar from the spec. Recall (strand 1) and notation (strand 2) are each at most 10% of AO1 marks. [V]
- **AO1 attribution rule:** where an AO2/AO3 task resolves into a routine procedure and marks are given for carrying it out accurately, those marks belong to AO1. [V] (S3 AO3 notes, AO1 3b note.)
- **AO2** (Higher 30%): deduce/infer, chains of reasoning to a **given** result, interpret/communicate, present arguments and proofs, assess validity. Proof is Higher-only. [V]
- **AO3** (Higher 30%): translate problems (mathematical or non-mathematical contexts, single process or series of processes), connections, interpret results in context, evaluate methods/results, evaluate assumptions. Tasks should not make the procedure clear; at least one-third of AO3 marks should come from tasks addressing two or more AO3 strands; greater emphasis on strands 1–3 than 4–5, and within strand 1 on multi-step (1b, 1d). Answers should be framed in the original problem, not in the abstract. [V]
- The same-topic question can be written at different AOs: factorise-and-solve (AO1), "show that" a quadratic follows from a context (AO2 given-result chain), a real-world area/projectile/cost problem requiring the learner to form and solve a quadratic (AO3). **[I]**

---

## D. Topic-specific question blueprint (for the Question Generator)

Everything in D is a Serapis design proposal grounded in S1–S3; items tagged [A] are not evidenced and are for teacher review.

### D1. Topic profile

- **Topic:** Algebra → Solving equations → Quadratic equations (S1 Alg 18), with Alg 4 factorising, Alg 11 completing-the-square link, Alg 21 modelling.
- **Learning objectives (derived from S1):**
  - LO-Q1: Factorise quadratic expressions x² + bx + c, including difference of two squares (Alg 4c). Both tiers.
  - LO-Q2: Factorise ax² + bx + c, a ≠ 1 (Alg 4d). Higher only.
  - LO-Q3: Solve quadratic equations by factorising (Alg 18a). Variants needing rearrangement to ax² + bx + c = 0 are bold in S1 so Higher-only (Alg 18a'); equations already in standard form are not bold.
  - LO-Q4: Solve quadratic equations using the quadratic formula, giving exact (surd) or rounded answers (Alg 18c, Num 8, Num 15). Higher only.
  - LO-Q5: Solve quadratic equations by completing the square, and use completed-square form to find roots or turning point (Alg 18b, Alg 11). Higher only.
  - LO-Q6: Form and solve quadratic equations in context and interpret / validate the solutions (Alg 21; S3 AO3).
- **Key concepts:** equation vs expression, root/solution, zero-product property [I], discriminant sign determines number of real roots [I — not named in S1; a teacher decision whether to include], exact vs approximate answers.
- **Common errors:** *No source supports any misconception claim.* The following are **hypotheses only**, for teacher confirmation and not to be cited as evidence: sign errors in b and in the formula; forgetting the ± (one root only); dividing by x; not rearranging to zero before factorising; mis-halving b in completed square; giving an inadmissible negative length. [A]

### D2. Question design

| Format | Target skill / AO | Suggested marks [A] | Higher-tier suitability | Answer type |
|---|---|---|---|---|
| Solve by factorising (a = 1); rearrangement variants are Higher-only content | AO1 3a | 2–3 | Lower end of grade 4–6 targeting [I] | Unique pair of values |
| Factorise ax² + bx + c then solve | AO1 3b | 3 | Mid–upper | Unique pair |
| Quadratic formula, exact surd form | AO1 3b | 3–4 | Grade 6–7 range [I] | Exact surd expressions |
| Quadratic formula, rounded to stated dp/sf | AO1 3b | 3 | Mid | Unique pair of decimals; rounding rule stated |
| Completed square form, state roots or turning point | AO1 3b / AO2 | 3–4 | Grade 7+ [I] | Unique |
| "Show that" a context gives a given quadratic, then solve | AO2 (chain to given result) + AO1 | 4–5 | Mid–upper | Unique; derivation is the mark-bearing work |
| Context problem: form, solve, interpret, reject inadmissible root | AO3 strands 1b/1d, 3, 4b | 4–6 | Upper (grade 7–9) [I] | Unique; may have discarded root |
| Prove/justify a quadratic property (for example, a given expression always positive via completed square) | AO2 proof | 3–4 | Upper | Argument |

- **Difficulty levels:** The only evidenced difficulty structure is the tier-level split (50% grades 4–6, 50% grades 7–9, S2 ¶9). **Item-level grade mapping is not evidenced; the grade bands above are analyst inferences [I]** that need teacher judgement. Do not claim a question "is grade 8" on this evidence.
- **Calculator status:** assign per question. Quadratic-formula questions with exact surd answers and factorising/completing-the-square are plausible non-calculator tasks [I]; decimal-rounded formula answers need a calculator [I]. Set a flag per question; any assembled test must respect the 33–50% non-calculator rule (S2 Condition 4) if aiming for paper-like balance.
- **Diagrams/tables/data:** context questions with geometry (area, perimeter, right triangle via Pythagoras, S1 Appendix) must include a labelled, consistent diagram specification; free-text description alone is insufficient for the reviewer. [A]
- **Unique vs multiple answers:** all questions must have a determinate answer set (quadratic: up to two roots). Questions with "state whether the equation has real roots" are allowed only if discriminant reasoning is accepted by the teacher as in scope [I].
- **Original-question constraints:** the Generator must not receive or recall any board paper text. Use parametric generation (choose roots/coefficients first, derive the equation) so that answers are known by construction. [A]

### D3. Mix guidance for topic practice (proposal [A])

The regulations give no topic-level mix. For a topic set, a teacher may choose; a suggested starting split is a majority AO1 (reflecting 40%) with a minority of AO2/AO3 context tasks. Because topic practice is not a paper, **AO proportions across a short set should not be forced to equal the 40/30/30 paper weighting**; rather, they should be reported per question. [A]

---

## E. Marking blueprint

- **Marking principles evidenced in S3:** marks for the routine procedure are AO1; AO3 working should usually be shown so partial credit is possible, though credit without working may be appropriate in some cases and should be stated in the mark scheme (S3 AO3 notes). AO2 requires explanation/justification; AO3 responses should not require it. [V]
- **Mark notation:** M (method), A (accuracy), B (independent) marks, "follow-through", and "correct answer implies marks" are **board mark-scheme conventions, not in S1–S3.** Using them here is a Serapis internal convention [A]; label as "Serapis-style marking, not Edexcel marking" and do not imply board fidelity.
- **For every question the mark scheme must contain:**
  1. Fully worked model solution(s), including all valid alternative methods the topic allows (factorising, formula, completing the square, graph if appropriate).
  2. A mark-by-mark rationale stating what demonstrable work earns each mark, and the AO it is credited to.
  3. Accepted equivalent forms (exact surd vs decimal; ordering of roots; unsimplified but correct fractions) and rounding/units rules.
  4. For context questions: the accepted treatment of inadmissible roots and how the final interpretation mark is earned.
  5. Anticipated incorrect responses and what partial marks they earn, flagged as analyst hypotheses until teacher-confirmed.
  6. Flag whether a subject specialist must review.
- **Verified-standard rule:** AI-written answers are **not** treated as verified marking standards. A solution becomes a marking standard only after (a) independent deterministic recomputation and (b) teacher sign-off. [Per mandate.]
- **Human review required:** yes, for 100% of this blueprint's first experiment items (see Recommendation).

---

## F. Quality gates (before any question is released to a student)

Fail any gate means reject or revise; do not silently repair.

1. **Source gate:** the question's skill IDs trace to S1 statements; no content from restricted sources was supplied to the generator.
2. **Tier gate:** every skill used is Area 1–3 content assessable at Higher; no content outside the selected specification and tier; the quadratic formula is not provided in the question (S1 App. 1).
3. **Deterministic mathematical gate:** a script (for example a symbolic solver) recomputes the roots/answers from the question's own parameters; mismatch fails. Check uniqueness, domain restrictions (for example length > 0) and rounding rules.
4. **Mark-allocation gate:** each mark corresponds to a demonstrable step; total marks equal sum of marks; AO attribution follows S3 (routine procedure = AO1).
5. **Internal consistency gate:** diagrams, data and context are consistent with the numbers (areas, perimeters, units).
6. **Ambiguity gate:** a second reader (model in a fresh context, then teacher) solves blind; any divergent answer or alternative reading fails.
7. **Originality gate:** no reproduction of a known exam question. Without reference papers a similarity check is not possible; originality rests on parametric construction plus teacher recognition. [U — see H]
8. **Labelling gate:** never described as an official, past or predicted exam-board question; carries the OGL attribution where S1–S3 content is reproduced; states "tier-aligned to DfE/Ofqual requirements, not board-verified".
9. **Mark-scheme completeness gate:** items in E present for every question.
10. **Human gate:** subject-specialist sign-off recorded with reviewer name and date.

---

## G. Evidence register

| # | Finding | Source | Status |
|---|---|---|---|
| E1 | Solving quadratics by factorising is plain-font content; the rearrangement parenthetical reads as bold | S1 Alg 18 | [V] (font); underline [U] |
| E2 | Completing the square and quadratic formula are bold, so Higher-only | S1 Alg 18; S2 ¶15 Area 3 | [V] |
| E3 | Factorising ax² + bx + c is bold, so Higher-only | S1 Alg 4; S2 ¶15 | [V] |
| E4 | Quadratic formula must be known, not given | S1 Appendix 1 | [V] |
| E5 | Higher tier targets grades 4–9; 50% marks grades 4–6, 50% grades 7–9 | S2 Tiering ¶5, ¶9 | [V] |
| E6 | AO weightings H: 40/30/30 | S1 AO table; S3 | [V] |
| E7 | 33–50% of marks non-calculator | S2 Cond. GCSE(Mathematics)4 | [V] |
| E8 | Algebra 30% of Higher marks (±3%) | S2 Tiering ¶22–23 | [V] |
| E9 | Routine procedure marks within problems credited to AO1; AO1 strands 3a+3b ≥ 80% of AO1 marks; more 3b than 3a at Higher | S3 AO1 table and notes | [V] |
| E10 | Proof is Higher-tier only (AO2 4b) | S3 AO2 | [V] |
| E11 | AO3 tasks should not make procedure clear; ≥ one-third of AO3 marks from multi-strand tasks; emphasis on strands 1–3; within strand 1 on 1b/1d | S3 AO3 | [V] |
| E12 | Boards must avoid predictable sampling | S2 ¶16, ¶18, ¶21 | [V] |
| E13 | Prerequisite links | Analyst reasoning from S1 | [I] |
| E14 | Item-level grade bands for question types | Analyst reasoning | [I] |
| E15 | Mark totals per format, M/A/B notation, error hypotheses | none | [A] |
| E16 | Pattern frequencies, Edexcel conventions, examiner expectations | none | [U] |

---

## H. Unresolved questions / limitations

1. **Underlining not machine-detectable:** Area 1 vs Area 2 not separated; bold/regular was read per text run and can mis-split mid-sentence phrases (the Alg 18 rearrangement parenthetical was read as bold). Reviewer to check the S1 PDF visually.
2. **Currency of S1–S3** not verified (A3). Possibly superseded by later amendments.
3. **S1 licence version:** PDF says "Open Government Licence" without version; page says v3.0. Immaterial but recorded.
4. **OGL and AI:** OGL v3.0 does not mention AI; founder to decide whether to seek legal confirmation.
5. **No pattern evidence:** frequency, mark distributions, command words, answer formats, difficulty calibration and Edexcel conventions all unknown. Any such claim in generated material must be rejected.
6. **Item-level difficulty:** grade bands are inferred; require teacher calibration (ideally with real student performance data later).
7. **Misconceptions:** no authorised source; teacher input required.
8. **Originality verification:** cannot be checked against board papers without access. Whether a local, non-AI similarity check against licensed papers is permitted remains open (from the discovery report).
9. **Discriminant / number-of-roots reasoning, zero-product reasoning, graph-based approximate solutions:** unclear whether in the requested coverage; teacher to decide.
10. **Calculator allocation per question:** inferred; no board convention.
11. **Fidelity statement:** the blueprint supports DfE/Ofqual alignment only. It supports no claim of Edexcel 1MA1 fidelity.
12. **Caveat on the sources of S2 Appendix:** S2 reproduces S1 as Appendix 1; no conflict between the two was found in the sections used, but a full diff was not done.

---

## Appendix: Blueprint JSON (schema-aligned with discovery report)

```json
{
  "blueprint_id": "SERAPIS-LE-EIE-01-quadratics-v0.1",
  "board": "none (DfE/Ofqual regulatory baseline; future target Pearson Edexcel 1MA1, fidelity unclaimed)",
  "qualification": "GCSE Mathematics (England, 9-1) Higher",
  "source_provenance": [
    {"doc": "DFE-00233-2013", "licence": "OGL v3.0", "evidence": "gov.uk page and PDF footer", "sha256": "647a751b51c71d9ced1c9356aa70b15ceb1a4acb2fd5bc9af49619ead06d0ee6"},
    {"doc": "Ofqual/16/6160", "licence": "OGL v3.0", "evidence": "gov.uk page and PDF footer", "sha256": "ea7f34e22be32aaeecce301fcf190f84202648990cacb8d16738ae09fbc6a53c"},
    {"doc": "Ofqual/15/5722", "licence": "OGL v3.0", "evidence": "gov.uk page and PDF footer", "sha256": "0f84e6dae5947e008748633d37dad9c9b2cffe124b3d14d6062498effd5aaf44"}
  ],
  "topic": {"id": "ALG-QUAD", "name": "Quadratic equations", "spec_refs": ["S1 Alg 4", "S1 Alg 11", "S1 Alg 18", "S1 Alg 21"]},
  "skills": [
    {"id": "LO-Q1", "statement": "Factorise x^2+bx+c incl. difference of two squares", "ao": "AO1", "tier_area": "1/2", "calculator": "either"},
    {"id": "LO-Q2", "statement": "Factorise ax^2+bx+c", "ao": "AO1", "tier_area": "3 (Higher only)", "calculator": "either"},
    {"id": "LO-Q3", "statement": "Solve quadratics by factorising incl. rearrangement", "ao": "AO1", "tier_area": "1/2 (rearrangement variants: Higher only)", "calculator": "either"},
    {"id": "LO-Q4", "statement": "Solve by quadratic formula (exact or rounded)", "ao": "AO1", "tier_area": "3 (Higher only)", "calculator": "either"},
    {"id": "LO-Q5", "statement": "Complete the square; roots / turning point", "ao": "AO1/AO2", "tier_area": "3 (Higher only)", "calculator": "either"},
    {"id": "LO-Q6", "statement": "Form, solve, interpret quadratics in context", "ao": "AO3", "tier_area": "1/2/3", "calculator": "either"}
  ],
  "question_patterns": "NOT ESTABLISHED - no authorised pattern evidence (see C1)",
  "design_formats": "see D2 (analyst proposals, [A]/[I])",
  "marking_principles": ["S3: routine-procedure marks are AO1", "S3: AO3 working usually shown; partial credit rules stated in scheme", "Quadratic formula not given (S1 App.1)", "Serapis-style M/A/B notation is internal, not board-faithful"],
  "constraints": {
    "forbidden_content": ["quadratic inequalities", "linear/quadratic simultaneous", "board-specific phrasing", "any claim of official or predicted exam question"],
    "tier_targeting": "Higher: 50% marks grades 4-6, 50% grades 7-9 (assessment-level)",
    "calculator": "33-50% of total marks non-calculator (assessment-level)"
  },
  "evidence_status": {"verified": ["E1-E12"], "inferred": ["E13", "E14"], "assumed": ["E15"], "unknown": ["E16"]},
  "reviewed_by": null,
  "version": "0.1-draft"
}
```
