# SERAPIS-LE-EIE-01 — 12-question exploratory pilot (candidate questions)

Status: **DRAFT candidates for teacher review. Not for student release. Not official, past or predicted exam-board questions.** Tier-aligned to DfE/Ofqual requirements only; no Edexcel fidelity is claimed.
Contains public sector information licensed under the Open Government Licence v3.0 (DfE/Ofqual requirement statements referenced).

Evidence tags: **[V]** sourced, **[I]** inferred, **[A]** Serapis assumption. Difficulty bands are hypotheses. The marking notation (M/A/B) is a **Serapis-internal convention, not Edexcel's**. The quadratic formula is expected to be on the formulae sheet (blueprint v0.2 section B2; sheet contents unverified from a board source).

Set totals: 45 marks. Questions are a pilot set, not a paper; paper-level rules (AO weights, calculator split, grade split) are not targeted.

| ID | Title | Marks | Calc | AO (intended) | Difficulty hypothesis [I] | Generation | Symbolic check | Blind solve |
|---|---|---|---|---|---|---|---|---|
| Q01 | Factorise then solve (a=1) | 3 | non-calculator | AO1 (3a routine procedure) | grade 4-5 [I] | root-first: roots 9 and -2 chosen, then expanded | PASS | answers agree |
| Q02 | Solve after rearranging (a=1) | 3 | non-calculator | AO1 (3a/3b) | grade 5 [I] | root-first: roots 3 and -10, equation presented unrearranged | PASS | answers agree |
| Q03 | Factorise and solve (a>1) | 3 | non-calculator | AO1 (3b multi-step) | grade 6 [I] | root-first with rational roots 4/3 and -5/2 | PASS | answers agree |
| Q04 | Quadratic formula, exact answer | 3 | non-calculator | AO1 (3b) | grade 6 [I] | coefficient-first: discriminant 57 chosen non-square so no integer factorisation exists | PASS | answers agree |
| Q05 | Quadratic formula, rounded | 3 | calculator | AO1 (3b) | grade 5-6 [I] | coefficient-first: discriminant 40 | PASS | answers agree |
| Q06 | Expand, rearrange, formula (non-factorisable) | 4 | calculator | AO1 (3b multi-step) | grade 6-7 [I] | coefficient-first: equation presented in unrearranged form; discriminant 136 non-square | PASS | answers agree |
| Q07 | Complete the square then solve exactly | 4 | non-calculator | AO1 (3b); AO2 link between parts | grade 7 [I] | coefficient-first: x²+10x−3; discriminant-style value 28 not a perfect square | PASS | answers agree |
| Q08 | Completing the square, a>1, turning point | 4 | non-calculator | AO1 (3b) | grade 7 [I] | coefficient-first | PASS | answers agree |
| Q09 | Rectangle: form, solve, reject, use | 6 | either | (a) AO2 (chain to given result); (b)-(c) AO3 strands 1b, 3, 4b with AO1 for routine solve | grade 7 [I] | context first, then verified: roots 11/2 and -7 (non-integer positive root) | PASS | answers agree |
| Q10 | Right-angled triangle, formula, not factorisable | 5 | calculator | (a) AO2; (b) AO3 with AO1 | grade 7-8 [I] | context first; discriminant 632 non-square | PASS | answers agree |
| Q11 | Projectile height, formula | 4 | calculator | AO3 (strands 1b, 3) with AO1 for routine solve | grade 7 [I] | context first; coefficients not designed for integer roots | PASS | answers agree |
| Q12 | Prove no real solutions / always positive | 3 | non-calculator | AO2 (4b proof; Higher only per Ofqual guidance) | grade 8 [I] | coefficient-first: x² − 6x + 10 → (x − 3)² + 1 | PASS | answers agree |

## Q01 — Factorise then solve (a=1)

**Skills and evidence:**
- LO-Q1: DfE Alg 4 factorising x²+bx+c — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]
- LO-Q3: DfE Alg 18 solve by factorising — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3a routine procedure)  
**Difficulty hypothesis:** grade 4-5 [I]  
**Provisional marks:** 3  
**Calculator:** non-calculator  
**Generation approach:** root-first: roots 9 and -2 chosen, then expanded

**Question**

```text
(a) Factorise x² − 7x − 18  [2 marks]
(b) Hence solve x² − 7x − 18 = 0  [1 mark]
```

**Worked solution**

