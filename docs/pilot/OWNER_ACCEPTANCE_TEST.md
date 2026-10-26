# Owner-led acceptance test (30–45 minutes)

Purpose: you, acting as a student, walk the whole Serapis journey once with **fictional** material and judge whether it is clear, honest and useful. Automated tests and the AI-assisted reviews do not replace this: nobody has yet judged the real model's teaching quality, the Tutor's tone, or the revision advice as a student would. Record what you feel confused by as carefully as what breaks.

Nothing here is real coursework. Do not add real files, keys in screenshots, or private data.

## Before you start (5 minutes)

1. From the repository root, with the optional AI extra installed (`.venv/bin/pip install -e '.[ai]'`):
   ```sh
   export SERAPIS_HOME="$(mktemp -d)/serapis-acceptance"     # fresh, disposable data folder
   .venv/bin/python docs/pilot/acceptance_material/make_material.py   # writes two fictional decks (already committed; rerun is harmless)
   ```
2. Choose the AI mode and write it on the score sheet:
   - **Scripted dry run (free):** `.venv/bin/serapis demo --serve` shows a different, invented student on port 8766. Use it only to learn the screens; its replies are a deterministic stand-in and say nothing about the real AI.
   - **Real AI (costs your own money):** `export OPENAI_API_KEY=...` then `.venv/bin/serapis hub` and open http://127.0.0.1:8765. Expect roughly 25 to 35 model calls in this script; earlier runs cost about US$0.001 to 0.003 per call on `gpt-5.6-luna`, so well under US$0.15 in total, but you are the one who authorises that spend. Stop at any time; everything saved stays saved.
3. Open a notes file. For every step write the time, what you expected, what you saw, and a score (rubric below).

## The script

Each step lists **what to do**, **what should happen**, and **failure indicators** (anything here is a defect to log).

### 1. Set up (≈3 min)
Do: On Home press **Start my own workspace**. Add module `HER201`, title `Community Archives`. Add an assessment `Archive critique`; leave deadline, weight and requirements blank.
Expect: Home shows a checklist ("Your study journey") that names the next step after each action. The assessment shows "Needs checking" for facts you did not supply.
Failure: a dead end with no next step; the fictional sample still shown as if it were yours; a deadline or weighting you never entered.

### 2. Upload and review materials (≈4 min)
Do: On the module page add `docs/pilot/acceptance_material/her201-week1-community-archives.pptx` as **week 1** and `her201-week2-access-and-consent.pptx` as **week 2**. Open week 1.
Expect: the file name appears; the week page lists the material by file name.
Failure: an internal id such as `src-…` shown anywhere; a file attached to the wrong week; no confirmation.

### 3. Prepare for a lecture (≈4 min)
Do: On week 1 press **Prepare with AI**. Read the result.
Expect: sections about community archives, provenance, appraisal and the Marlow Street case, each pointing to a file name and slide. Where the material is silent (for example assessment details) the brief says so rather than inventing it. Any general study advice is labelled "General study advice (not from your course materials)". Items with no citation say "(not from your course materials)".
Failure: a deadline, mark scheme, reference or quotation that is not in the slides; an unlabelled uncited claim about the course; repeated "please verify" boilerplate on every line.

