# SERAPIS LE — Exam Intelligence Report (SERAPIS-LE-EIE-01)

Blueprint **v0.2** — GCSE Mathematics (England, 9–1), Higher tier, Quadratic equations. Supersedes v0.1 (preserved unchanged as `blueprint-v0.1-original.md`).

## Changes from v0.1 (2026-10-30)

1. **Formula sheets (correction).** v0.1 said the quadratic formula "must be recalled, not provided". That is the historical DfE content-document statement. Current examination arrangements differ: see new section B2. v0.1's gate and mark-scheme wording that relied on the formula not being given are replaced.
2. **Tier formatting verified visually.** Bold and underline in DFE-00233-2013 pp5–7 were inspected on rendered page images and by extracting drawn underline rules; renders are in `evidence/`. This corrects v0.1: factorising x²+bx+c, expanding two binomials and solving quadratics by factorising are **underlined (Area 2)**, not plain (Area 1); and the claim in v0.1 that "(or two simultaneous equations)" in Alg 21 is bold was **wrong** (it is underlined; the bold text was Alg 22's "one or two variable(s)").
3. **Currency checks** on S1–S3 (section A3) and the 2026 Ofqual decisions.
4. **Evidence separation.** Sourced requirements [V], inferences [I], assumptions [A] and unknowns [U] remain tagged; section D now separates sourced requirements from inferred difficulty bands, hypothesised misconceptions and Serapis-specific marking conventions.
5. Pilot results (12 candidate questions) are in `pilot/`; they do not alter the blueprint's evidence status.

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

### A3. Currency of sources — checked 2026-10-30

| Source | Check made | Result |
|---|---|---|
| S1 DFE-00233-2013 | Re-fetched gov.uk publication page | Published 1 Nov 2013; no update history, no withdrawn/superseded banner; no newer subject content document linked. [V] |
| S2 Ofqual/16/6160 | Re-fetched page; read in-document revision table | Last updated 16 Feb 2017 (removed tiering ¶6 only). 12 Apr 2016 revision withdrew detailed calculator-use rules; **Condition GCSE(Mathematics)4 (33–50% non-calculator marks) remains in the Feb 2017 text**. No withdrawal banner. [V] |
| S3 Ofqual/15/5722 | Page and PDF revision table | First published 23 May 2014, revised 30 Jun 2015. No newer version found. [V] |
| Ofqual GCSE qualification-level conditions | Search result only | Reported (not opened) as revised July 2026. Not reviewed; may affect general requirements. **[U]** |
| Formula/equation sheets | Ofqual and DfE pages (section B2) | Current arrangements differ from S1 Appendix 1 wording; handled in B2. [V] |
| Curriculum and Assessment Review (Nov 2025) | Referenced on Ofqual page only | New GCSE specifications are expected for first teaching in 2029–2030 (per Ofqual page); content not yet confirmed by DfE. Current blueprint applies to the current specifications only. [V] for existence, [U] for content |

Limitation: absence of a withdrawal banner is not proof of continuing force. A human should confirm against Ofqual's consolidated register before any release.

### A4. Content excluded

- No Edexcel (or other board) specification, sample assessment materials, past papers, mark schemes, examiner reports or third-party websites. None were consulted or recalled.
- I am aware from general knowledge that Edexcel 1MA1 uses three 80-mark papers; this was deliberately **not used** in the blueprint and no Edexcel-specific claim is made.

### A5. Coverage gaps

- Pattern evidence (Phase 2): **none available** (no authorised assessment examples).
- No board-level interpretation of the DfE content, no command-word list, no mark-scheme conventions, no board formula or notation conventions.

---

## B. Specification map (quadratics)

Source: S1, Algebra section (statement numbers are the DfE's own, within the Algebra section); tier areas per S2 ¶15 [V]: **Area 1** = standard font, both tiers; **Area 2** = underlined, both tiers (Higher candidates expected confident and competent); **Area 3** = **bold**, **Higher tier only**.

Method (v0.2): bold read from PDF font data; underlining read from drawn rules in the PDF; every row below was then confirmed by viewing the rendered page images (`evidence/DFE-00233-2013_p5…p7_render.png`). **Formatting is therefore verified [V] for these rows.**

| Ref | Requirement (S1 wording abbreviated) | Area | Higher tier? |
|---|---|---|---|
| Alg 4 | Expand products of **two** binomials | 2 (underlined) | Yes |
| Alg 4 | …expand products of two **or more** binomials ("or more") | 3 (bold) | Higher only |
| Alg 4 | Take out common factors | 1 | Yes |
| Alg 4 | Factorise x² + bx + c, including difference of two squares | 2 (underlined) | Yes |
| Alg 4 | Factorise ax² + bx + c | 3 (bold) | Higher only |
| Alg 5 | Rearrange formulae to change the subject | 1 | Yes |
| Alg 6 | Know equation vs identity; argue to show expressions equivalent; use algebra to support and construct arguments | 2 (underlined) | Yes |
| Alg 6 | …"and proofs" | 3 (bold) | Higher only (consistent with S3 AO2 4b) |
| Alg 11 | Identify and interpret roots, intercepts, turning points of quadratic functions graphically; deduce roots algebraically | 2 (underlined) | Yes |
| Alg 11 | …and turning points by completing the square | 3 (bold) | Higher only |
| Alg 17 | Solve linear equations (incl. unknown on both sides) | 1/2 | Yes (prerequisite) |
| Alg 18 | Solve quadratic equations algebraically by factorising | 2 (underlined) | Yes |
| Alg 18 | …(including those that require rearrangement) | 3 (bold) | Higher only |
| Alg 18 | …by completing the square and by using the quadratic formula | 3 (bold) | Higher only |
| Alg 18 | …find approximate solutions using a graph | 2 (underlined) | Yes |
| Alg 19 | Simultaneous equations: linear/linear (underlined); **linear/quadratic** (bold) | 2 / 3 | Adjacent topic, out of scope |
| Alg 21 | Translate situations into expressions/formulae; derive an equation (or two simultaneous equations), solve and interpret | 2 (underlined) | Yes |
| Alg 22 | Quadratic inequalities in one variable (and "one or two variable(s)") | 3 (bold) | Higher only; out of scope |
| Num 7/8 | Calculate exactly with surds | 3 (bold) | Higher only |
| Num 8 | …and multiples of π | 2 (underlined) | Yes |
| Num 8 | Simplify surd expressions; rationalise denominators | 3 (bold) | Higher only |
| Num 15 | Round to specified dp / sf; inequality notation for error intervals (underlined part) | 1 / 2 | Yes |
| App 1 (S1) | Quadratic formula x = (−b ± √(b² − 4ac)) / 2a is a formula candidates are "expected to know" and which "must not be given in the assessment" | n/a | **Historical DfE statement; see B2 for current arrangements** |

Rows 4 ("take out common factors"), 5 and 17 were read directly from the rendered page; the rest as above.

### B2. Current examination arrangements — formula sheets (verified 2026-10-30)

**Official sources fetched:**
- Ofqual, *Decisions: proposed changes to the assessment of mathematics, physics and combined science GCSEs* (ref Ofqual/26/7327; page updated 5 May 2026).
- DfE, *GCSE exam support materials: Minister for School Standards writes to Ofqual* (26 Feb 2026).
- Ofqual consultation and decisions on 2025/2026/2027 assessment (gov.uk), and the consultation page Ofqual/26/7302.

**Findings [V] (from the pages, as fetched):**
1. Ofqual "will continue to require exam boards to provide students with formulae and equations sheets" for GCSE maths for the lifetime of the current specifications. The decision relates to exams taken **from 2028 onwards**.
2. For **2025, 2026 and 2027** exams the DfE letter states students "will not need to memorise formulae and equations" and "will continue to be provided with these". Ofqual's earlier decision (2025–27) required boards to publish 2026 and 2027 sheets by 1 September 2025 and provide clean copies with papers. Together these two decisions cover 2025 onward without a gap. [I] on joining them.
3. Boards must publish sheets by 1 September the year before the series, provide clean copies, and "not set questions that can be answered solely by transferring information from the formulae or equations sheets". Sheets must remain consistent with previous years and between specifications.
4. The DfE decision means "it is not necessary for students to memorise formulae for GCSE mathematics".
5. Retained separately: DfE S1 Appendix 1 (2013) still says candidates are expected to know the quadratic formula and it must not be given. The two are in tension; for current examinations the Ofqual/DfE 2026 position governs provision of the sheet. S1 remains the source for which content is in scope, not for whether the formula is printed.

**Not verified [U]:**
- The Ofqual pages do not list the sheet's contents, so **that the quadratic formula appears on the 2027 Higher sheet is not confirmed by an official Ofqual source.** The 2025–27 decision says the support materials "set out the formulae and equations that students must memorise in a normal year", which [I] covers the quadratic formula in S1 Appendix 1.
- I did **not** open any exam-board formula sheet. AQA's policy prohibits putting AQA material into AI tools and Pearson's AI position is unresolved. A search-result snippet reported an AQA 2024 Higher sheet containing a quadratic formula section; this was not ingested and is not relied on.
- A teacher should confirm against the board-published 2027 Higher formulae sheet (read by a human) whether the quadratic formula is printed and in what form.
- Whether separate Foundation and Higher sheets exist for 2027 is not established from official sources.

**Consequences for generation and marking:**
- Treat the quadratic formula as **available to the student** in practice questions (parameter of the exam, not of S1's historical statement). Do not require it to be memorised.
- Mark schemes must credit **substitution and evaluation**, not mere recall or copying. A question must not be answerable solely by transferring from the sheet.
- Completing the square, factorising and surd simplification are **not** formula-sheet items [I] and must still be performed by the student.
- Questions must not print the formula in the question text unless a teacher decides to simulate the sheet.

### Prerequisite relationships — **[I]**

S1 does not list prerequisites. The following are inferred from the content statements and must be confirmed by the reviewer:
- Solving by factorising ← factorising quadratics (Alg 4), solving linear equations (Alg 17), zero-product reasoning (not stated in S1).
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
| (Historical DfE statement: quadratic formula to be known and not given.) Current examinations: formulae sheets provided; see B2. | S1 Appendix 1 [V] / Ofqual 2026 [V] |

### C3. AO interpretations relevant to quadratics (S3)

- **AO1** (Higher 40%): strand 3a/3b (routine procedures / multi-step set tasks) must be at least 80% of AO1 marks; at Higher there should be more 3b than 3a. Routine procedure = procedure made clear by the task, no significant context, familiar from the spec. Recall (strand 1) and notation (strand 2) are each at most 10% of AO1 marks. [V]
- **AO1 attribution rule:** where an AO2/AO3 task resolves into a routine procedure and marks are given for carrying it out accurately, those marks belong to AO1. [V] (S3 AO3 notes, AO1 3b note.)
- **AO2** (Higher 30%): deduce/infer, chains of reasoning to a **given** result, interpret/communicate, present arguments and proofs, assess validity. Proof is Higher-only. [V]
- **AO3** (Higher 30%): translate problems (mathematical or non-mathematical contexts, single process or series of processes), connections, interpret results in context, evaluate methods/results, evaluate assumptions. Tasks should not make the procedure clear; at least one-third of AO3 marks should come from tasks addressing two or more AO3 strands; greater emphasis on strands 1–3 than 4–5, and within strand 1 on multi-step (1b, 1d). Answers should be framed in the original problem, not in the abstract. [V]
- The same-topic question can be written at different AOs: factorise-and-solve (AO1), "show that" a quadratic follows from a context (AO2 given-result chain), a real-world area/projectile/cost problem requiring the learner to form and solve a quadratic (AO3). **[I]**

---

## D. Topic-specific question blueprint (for the Question Generator)

Everything in D is a Serapis design proposal grounded in S1–S3; items tagged [A] are not evidenced and are for teacher review.

### D0. Evidence classes used in this section (v0.2)

| Class | What belongs here | Examples |
|---|---|---|
| **Sourced requirement [V]** | Stated in S1–S3 or the 2026 Ofqual/DfE pages | Tier areas of each skill (B); AO weightings and AO3 emphasis (C3); 33–50% non-calculator rule (S2); grade 4–6 / 7–9 mark split per assessment (S2); formulae sheets continue (B2) |
| **Inferred [I]** | Analyst reasoning from sourced text | Prerequisite links; which question formats fit which AO; which methods suit non-calculator work; item-level grade bands (D2) |
| **Assumed [A]** | Serapis design choice, no source | Mark totals per format; M/A/B-style notation; hypothesised misconceptions (D1); mix guidance (D3) |
| **Board-specific [U]** | Needs authorised board evidence | Command words, mark-scheme conventions, frequency, difficulty calibration, sheet contents. **Nothing in this blueprint is attributed to Edexcel.** |

### D1. Topic profile

- **Topic:** Algebra → Solving equations → Quadratic equations (S1 Alg 18), with Alg 4 factorising, Alg 11 completing-the-square link, Alg 21 modelling.
- **Learning objectives (derived from S1):**
  - LO-Q1: Factorise quadratic expressions x² + bx + c, including difference of two squares (Alg 4). Area 2, both tiers.
  - LO-Q2: Factorise ax² + bx + c, a ≠ 1 (Alg 4). Area 3, Higher only.
  - LO-Q3: Solve quadratic equations by factorising (Alg 18, Area 2). Variants needing rearrangement to ax² + bx + c = 0 are bold in S1 so Higher-only (Alg 18); equations already in standard form (Alg 18 factorising) are Area 2.
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
2. **Tier gate:** every skill used is Area 1–3 content assessable at Higher; no content outside the selected specification and tier; the question does not reduce to transferring information from the formulae sheet (Ofqual 2026 decision, B2).
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
| E1 | Solving quadratics by factorising is underlined (Area 2); the rearrangement parenthetical is bold (Area 3); graph solutions underlined | S1 Alg 18, visual inspection p7 | [V] |
| E2 | Completing the square and quadratic formula are bold, so Higher-only | S1 Alg 18; S2 ¶15 Area 3 | [V] |
| E3 | Factorising ax² + bx + c is bold, so Higher-only | S1 Alg 4; S2 ¶15 | [V] |
| E4 | S1 Appendix 1 states the quadratic formula must be known and not given (historical). Current exams: formulae sheets continue (decision updated 5 May 2026; DfE letter 26 Feb 2026) | S1 App.1; Ofqual/26/7327; DfE letter | [V]; whether the Higher sheet prints the quadratic formula: [U] |
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

1. ~~Underlining not machine-detectable~~ **Resolved in v0.2** by visual inspection and drawn-rule extraction of S1 pp5–7. Residual: Num 4/5 rows outside the quadratics scope were not individually cross-checked.
2. **Currency of S1–S3** checked (A3): no withdrawal notices found, but not proof of continuing force; the July 2026 qualification-level conditions revision was not reviewed; first teaching of replacement specifications is expected 2029–30.
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
  "marking_principles": ["S3: routine-procedure marks are AO1", "S3: AO3 working usually shown; partial credit rules stated in scheme", "Formulae sheets are provided in current exams (Ofqual 2026 decision); credit substitution and evaluation, not recall; no question answerable solely by copying from the sheet", "Serapis-style M/A/B notation is internal, not board-faithful"],
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