```text
(a) Need two numbers with product −18 and sum −7: −9 and +2. x² − 7x − 18 = (x − 9)(x + 2).
(b) (x − 9)(x + 2) = 0, so x = 9 or x = −2.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- (a) M1 for a correct attempt: (x ± p)(x ± q) with pq = −18 or p + q = ±7; A1 for (x − 9)(x + 2).
- (b) B1 for x = 9 and x = −2 (follow-through from their factors in (a) if both factors are linear).
- Accept answer to (b) without working if both values correct.

**Independent mathematical verification**
- Symbolic: all 3 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Easiest item; may be below Higher-tier targeting on its own. Intended as a both-tiers prerequisite check.

## Q02 — Solve after rearranging (a=1)

**Skills and evidence:**
- LO-Q3: DfE Alg 18 solve by factorising incl. rearrangement — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- LO-Q1: DfE Alg 4 factorising x²+bx+c — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3a/3b)  
**Difficulty hypothesis:** grade 5 [I]  
**Provisional marks:** 3  
**Calculator:** non-calculator  
**Generation approach:** root-first: roots 3 and -10, equation presented unrearranged

**Question**

```text
Solve x² + 7x = 30  [3 marks]
```

**Worked solution**

```text
x² + 7x − 30 = 0. Numbers with product −30 and sum 7: 10 and −3. (x + 10)(x − 3) = 0, so x = −10 or x = 3.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- M1 for rearranging to x² + 7x − 30 = 0 (may be implied by correct factors).
- M1 for a correct attempt to factorise: (x ± p)(x ± q) with pq = −30 or p + q = ±7.
- A1 for x = −10 and x = 3.
- Both roots stated without working: teacher to decide whether this earns full marks (not specified by the sources).

**Independent mathematical verification**
- Symbolic: all 2 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
The 'rearrangement' element is bold (Higher-only) in the DfE text; the factorising itself is Area 2.

## Q03 — Factorise and solve (a>1)

**Skills and evidence:**
- LO-Q2: DfE Alg 4 factorising ax²+bx+c — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- LO-Q3: DfE Alg 18 solve by factorising — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3b multi-step)  
**Difficulty hypothesis:** grade 6 [I]  
**Provisional marks:** 3  
**Calculator:** non-calculator  
**Generation approach:** root-first with rational roots 4/3 and -5/2

**Question**

```text
Solve 6x² + 7x − 20 = 0  [3 marks]
```

**Worked solution**

```text
6x² + 7x − 20 = (3x − 4)(2x + 5) (check: 6x² + 15x − 8x − 20). So x = 4/3 or x = −5/2.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- M1 for a correct attempt to factorise: (3x ± p)(2x ± q) or (6x ± p)(x ± q) with pq = ±20, or use of the quadratic formula with correct substitution.
- A1 for (3x − 4)(2x + 5), or for a fully correct formula substitution.
- A1 for x = 4/3 (or 1⅓) and x = −5/2 (or −2.5). Decimal approximations of 4/3 lose the final A mark.

**Independent mathematical verification**
- Symbolic: all 3 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Alternative valid method: quadratic formula (discriminant 529 = 23²). Mark scheme must accept it.

## Q04 — Quadratic formula, exact answer

**Skills and evidence:**
- LO-Q4: DfE Alg 18 quadratic formula — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- NUM-SURD: DfE Num 8 exact surds — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3b)  
**Difficulty hypothesis:** grade 6 [I]  
**Provisional marks:** 3  
**Calculator:** non-calculator  
**Generation approach:** coefficient-first: discriminant 57 chosen non-square so no integer factorisation exists

**Question**

```text
Solve 2x² + 5x − 4 = 0
Give your solutions in the form (p ± √q)/r where p, q and r are integers.  [3 marks]
```

**Worked solution**

```text
a = 2, b = 5, c = −4. b² − 4ac = 25 + 32 = 57. x = (−5 ± √57)/4.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- M1 for correct substitution into the quadratic formula (the formula is expected to be on the formulae sheet; see blueprint v0.2).
- M1 for evaluating the discriminant as 57 (accept unsimplified 25 − 4×2×(−4)).
- A1 for (−5 ± √57)/4 or equivalent with p = −5, q = 57, r = 4.
- Decimal answers only (−3.14, 0.64): max M1 M1 A0.

**Independent mathematical verification**
- Symbolic: all 3 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Whether the board sheet supplies the formula (and its exact presentation) is not verified from a board source; teacher to confirm. Mark scheme must not give credit for merely copying the formula from the sheet.

## Q05 — Quadratic formula, rounded

