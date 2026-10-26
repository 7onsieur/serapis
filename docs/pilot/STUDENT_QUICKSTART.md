# Serapis — student quick start

Serapis is early, free, open-source software that runs **on your own computer**. It helps you keep your modules, assessments and course files together, study from them with AI-generated (source-grounded) study aids, and plan assignments with a coach that helps you think but never writes your work.

## Before you begin

- A Mac, Windows or Linux computer with **Python 3.11 or newer** and a terminal.
- Course files you are allowed to use, as **PowerPoint (.pptx)** or **PDF**. PDF text can only be read on **macOS**; on other systems PDFs are stored but cannot be searched, so prefer .pptx.
- Optional, only for the AI buttons: an OpenAI API key (`OPENAI_API_KEY`). The Hub, setup, material import, plan editing and the synthetic demo work without one. Using AI sends the relevant excerpts and your messages to OpenAI and may cost money on your key.

## 1. Try the synthetic demonstration first (no key, no cost)

```sh
git clone https://github.com/7onsieur/serapis.git && cd serapis
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/serapis demo --serve
```

Open http://127.0.0.1:8766. You will see an invented student, two modules, lecture decks and an Assignment Coach session with a saved plan. Replies are scripted by a deterministic stand-in (a banner says so), nothing leaves your computer, and it uses a separate folder, never your real data. `serapis demo --reset` rebuilds it.

## 2. Set up your own workspace

```sh
.venv/bin/pip install -e '.[ai]'      # only if you will use the AI buttons
export OPENAI_API_KEY=...             # only if you will use the AI buttons
.venv/bin/serapis hub
```

Open http://127.0.0.1:8765. **First time only:** until you start your own workspace, the Hub shows an invented *Fictional sample*. Press **Start my own workspace** on Home (or run `.venv/bin/serapis setup`, which asks the same questions in the terminal). The sample is never changed. **Home** then shows a checklist ("Your study journey") and always names the next step. Work through it:

1. **Profile** — university and programme (optional).
2. **Modules** — add a module code and title.
3. **Assessments** — on the module page add each assessment. Deadline, weight and requirements are optional; whatever you type is shown as *Needs checking* until supported by a source.
4. **Materials** — add .pptx/PDF files to the module, ideally with the week number. Also add your **assignment brief** if you have it as a file.
5. **Study a week** — open the week, press *Prepare with AI*, then use *Teach*, *Quiz*, *Revise* or start a *Tutor* session. Answers are saved as study evidence; you can ask for an AI evaluation of each. *Revise* then puts the questions you found hardest first and says what it observed versus what it suggests; with no answers recorded it is a general brief and says so. General study advice is always labelled as not coming from your course materials.
6. **Assignment Coach** — on the module page press *Open in Assignment Coach* next to the assessment. Copy the requirements and marking criteria from your official brief, plan in your own words, and talk it through with the coach.

Everything is saved on your computer. Close the browser or stop the Hub whenever you like; **Home → Continue where you left off** takes you back.

## Where your data lives

In your operating system's application-data folder under `serapis` (or `SERAPIS_HOME`). Course files, your plan and your coach conversations are never added to Git. To remove everything, delete that folder.

## If something goes wrong

- An error appears in a red box on the same page; your typed text is kept where possible.
- "No OpenAI credential" means the AI buttons are not set up; everything else still works.
- A coach message that did not finish (for example no AI key, or the service was down) is saved and offers **Retry** (never sends twice) or **Discard it**.
- A long coach session that reaches its limit: use **Start a fresh session**. Your criteria, plan, evidence and questions carry over; the old conversation stays, read-only.
- The coach says no to something you asked: that is by design; see `PRIVACY_AND_INTEGRITY.md`. Rephrase toward understanding, planning or feedback.
- Report problems with the form in `TESTING_PROTOCOL.md`. Do not paste private course files or keys into reports.