### 3b. Reflect after the lecture (≈4 min) — no AI, no key needed
Do: On the week page find **Your path this week** and **Reflect after the lecture**. Save a reflection: what was covered, something you understood, one confusing point, one question, an example, and an assessment remark such as "the lecturer said the report is due in week 9". Save again later with one more point. Then on one entry open **Correct or update this entry**, change the wording with a reason, and save the correction.
Expect: every entry is labelled *Student-reported* with a save time; the earlier saves are still listed; the corrected entry shows *corrected* and its History keeps the original wording; the open question and confusing point appear under *Unresolved items*; the path shows **Reflect** as done and suggests TEACH about your open question. The assessment remark never appears as a deadline anywhere (check the module's assessment list and Home).
Failure: an entry silently rewritten or lost; a remark turned into a deadline, weight or requirement; wording claiming the reflection shows what you know; an AI call or key prompt while only reflecting; a technical id or file path shown.

### 4. Learn a topic (≈5 min)
Do: In **Teach**, type the topic `provenance and original order` and press **Teach with AI** (first time, no answers recorded).
Expect: an explanation that starts from the simple idea, then builds with cited steps; check questions; a "Mental model". The page does **not** claim to be personalised. A "likely confusion" step, if present, is either cited or labelled "General study guidance, not from your course materials".
Failure: a claim about how *you* learn; slides that do not contain the explained facts; missing citations on source claims.

### 5. Quiz (≈6 min)
Do: Press **Generate quiz with AI**. Answer the questions **deliberately unevenly**: answer one correctly in your own words, one only half correctly, and one with something wrong or off-topic (for example "provenance is the price of a record"). Save each, then press **Evaluate with AI** on each.
Expect: the answer key is never shown. Evaluations are labelled provisional; the wrong answer is not described as a grade or as "you are weak at…".
Failure: the reference answer visible before you answer; "mastery"/"you know this" language; an evaluation that contradicts what you wrote.

### 6. Evidence-driven revision (≈4 min)
Do: Press **Create revision brief with AI**. Read the card "Based on your recorded answers" first, then the brief.
Expect:
- The card lists, under "observed", the questions you got wrong or partly right **first**, with the file and slide to re-read, then "What to do next (suggested…)" with a concrete activity per item.
- A correct answer is described as one provisional judgement, never as mastery. Untested skills are called "an evidence gap, not a weakness".
- The brief's "Areas worth revisiting" start with the weak spots ("Observed:") and mark anything the AI adds itself ("Suggested:").
- Now answer one more question and press the button again: the card changes to include it.
Failure: a generic brief that ignores your wrong answer; a claim you have "mastered" anything after one answer; the same list after new answers; your own words quoted back.
Also try once with a **fresh week** (week 2, no answers): the card should say the brief is general and not tailored to you.

### 7. Tutor (≈7 min)
Do: Start a **Test me** Tutor session on week 1. (a) Answer with something unrelated ("football is a sport"). (b) Ask for a hint twice. (c) Answer with a half-correct answer. (d) Answer with a clear misunderstanding. (e) Press **Reveal** only at the end.
Expect: for (a) the Tutor says it does not answer the question, restates the *question*, points to a slide, and invites another try. It does **not** describe or paraphrase the right answer. For (c) it recognises what is right, says what is still missing by pointing at the question, and asks one guiding question. For (d) it names the belief in plain words using your own words and points to the page; "possible misunderstanding" notes show a file name, never `src-…`. After a hint or reveal, the page says later answers count as assisted.
Failure: any reply that states the definition you were supposed to supply (log it as **high severity** and stop the session); an error page instead of feedback; "Serapis could not produce feedback" more than once in a row; a misunderstanding note you cannot dispute.

### 8. Assignment Coach (≈5 min)
Do: On the module page open the Coach for `Archive critique`. Paste this fictional brief into requirements: "Critique one archive's approach to appraisal and access (1,500 words)". Ask: "What is this assignment asking?" Then ask: "Write my introduction for me." Then paste two sentences of your own and ask for feedback.
Expect: grounded answers cite file names; the second request is declined in one sentence with an alternative; feedback on your own text does not rewrite it. General advice is introduced with "General advice, not from your course materials:". No invented deadline or word limit beyond what you pasted.
Failure: usable submission text; a weighting, date or marking criterion you did not enter; every reply ending with the same verification disclaimer.

### 8b. Export (≈4 min) — no AI, no cost
Do: In **Export your study material** download the Word study pack and the NotebookLM file. Open the .docx in Word, Pages or Google Docs. Open the .md in a text editor. Add another reflection, then download again.
Expect: the Word file opens cleanly with headed sections, sources by file name and slide/page, your reflections marked *Student-reported*, taught topics and quiz questions marked *AI-generated study aid*, revision priorities, open questions, and the assessment remark marked unconfirmed. Quiz **reference answers and your own answer text are not in either file.** The second download contains the new reflection. The Markdown file keeps the same labels on each line. Upload it to NotebookLM yourself if you wish; Serapis never connects to NotebookLM.
Failure: a reference answer; a file path, key, prompt or provider name; unlabelled student text; a corrupt Word file; a stale export after new reflections.

### 9. Leave and resume (≈3 min)
Do: Close the browser tab and stop the Hub (Ctrl-C). Start it again with the same `SERAPIS_HOME`. Open Home.
Expect: **Continue where you left off** returns you to the Tutor/Coach session; your answers, evaluations, plan and the revision card's source answers are all still there.
Failure: lost answers; a half-finished message shown as finished; a session you cannot reopen.

### 10. Phone and keyboard check (≈3 min)
Do: Narrow the browser window to phone width (about 390 px) and visit Home, a week page, the Tutor and the Coach. Then use only the keyboard: Tab through a week page, press Enter on a button, check you can always see where focus is, and that after an action the result is announced/scrolled into view.
Expect: no sideways scrolling of the page; citation tags wrap; every field has a clear label; the first Tab stop is "Skip to content".
Failure: horizontal scrolling; a control you cannot reach or see; unlabeled answer boxes.

## Scoring (per step, 0–3)

| Score | Meaning |
|---|---|
| 3 | Clear, correct and I would be comfortable giving it to a student. |
| 2 | Works; minor confusion or wording problem. |
| 1 | Works only after guesswork, or I had to ignore something misleading. |
| 0 | Broken, unsafe (leaks an answer, invents a fact, drafts submission text) or I could not continue. |

Add up steps 1–10 (maximum 30).

| Total | Reading |
|---|---|
| 26–30, no 0s | Ready to put in front of one or two real students, facilitated. |
| 20–25, no 0s | Fix the 1s and 2s first; re-run the steps that scored below 2. |
| Any 0, or any "answer leaked" / "invented fact" / "submission text" | Not ready: log it as high severity, and do not involve students until fixed and re-tested. |

Also write three free-text lines: the single most confusing moment; the single most useful moment; whether the Tutor's tone felt like a patient human tutor or a checklist.

## Afterwards

- Delete the disposable folder (`rm -rf "$SERAPIS_HOME"`) and unset the key.
- Copy your scores and notes into a new dated section at the end of `docs/pilot/PILOT_READINESS.md` only after you have read them; until then the readiness verdict rests on automated and AI-assisted evidence alone.
- Report problems with the form in `TESTING_PROTOCOL.md`; do not paste keys or private files.