**Skills and evidence:**
- LO-Q4: DfE Alg 18 quadratic formula — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- NUM-ROUND: DfE Num 15 rounding — Area 1 (standard font) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3b)  
**Difficulty hypothesis:** grade 5-6 [I]  
**Provisional marks:** 3  
**Calculator:** calculator  
**Generation approach:** coefficient-first: discriminant 40

**Question**

```text
Solve 3x² − 8x + 2 = 0
Give your solutions correct to 2 decimal places.  [3 marks]
```

**Worked solution**

```text
a = 3, b = −8, c = 2. b² − 4ac = 64 − 24 = 40. x = (8 ± √40)/6 = 2.3874… or 0.2792…  So x = 2.39 or x = 0.28.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- M1 for correct substitution into the quadratic formula.
- M1 for a correct simplified or evaluated discriminant (40) or one correct unrounded value.
- A1 for 2.39 and 0.28 (both required).
- Answers given to a different accuracy: A0 unless the unrounded values are shown and the rounding slip is the only error (teacher decision).

**Independent mathematical verification**
- Symbolic: all 1 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Calculator-dependent items need a stated calculator policy per question.

## Q06 — Expand, rearrange, formula (non-factorisable)

**Skills and evidence:**
- LO-Q4: DfE Alg 18 quadratic formula incl. rearrangement — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- ALG-EXP: DfE Alg 4 expanding two binomials — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]
- NUM-ROUND: DfE Num 15 rounding — Area 1 (standard font) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3b multi-step)  
**Difficulty hypothesis:** grade 6-7 [I]  
**Provisional marks:** 4  
**Calculator:** calculator  
**Generation approach:** coefficient-first: equation presented in unrearranged form; discriminant 136 non-square

**Question**

```text
Solve (2x − 1)(x + 4) = 3x + 11
Give your solutions correct to 3 significant figures.  [4 marks]
```

**Worked solution**

```text
(2x − 1)(x + 4) = 2x² + 7x − 4. So 2x² + 7x − 4 = 3x + 11, i.e. 2x² + 4x − 15 = 0. b² − 4ac = 16 + 120 = 136. x = (−4 ± √136)/4 = 1.9154… or −3.9154… So x = 1.92 or x = −3.92.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- M1 for expanding to 2x² + 7x − 4 (at most one sign or term error).
- M1 for rearranging to a three-term quadratic = 0, e.g. 2x² + 4x − 15 = 0.
- M1 for substitution into the quadratic formula using their a, b, c.
- A1 for 1.92 and −3.92 (both).
- Follow-through on the final M1 and A1 only if their quadratic is still three-term with a ≠ 0.

**Independent mathematical verification**
- Symbolic: all 3 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Not solvable by integer factorisation (discriminant 136). Mark scheme must say how many significant figures an unrounded -3.9154 earns.

## Q07 — Complete the square then solve exactly

**Skills and evidence:**
- LO-Q5: DfE Alg 18 completing the square — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- NUM-SURD: DfE Num 8 surds — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3b); AO2 link between parts  
**Difficulty hypothesis:** grade 7 [I]  
**Provisional marks:** 4  
**Calculator:** non-calculator  
**Generation approach:** coefficient-first: x²+10x−3; discriminant-style value 28 not a perfect square

**Question**

```text
(a) Write x² + 10x − 3 in the form (x + a)² + b  [2 marks]
(b) Hence solve x² + 10x − 3 = 0
    Give your solutions in the form p ± q√r, where p, q and r are integers and r is as small as possible.  [2 marks]
```

**Worked solution**

