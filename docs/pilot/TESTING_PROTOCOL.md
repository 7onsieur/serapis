# Student testing protocol (controlled pilot)

**Purpose:** find out whether students can set up and use Serapis, where they get stuck, and what they find useful or untrustworthy. **It does not measure learning outcomes**, and results must not be reported as evidence of educational effectiveness.

## Ground rules

- 5–8 volunteer students, each in a 60–75 minute moderated session (screen-share or in person), plus an optional return visit after a few days to test resuming.
- Facilitator is not the student's assessor. Participation is voluntary and can stop at any time.
- Students use **synthetic or non-sensitive material**: the built-in demo, or a public/own non-assessed deck. No live assessed work, no university credentials, no Blackboard or Drive.
- AI steps: either run the pilot with the scripted demo provider (no cost, shows flow only) or with a facilitator-provided OpenAI key and a spending limit. State which in the notes; never mix the two when comparing.
- Record: task completion, time, errors, quotes. Do not record screens containing personal data without consent. Store notes without names (P1, P2, …).
- Tell students up front: it is early software; AI replies can be wrong; the coach will not write their work; what is sent to OpenAI when they use AI buttons (see `PRIVACY_AND_INTEGRITY.md`).

## Consent and safety checklist (before each session)

- [ ] Student read `PRIVACY_AND_INTEGRITY.md` and agreed to take part; knows they can stop at any time.
- [ ] Student knows what leaves the computer when they use AI buttons (or this session uses the scripted demo only).
- [ ] No live assessed work, real university credentials or private files will be used. No Blackboard/Drive.
- [ ] Facilitator will not ask the student to try to defeat the integrity checks; if the student tries, note it neutrally (it is useful data). Any reply that looks like usable submission text is logged as a **High** incident with the exact message, and the pilot is paused until reviewed.
- [ ] Data folder for this participant is separate and will be deleted or returned afterwards.

## Setup for the facilitator (once per machine)

1. Follow `STUDENT_QUICKSTART.md` §1, confirm the demo opens, run `.venv/bin/python -m pytest -q`.
2. For real-AI sessions only: `pip install -e '.[ai]'`, set `OPENAI_API_KEY`, confirm one Prepare call works on the demo-style deck before the student arrives.
3. Start each participant from an empty `SERAPIS_HOME` (new folder).

## Usability tasks

For each: give the scenario, do not explain the interface, note completion (done / done with help / not done), time, and where they hesitated. Stop a task after 5 minutes.

| # | Scenario | Success looks like |
|---|---|---|
| 1 | "Set up Serapis for yourself: say where you study, and add the module *BUS101 Introduction to Business*." | Profile saved, module visible |
| 2 | "Add an assessment called *Reflective report*, due 2 May 2030, worth 40%, with two requirements." | Assessment listed, shown as *Needs checking* |
| 3 | "Add the lecture deck for week 1 to this module." (provide `bus101-week1.pptx` from the demo folder) | Material attached to week 1 |
| 4 | "Get ready to study week 1, then test yourself on it." | Prepare run, quiz shown, answer saved |
| 5 | "Find out how well your answer matched, and what you could do next." | Evaluation read; next-task suggestion understood |
| 6 | "Ask the tutor to teach you something you are unsure of from week 1." | Tutor session with a hint or answer |
| 7 | "Open the reflective report in the Assignment Coach and add the marking criteria from the brief." | Session open, criteria added |
| 8 | "Ask the coach what the brief wants, then try asking it to write your introduction. What happens?" | Reads reply; understands refusal and alternatives |
| 9 | "Write down the main argument and two sections of your plan, linking each to a requirement." | Plan saved with links |
| 10 | "What is still missing from your preparation? Where did you see that?" | Finds the gaps panel |
| 11 | Close the browser and Hub; restart; "Carry on where you left off." | Returns to the same session with everything intact |

Additional facilitator-run checks (not student tasks): (a) with no AI key set, send a coach message and confirm the error is readable and **Retry** / **Discard it** work; (b) press the browser Back button after sending a message and confirm nothing is sent twice; (c) open the same session in two tabs and confirm edits from both survive.

## Observation prompts

Did they notice the "Needs checking" tags and understand them? Did they trust or distrust a coach reply, and why? Did they try to get the coach to write for them (note without judgement)? Did anything look broken but turn out to be fine (or the reverse)?

## Structured feedback questions (after the tasks)

Rate 1 (strongly disagree) – 5 (strongly agree), then ask "why?":

1. I understood what to do first when I opened Serapis.
2. Setting up my modules and files was straightforward.
3. I understood what was saved on my computer and what is sent to an AI service.
4. The study aids (quiz, teach, tutor) felt connected to my own course material.
5. The citations/source references helped me check the answers.
6. I could tell which things were verified and which were not.
7. The Assignment Coach helped me think about the assignment, rather than doing it for me.
8. I knew what to do next at every stage of the coach.
9. I would trust the coach's replies enough to act on them without checking. (Disagreement is the desirable answer.)
10. Coming back after closing the app, I found things as I left them.

Open questions: What was the most confusing moment? What did you expect that was not there? What would you use this for in a real module? What would make you stop using it? Was any reply wrong, unhelpful or uncomfortable? Is there anything you would not be willing to put into it?

## Bug / observation log (one row each)

`Participant · task # · what happened · what was expected · screen/URL · severity (blocks task / slows / cosmetic) · AI mode (scripted/real)`

## After the pilot

Summarise task completion and recurring blockers, list fixes, and report the limits of the evidence (small, self-selected, moderated, short). Do not state learning gains, user numbers beyond the participants, or institutional endorsement.
