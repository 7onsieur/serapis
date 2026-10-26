# Lecture-to-revision workflow

PREPARE → attend → **Reflect** → TEACH → QUIZ → REVISE → **Export**, shown on each week page as "Your path this week". A step is marked done only when saved data shows it; attending and revising leave no record and are never marked done.

## Reflect (no AI)

`workflows.after_lecture.captures` in the week's `academic-record.json` holds append-only, dated, student-reported captures (covered, understood, confusing, questions, examples, lecturer emphasis, assessment remarks, own notes). Saving works before any AI preparation: a bare record is created from local state (`prepare_me.status = not_generated`) and a later Prepare fills it in without touching reflections.

Corrections live in `workflows.after_lecture.corrections` (correct, withdraw, mark answered, reopen) with time, reason and previous text. Captures are never edited. Open questions and confusions are mirrored in `learning.unresolved_items`; a corrected item is marked `superseded` and replaced, never deleted. `reflections.py` folds captures and corrections into the current wording.

Limits: identical consecutive saves are refused; entries are capped (8,000 characters, 40 per field).

## Use in later steps

- TEACH with no topic targets the first open question, then confusion, using the current wording.
- REVISE sends bounded, labelled `student_reflections` (open questions, confusions, reported emphasis, unconfirmed assessment remarks) when present; the prompt (`revise-grounding-v3`) forbids treating them as sources or deriving deadlines from them.
- Next-step suggestions mention open reflections without claiming anything about understanding; among valid tasks, those sharing terms with open questions are shown first.
- Reflections never enter `learning.evidence` and never change academic state or assessment facts.

## Exports

`GET /modules/{code}/weeks/{n}/export/study-pack` (.docx) and `.../export/notebooklm` (.md) build from the current record in memory, send `Content-Disposition: attachment`, write nothing and call no model. The Word file is generated without extra dependencies. On-disk copies in the workspace folder are snapshots refreshed by reflection, TEACH and prepare writes; downloads are always current.

## Adapted from University Jarvis

Serapis started from Jarvis, so capture, the canonical record, the hand-built DOCX and the NotebookLM Markdown already existed. This sprint kept those ideas and changed: no-AI reflection with a bare record; append-only corrections; one export model shared by DOCX and Markdown with provenance labels; evidence, priorities and questions (never reference answers) in exports; escaping and XML sanitising; on-demand Hub downloads; reflections feeding REVISE. Jarvis was only read, not modified.
