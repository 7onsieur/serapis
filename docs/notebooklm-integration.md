# NotebookLM workflow

Serapis does not automate NotebookLM and has no unofficial integration with it. You export a file and upload it yourself.

## Export

In the Hub open a week and use **Export your study material → Download NotebookLM file (.md)**. The file is built from your local record at the moment you download it, so download again after adding reflections or answers; no AI call is made and nothing is written. (The CLI `serapis workspace` / `after-lecture` / `teach` commands also refresh a copy in the workspace folder.)

Then add the file as a source in NotebookLM using its own interface and replace it when you export a newer one. Check NotebookLM's help for current supported formats.

## What the file contains

Sections for orientation, core concepts, your reflections, open questions, taught topics, practice questions (questions only), revision priorities, assessment connections and a source guide. Every section heading and every student or AI line carries a label, because NotebookLM splits sources into passages:

- **University source** – cited with source name, ID and page or slide. Preparation summaries are AI-written from those sources but each claim cites them.
- **Student-reported** – your own notes, questions and confusions; unverified. Assessment remarks are additionally marked as not a confirmed deadline, weighting or requirement.
- **AI-generated study aid** – TEACH explanations and questions; not a source and not proof of mastery.

Excluded: quiz reference answers, the text of your own answers, credentials, prompts, provider and cache details, file paths. All free text is escaped so notes cannot add headings, links or HTML.

## Boundary

NotebookLM conversations and generated material are study aids. They are never imported into Serapis as evidence (the Hub accepts only PDF and PowerPoint materials). Check claims against the cited sources.