```text
(a) x² + 10x − 3 = (x + 5)² − 25 − 3 = (x + 5)² − 28.
(b) (x + 5)² = 28, x + 5 = ±√28 = ±2√7. x = −5 ± 2√7.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- (a) M1 for (x + 5)² seen; A1 for (x + 5)² − 28.
- (b) M1 for (x + 5)² = 28 (or follow-through from (a)) and square root of both sides with ±; A1 for −5 ± 2√7.
- Follow-through from an incorrect (a) for the M1 only.
- −5 ± √28: A0 (simplest-surd condition not met).

**Independent mathematical verification**
- Symbolic: all 3 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Part (b) 'r as small as possible' needs teacher check for clarity.

## Q08 — Completing the square, a>1, turning point

**Skills and evidence:**
- LO-Q5: DfE Alg 11 turning points by completing the square — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO1 (3b)  
**Difficulty hypothesis:** grade 7 [I]  
**Provisional marks:** 4  
**Calculator:** non-calculator  
**Generation approach:** coefficient-first

**Question**

```text
(a) Write 2x² − 12x + 7 in the form a(x + p)² + q  [3 marks]
(b) Write down the coordinates of the minimum point of the curve y = 2x² − 12x + 7  [1 mark]
```

**Worked solution**

```text
(a) 2x² − 12x + 7 = 2(x² − 6x) + 7 = 2[(x − 3)² − 9] + 7 = 2(x − 3)² − 18 + 7 = 2(x − 3)² − 11.
(b) Minimum at x = 3 (the squared term is zero), y = −11: (3, −11).
```

**Proposed marking guidance (Serapis-style, internal convention)**

- (a) M1 for factoring out 2 and (x − 3)² seen; M1 for 2(x − 3)² − 18 + 7 or equivalent; A1 for 2(x − 3)² − 11 (a = 2, p = −3, q = −11).
- (b) B1 for (3, −11) (follow-through from (a) where the form is a(x + p)² + q with a > 0).

**Independent mathematical verification**
- Symbolic: all 4 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Turning-point reading assumes students link completed square to vertex; 'minimum' is justified by a > 0, which is not asked for.

## Q09 — Rectangle: form, solve, reject, use

**Skills and evidence:**
- LO-Q6: DfE Alg 21 form and solve in context — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]
- LO-Q3: DfE Alg 18 solve — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]
- LO-Q2: DfE Alg 4 ax²+bx+c factorising (if factorising used) — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** (a) AO2 (chain to given result); (b)-(c) AO3 strands 1b, 3, 4b with AO1 for routine solve  
**Difficulty hypothesis:** grade 7 [I]  
**Provisional marks:** 6  
**Calculator:** either  
**Generation approach:** context first, then verified: roots 11/2 and -7 (non-integer positive root)

**Question**

```text
A rectangular garden has width w metres. Its length is (2w + 3) metres. The area of the garden is 77 m².
(a) Show that 2w² + 3w − 77 = 0  [2 marks]
(b) Work out the width of the garden.  [3 marks]
(c) Work out the perimeter of the garden.  [1 mark]
```

**Worked solution**

```text
(a) w(2w + 3) = 77, so 2w² + 3w = 77, so 2w² + 3w − 77 = 0.
(b) 2w² + 3w − 77 = (2w − 11)(w + 7) = 0 (or use the formula: disc = 9 + 616 = 625 = 25²). w = 11/2 = 5.5 or w = −7. A width cannot be negative so w = 5.5 m.
(c) Length = 2 × 5.5 + 3 = 14 m. Perimeter = 2(5.5 + 14) = 39 m.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- (a) M1 for w(2w + 3) = 77; A1 for expanding and rearranging to the given result with no errors.
- (b) M1 for a correct attempt to solve (factorise or formula); A1 for w = 5.5 and w = −7; B1 (or A1) for rejecting −7 with a reason (length cannot be negative) and stating 5.5 m.
- (c) B1 for 39 (follow-through using their positive width if valid).
- AO attribution: the solve in (b) is routine procedure so credited AO1; interpretation/rejection credited AO3 (S3 notes).

**Independent mathematical verification**
- Symbolic: all 5 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Combined AO2/AO3 marks; teacher to confirm AO split. Could be written without 'Show that' in an alternative AO3-only version.

## Q10 — Right-angled triangle, formula, not factorisable

**Skills and evidence:**
- LO-Q6: DfE Alg 21 context — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]
- LO-Q4: DfE Alg 18 formula — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- GEO-PYTH: DfE Appendix Pythagoras — formula [V for tier area; skill mapping is analyst judgement]

**Intended AO:** (a) AO2; (b) AO3 with AO1  
**Difficulty hypothesis:** grade 7-8 [I]  
**Provisional marks:** 5  
**Calculator:** calculator  
**Generation approach:** context first; discriminant 632 non-square

**Question**

```text
The diagram shows a right-angled triangle. The two shorter sides have lengths x cm and (x + 2) cm. The hypotenuse is 9 cm.
[Diagram: right angle at bottom-left; vertical side x, horizontal side x + 2, hypotenuse 9. Not drawn accurately.]
(a) Show that 2x² + 4x − 77 = 0  [2 marks]
(b) Work out the value of x. Give your answer correct to 3 significant figures.  [3 marks]
```

**Worked solution**

