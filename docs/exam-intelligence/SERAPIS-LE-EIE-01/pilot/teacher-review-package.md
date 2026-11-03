# SERAPIS-LE-EIE-01 — teacher-review package

For two independent GCSE Maths teachers (ideally one with Higher-tier examining or marking experience). Files: `pilot-questions.md` (questions, worked solutions, marking guidance), `../blueprint-v0.2.md` (requirements), `teacher_review_sheet.csv` (one row per reviewer per question).

## 1. Procedure

1. Reviewers work **separately** and do not see each other's sheets until both have finished.
2. **Step A (blind):** for each question, read only the question text. Solve it, record your own answer, your estimated grade band (4–9) and marks you would award. Do this **before** reading the worked solution, difficulty hypothesis or marking guidance.
3. **Step B:** read the worked solution and marking guidance, then complete the rubric below.
4. Record a release decision per question: **Accept**, **Revise** (say what) or **Reject** (say why).
5. After both finish, a third person (or the project owner) lists disagreements. Reviewers discuss only items where decisions differ. Record the final outcome and who made it.
6. Please also answer the blueprint questions in section 4.

## 2. Rubric (score 0–2 per criterion unless stated)

Scale: **2** = fully meets; **1** = meets with minor issues (describe); **0** = does not meet. Any 0 in criteria 1–3 means the item cannot be accepted without revision.

| # | Criterion | What to check |
|---|---|---|
| 1 | Mathematical correctness | Question has a determinate answer; worked solution and answers are correct; no hidden errors |
| 2 | Specification and tier alignment | Uses only GCSE Higher content; Higher-only content is genuinely Higher; nothing beyond the specification (e.g. calculus, complex roots) |
| 3 | Clarity and unambiguity | Single reasonable reading; instructions (rounding, exact form, "show that") are clear; diagram description adequate; context is realistic |
| 4 | Assessment objective fit | Intended AO matches what students actually do; routine procedures not mislabelled as problem solving |
| 5 | Mark allocation | Marks match the demonstrable work; part marks sensible; total proportionate |
| 6 | Mark scheme quality | Each mark traceable to work; alternative valid methods accepted; follow-through and rounding rules sufficient; common wrong answers handled |
| 7 | Calculator flag | Appropriate; non-calculator items doable without a calculator in reasonable time |
| 8 | Originality and exam-likeness | Does not reproduce a question you recognise; style is plausible for GCSE Higher without claiming board fidelity |
| 9 | Language and accessibility | Reading level, units, notation and layout suitable for 14–16-year-olds |

Also record (not scored): **your own difficulty estimate** (grade band 4–9, written in Step A); **time to solve**; **estimated facility** (percentage of Higher-tier students you expect to score full marks, rough); **any misconception you actually see in your classes for this item** (this becomes evidence only once teacher-sourced).

## 3. Agreement and decision rules

- With two reviewers and 12 items, compute simple agreement per criterion and on the release decision. Report raw counts, not a statistic that implies precision. A kappa on 12 items is unstable.
- An item is **accepted for pupil trialling** only if both reviewers select Accept, or the discrepancy is resolved and recorded.
- Difficulty hypotheses are **compared** with the reviewers' independent estimates; where reviewers differ by two or more grade bands, the item is flagged for recalibration.

## 4. Blueprint questions for reviewers (from v0.2)

1. Formula sheet: against the board-published 2027 Higher formulae sheet (read by you; do not paste it into AI tools), is the quadratic formula printed and in what form? Do any pilot questions rely on it inappropriately?
2. Tier areas: confirm from the DfE pages that factorising x²+bx+c, expanding two binomials and solving by factorising are underlined (Area 2); and that completing the square, the quadratic formula, rearranged quadratics, ax²+bx+c factorising and surds are bold (Area 3).
3. Are the grade-band hypotheses in `pilot-questions.md` plausible?
4. Which misconceptions do you actually see for each question type?
5. Is it appropriate that Q02 (rearrangement), Q06 and Q12 are treated as Higher-specific?
6. Should Q10's "the value of x" say explicitly that x is positive? Should Q12 prescribe completing the square?
7. Which of the Serapis-style marking conventions (M/A/B) do you use, and what would you change?

## 5. Reviewer record

Reviewer ID (no names required): ____  Years teaching GCSE Maths: ____  Examiner/marker experience (Y/N, board not required): ____  Date: ____  Time spent: ____

Use `teacher_review_sheet.csv`. Keep Step A answers in the `own_answer` column before opening the solutions.
