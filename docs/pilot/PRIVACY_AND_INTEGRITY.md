# Privacy and academic-integrity guidance (pilot)

This is practical guidance for the pilot. It is **not** legal advice, not an institutional policy, and Serapis has no university approval or endorsement.

## What stays on your computer

Your profile, modules, assessments, imported files, study attempts, tutor transcripts and Assignment Coach sessions are stored locally, owner-only, in the Serapis data folder, and kept out of Git. The Hub only answers requests addressed to localhost and rejects cross-site form posts. There is no Serapis server and no analytics.

## What is sent out, and only when you press a button

| Action | Sent to | What |
|---|---|---|
| Prepare, Teach, Quiz, Revise, Tutor turn, evaluate an answer, one-off assignment brief | OpenAI | selected excerpts from your course files for that week or question, assessment details, and (for evaluation/tutoring) your answer |
| Message the Assignment Coach | OpenAI | your message, your plan notes, evidence list and open questions, the requirements and criteria, recent turns, and a few retrieved excerpts from your module's files |
| Everything else (setup, import, plan editing, viewing pages, demo) | nobody | — |

Check your institution's rules on putting course material into third-party AI services **before** using AI buttons, and the provider's terms. Blackboard and Google Drive integrations exist but are **out of scope for the pilot**; do not use them.

## Do not enter

Passwords or API keys in the Hub, other people's personal data, or confidential material you are not allowed to process with AI. Pilot reports must use synthetic or non-sensitive examples.

## Academic integrity: how the Assignment Coach is designed

- You write the assignment. The coach explains the brief, asks questions, points to your course material, suggests what evidence to look for, and (if you tick *sharing my own wording*) comments on your wording against your criteria.
- It refuses requests to write, draft or rewrite assessed text, and attempts to override its rules, **before any AI call** (a keyword-based check). Replies that look like submission text, are too long, or contain a reference found neither in your materials nor in your own text are discarded.
- The plan, evidence and questions are yours. The coach can only *suggest* items, which appear as open/needed until **you** resolve them.
- Requirements and deadlines you or the coach mention are never treated as confirmed; check the official brief.

### How the safeguards work, in layers

1. **Request gate (before any AI call).** Folds invisible and look-alike characters, spacing and line breaks, then refuses clear requests to write, draft, continue, expand, rewrite or hand over assessed text ("sample introduction", "do it all for me", "ignore your rules"). It lets through questions *about* writing, "don't write it", "I'll write it myself" and requests for feedback.
2. **Prompt.** The coach is told to treat your messages, plan, notes and course text as data, never to write submittable text, and never to state dates, weightings or word limits that are not in its context.
3. **Reply checks (after the AI call, before you see anything).** A reply is discarded if it is long, reads like an essay, announces "here is a sample…", quotes text that is not verbatim in your materials or your own text, cites a source or page that was not supplied, names an author/year that appears nowhere in the supplied text, or states a date, percentage, word limit or mark that appears nowhere in the supplied context (so it cannot "establish" a deadline). After two discarded replies a fixed fallback is shown.
4. **Structure.** The coach can only *suggest* questions and evidence; they stay open until you resolve them. It cannot change a requirement's status, mark evidence found, or edit your plan.

### Residual risks (not eliminated, do not rely on these checks alone)

- The request gate is keyword-based. Other languages (beyond a few common verbs), euphemisms, multi-turn set-ups, text hidden in a pasted "draft" or in course files, and creative obfuscation can get through. It also refuses some legitimate requests ("give me an example thesis statement"); rephrase to ask about the idea instead.
- The reply checks cannot tell that a short, well-formed reply *is* usable submission text (a single strong sentence passes), cannot verify that a paraphrase of the course material is accurate, and cannot detect a factual claim that is wrong but not quote-like or numeric.
- With "sharing my own wording" the coach is asked for feedback, not a rewrite, but a reply that models better wording in a few sentences may pass. Treat any such text as a suggestion to think about, not words to paste.
- Everything you type, including pasted drafts, is stored locally in plain text in your Serapis folder and sent to the AI provider with each message.
- Nothing here detects plagiarism or AI use, and nothing replaces your institution's rules. Declare AI assistance where required.