```text
(a) By Pythagoras x² + (x + 2)² = 9². x² + x² + 4x + 4 = 81. 2x² + 4x − 77 = 0.
(b) a = 2, b = 4, c = −77. disc = 16 + 616 = 632. x = (−4 ± √632)/4 = 5.2849… or −7.2849… x is a length so x = 5.28 cm.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- (a) M1 for x² + (x + 2)² = 81 (or 9²); A1 for expanding and simplifying to the given result with no errors.
- (b) M1 for correct substitution into the quadratic formula; A1 for 5.28 (3 sf); B1 for rejecting the negative root (−7.28) or stating x must be positive.
- Do not accept the unrounded 5.2849… for the A mark.

**Independent mathematical verification**
- Symbolic: all 5 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Needs an accurate diagram in production; the pilot uses a text description only. The word 'diagram' must not appear without one.

## Q11 — Projectile height, formula

**Skills and evidence:**
- LO-Q6: DfE Alg 21 context — Area 2 (underlined in DfE source: assessed at both tiers; Higher candidates expected confident) [V for tier area; skill mapping is analyst judgement]
- LO-Q4: DfE Alg 18 formula — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- NUM-ROUND: DfE Num 15 — Area 1 (standard font) [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO3 (strands 1b, 3) with AO1 for routine solve  
**Difficulty hypothesis:** grade 7 [I]  
**Provisional marks:** 4  
**Calculator:** calculator  
**Generation approach:** context first; coefficients not designed for integer roots

**Question**

```text
A ball is thrown upwards. Its height, h metres, above the ground after t seconds is given by
h = 1.5 + 12t − 4.9t²
Work out the time the ball takes to hit the ground.
Give your answer in seconds correct to 2 decimal places.  [4 marks]
```

**Worked solution**

```text
The ball hits the ground when h = 0. 4.9t² − 12t − 1.5 = 0. a = 4.9, b = −12, c = −1.5. disc = 144 + 29.4 = 173.4. t = (12 ± √173.4)/9.8 = 2.5682… or −0.1192… Time cannot be negative so t = 2.57 s.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- M1 for h = 0 and a correct equation, e.g. 1.5 + 12t − 4.9t² = 0 (accept 4.9t² − 12t − 1.5 = 0).
- M1 for correct substitution into the quadratic formula (signs of a, b, c consistent).
- A1 for t = 2.57 (2.5682… seen or implied) .
- B1 for rejecting the negative root with a reason.

**Independent mathematical verification**
- Symbolic: all 4 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Contextual model (g ≈ 9.8) is a simplification; the question does not ask students to critique it. The root −0.12 s has no physical meaning in the model's domain: wording relies on students inferring t ≥ 0.

## Q12 — Prove no real solutions / always positive

**Skills and evidence:**
- LO-Q5: DfE Alg 18 / Alg 11 completing the square — Area 3 (bold in DfE source: Higher tier only) [V for tier area; skill mapping is analyst judgement]
- ALG-PROOF: DfE Alg 6 proof — A3 (bold 'and proofs') [V for tier area; skill mapping is analyst judgement]

**Intended AO:** AO2 (4b proof; Higher only per Ofqual guidance)  
**Difficulty hypothesis:** grade 8 [I]  
**Provisional marks:** 3  
**Calculator:** non-calculator  
**Generation approach:** coefficient-first: x² − 6x + 10 → (x − 3)² + 1

**Question**

```text
Show that x² − 6x + 10 is greater than 0 for all values of x.  [3 marks]
```

**Worked solution**

```text
x² − 6x + 10 = (x − 3)² − 9 + 10 = (x − 3)² + 1. For any real x, (x − 3)² ≥ 0, so (x − 3)² + 1 ≥ 1 > 0.
```

**Proposed marking guidance (Serapis-style, internal convention)**

- M1 for (x − 3)² seen; A1 for (x − 3)² + 1.
- B1 for a statement that a squared real number is ≥ 0 (or never negative) and a conclusion that the expression is ≥ 1 or > 0 for all x.
- Conclusion via discriminant (b² − 4ac = −4 < 0 and a > 0): award full marks if both conditions stated (alternative valid method; the item is not claimed to require completing the square).

**Independent mathematical verification**
- Symbolic: all 3 checks passed (`verify_pilot.py`; details in `verification_results.json`).
- Blind solve (separate model context, no solutions supplied): final answers agree. See `verification-report.md` for caveats.

**Ambiguity / limitations**
Alternative discriminant proof is acceptable but changes which skill is evidenced. Teacher decision whether to prescribe 'by completing the square'.
