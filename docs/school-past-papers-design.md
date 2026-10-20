# Design: School track + generated past papers

Status: draft for review. Nothing in this document is implemented yet.

## 1. Goal

Extend Serapis to lower-education students (GCSE / A-Level) with a second,
parallel offering: a locally-usable academic assistant **plus** a steady
supply of original, exam-style practice papers, refreshed on a cadence
(initially monthly), covering a student's subject/exam-board/spec.

This is explicitly **not** real exam-board past papers. Those are
copyrighted by AQA/Edexcel/OCR/WJEC/CCEA and we will not host, redistribute,
or reproduce them. "Past papers" here means **original practice papers
written in the style and structure of a real spec's assessment** (question
types, command words, mark allocations, paper length) — the same thing a
tutor or workbook publisher produces, not a leaked or scanned real paper.

## 2. Non-goals (this phase)

- No per-student, on-demand AI generation of papers. The answer to "how is
  monthly content produced" was explicitly: centrally, on our side, because
  per-student generation cost doesn't scale. Generation is a Serapis-side
  content pipeline, not a client-side OpenAI call.
- No scraping or hosting of real exam board material.
- No change to the existing university module/week model, Blackboard
  integration, or Drive integration — those stay untouched. Per `AGENTS.md`,
  this is additive and kept separate, not a rework of the university path.

## 3. Terminology / data model

Serapis today models study life as **university → module → week**, with
assessments and sources hung off a week (`state.py`, `sources.py`,
`workflows.py`). That shape doesn't fit school: there's no "module", and a
GCSE/A-Level student thinks in **subject + exam board + spec + topic/unit**,
across **year groups** (e.g. "Year 11", "Year 13") rather than semesters.

Proposal: a new, parallel **school profile**, alongside (not replacing) the
existing university profile:

```
SchoolProfile
  level: "GCSE" | "A-Level"
  year_group: str                 # "Year 10", "Year 13", etc.
  subjects: list[SchoolSubject]

SchoolSubject
  subject: str                    # "Mathematics", "Biology", ...
  exam_board: str                 # "AQA" | "Edexcel" | "OCR" | "WJEC" | "CCEA" | "Other"
  spec_code: str | None           # optional, e.g. "8300" for AQA Maths
  topics: list[str]               # spec topic list, student- or template-seeded
```

A student picks one profile (university *or* school) at setup; the two are
mutually exclusive in a given workspace, matching how `student_setup.py`
already gates on a single academic identity.

## 4. Past papers as a new source origin

Sources today (`sources.py`) are always student-supplied (PDF/PPTX,
uploaded or pulled from Blackboard/Drive). Past papers are different: they
are **Serapis-authored content**, not student material. Rather than
stretch the existing provenance model, add a new `origin`:

```
origin: "student_upload" | "blackboard" | "drive" | "practice_pack"
```

A `practice_pack` source additionally carries:

```
pack_id: str            # stable id for this generated paper
subject: str
exam_board: str
topic: str | list[str]
paper_type: "full_paper" | "topic_set"
released: date           # when this pack was published
mark_scheme_source_id: str | None   # paired mark scheme, if included
```

These slot into the existing evidence/provenance language: a practice pack
is `CONFIRMED` as *to what it is* (an original Serapis practice paper) but
is explicitly never treated as equivalent to a real board paper, and must
say so in the Hub UI — this avoids a student mistaking it for the genuine
article when deciding what to revise from.

## 5. Content pipeline (outside this repo's runtime)

Generation happens on Serapis's side, not the student's device:

1. An internal tool (could live in a separate maintainers-only repo, or a
   `tools/` script here that is never invoked by the shipped CLI) produces
   a batch of practice papers per subject/board/topic, using whatever model
   and review process we choose, amortised across all users rather than
   billed per student.
2. Each batch is reviewed (even lightly) before release, given it's
   curriculum-facing content going to school-age students.
3. The batch is packaged as a versioned **manifest** plus paper files
   (PDF or structured JSON question sets — JSON is more useful, since it
   lets the client render a paper, auto-mark short-answer formats, and feed
   questions into QUIZ/REVISE-style workflows instead of being an opaque PDF).

## 6. Distribution and client sync

Students' machines don't run the generator; they pull finished packs.

- A manifest (e.g. `manifest.json`) lists available packs: id, subject,
  board, topic, released date, checksum, download URL.
- A new CLI surface, e.g. `serapis papers sync`, fetches the manifest,
  diffs against what's already in the local workspace
  (`SERAPIS_HOME/papers/`), and downloads only new/updated packs.
- This is pull-based and explicit, matching the project's existing
  "ordinary Hub views don't call out; AI actions are explicit" stance (see
  README's "Local data, AI calls and integrations" section) — sync is a
  student-triggered or Hub-surfaced action, not a silent background job,
  since (per your answer) this isn't meant to be a local scheduled task.
- The Hub can show a badge ("3 new practice papers for Biology (AQA)")
  next time it's opened, rather than Serapis polling in the background.

## 7. Workflow integration

Two ways a synced pack becomes useful, both reusing existing machinery
rather than inventing new AI workflows:

- **As a source**: a practice pack can be attached to a school subject the
  same way a PDF is attached to a module/week, so existing bounded,
  source-grounded workflows (`workflows.py`, `tutoring.py`) can reference it
  for TEACH/REVISE-style explanations — "explain Q4" grounded in that exact
  paper's text, not the model's general recollection of the topic.
- **As an evidence loop**: if a pack is structured JSON rather than a flat
  PDF, a student's attempt at a question can feed the same
  save-attempt/evaluate loop materials already use (`tutor_policy.py`),
  so a practice paper contributes to the recall/explanation/application
  evidence picture instead of being a dead end.

No new AI workflow category is required initially; "past papers" is a new
*source type* that existing workflows can consume, which keeps the surface
area small for a first slice.

## 8. Open questions before implementation

1. Hosting for the manifest/packs: GitHub Releases on this repo (simple,
   versioned, free, but public) vs. a small external host. Affects whether
   non-released/paid content is possible later.
2. Format: JSON question sets (richer, more work to author) vs. PDF
   (simpler to produce, but inert — no auto-marking, no evidence loop).
3. Licensing/visibility of spec topic lists: AQA/Edexcel/etc. publish specs
   publicly, but we should confirm topic-list reproduction (titles only,
   not their exam content) is comfortably fine before baking them in as
   defaults.
4. How "monthly" maps to a real release cadence per subject — a single
   global drop, or staggered by subject so review load doesn't spike.
5. Whether mark schemes/model answers ship alongside papers in v1, or land
   in a later phase.

## 9. Suggested phasing

1. School profile data model + setup flow (no papers yet).
2. Manifest format + `serapis papers sync` against a hand-built test
   manifest (packs can be stubbed/hand-written at this stage).
3. Hub surface: list synced papers per subject, open/view one.
4. Wire a synced pack in as a `source` so TEACH/REVISE can reference it.
5. Only then: stand up the actual generation pipeline and real content.
