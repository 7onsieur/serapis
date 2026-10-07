# Serapis by Limitless

Serapis is a free, open-source, local-first academic AI assistant for university students. It maintains grounded academic context over time, bringing together a student's university, programme, modules, assessments, deadlines, course materials and study evidence.

Students often have to rebuild that context in generic AI chats. Serapis aims to keep it available for study, revision and planning, reducing repeated setup and unnecessary AI use. Its long-term goal is a persistent academic companion combining **academic context + source-grounded AI + personalised learning + assignment support + LMS/material integration**. It does not replace lecturers or universities or take authorship away from students.

Serapis is actively being developed. The current implementation is an early local application, and independent student testing is a next validation stage. No learning outcomes or user numbers are claimed.

## Current status

### Working / implemented

- **Local academic setup:** enter university, programme and study details, then manage modules and assessments in a local Hub. Add, edit and remove module and assessment records.
- **Academic picture:** the Hub lets students create, edit and manage their academic setup. The Academic Picture presents and reconciles student-entered state, machine-observed Blackboard intake, source records and study records; it is a view, not an editing interface. The CLI also provides status, picture and attention views.
- **Truth and provenance:** consequential fields use `CONFIRMED`, `NEEDS_VERIFICATION` or `UNKNOWN` statuses with evidence references. Evidence distinguishes university material, student-entered facts, machine-observed LMS information, derived study aids and other sources. A value does not become authoritative just because it is present; model output cannot independently confirm institutional facts. Deadlines and weights lacking adequate evidence remain unverified or unknown.
- **Materials:** associate supported PDF and PPTX files with a module/week, replace, reassign or remove them, and retain source IDs and extraction metadata. PPTX text extraction is portable. PDF text extraction uses macOS PDFKit.
- **Learning evidence:** save attempts locally and optionally request a bounded AI evaluation against a supplied task/rubric and source context. A deterministic rule selects the next useful capability to address.
- **Study workflows:** explicit AI actions support PREPARE, TEACH, QUIZ and REVISE in bounded, source-grounded ways. Generated outputs are study aids, and source references are checked against the context provided to the workflow.
- **Assignment support:** a module-scoped, one-shot assignment planning brief can explain the prompt, constraints and marking criteria, identify relevant course material, suggest planning questions and work stages, and surface evidence needs and risks. It is not a resumable conversation or a stored assignment plan, and it does not produce a finished submission.
- **Local Hub and CLI:** the Hub binds to `127.0.0.1` by default. Setup, state management, material import and ordinary Hub page views do not require a model call.

### Partial / limited

- **Learning dimensions:** the current evidence model tracks recall, explanation and application. Analysis is not yet a separate tracked capability. The interface records whether work was prompted or unaided, retains raw attempts, and distinguishes an evidence gap from weak performance. There is no universal mastery percentage or grade prediction. Model evaluations are provisional task-level judgements, not institutional or definitive measures of understanding.
- **Learning loop:** Learn → student responds → attempt is saved → optional evaluation updates the evidence picture → deterministic next-task selection → repeat. The model may create a source-grounded task or evaluate a response, but deterministic system logic selects which capability to address next. The current selection uses the latest available task evidence and simple rules; it is not a validated adaptive-learning model.
- **PREPARE / TEACH / QUIZ / REVISE:** each is an explicit workflow, not an autonomous tutor. PREPARE produces bounded preparation; TEACH explains a source-grounded concept and can provide check questions; QUIZ creates source-grounded questions whose responses can enter the evidence loop; REVISE creates a revision brief. Generated questions and evaluations have not been shown through independent student research to improve learning.
- **PDFs:** on macOS, Serapis attempts direct text extraction. On other platforms PDFs can be stored and managed, but their text is not extracted. Image-only/scanned PDFs and files without extractable text are not handled by OCR.
- **Blackboard:** there is an explicitly invoked, read-oriented browser-backed discovery and material retrieval/reconciliation path. It is structurally implemented and has offline tests, but has not been established as a reliable live integration across institutions or course configurations. Incomplete discovery can make a previously observed item appear missing; opaque LMS metadata that stays unchanged can prevent re-download and content-hash comparison even when a file's content changed. These statuses need cautious interpretation. Scheduled monitoring and notifications are not production-ready and are not provided as an autonomous service.
- **Google Drive:** optional OAuth and explicitly invoked upload/update code are present. Automated tests use fake services/offline fixtures; that is not proof of reliable live Google Drive operation. The configured `drive.file` permission is limited to files and folders created or opened by the app, and a real OAuth flow or Drive action communicates with Google.
- **Provider:** OpenAI is the only implemented AI provider. There is no local inference implementation or currently supported multi-provider selection.

### Unproven externally

Serapis has not yet established independent evidence for educational effectiveness, robust operation across real universities, or production reliability of its external integrations. Those questions require real student use and broader live integration testing.

## How grounding and trust work

Serapis keeps academic facts and AI study outputs in different roles. Institutional facts have explicit status and field-level evidence. A confirmed fact should have appropriate source evidence; student-entered information can be useful while still needing verification. `UNKNOWN` means there is not enough evidence to make a claim, not that the fact is false or that the student lacks knowledge. Imported materials retain source identifiers, and derived study aids can refer back to those sources. AI output may help with learning, but it cannot promote a deadline, assessment weight or other institutional fact to `CONFIRMED` by itself.

When a supported AI workflow runs, Serapis builds a bounded context from the relevant module/week, assessment information and available source excerpts. The workflow is instructed to use supplied sources, and citation references are checked against those made available. This helps make the origin of study content inspectable; it does not guarantee that a model interpretation is correct.

## Installation and first use

Python 3.11 or newer is required. From a terminal:

```sh
git clone https://github.com/7onsieur/serapis.git
cd serapis
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
.venv/bin/serapis setup
```

Setup creates or continues your personal workspace and can open the Hub when finished. You can also start it later with:

```sh
.venv/bin/serapis hub
```

The Hub is local to your computer and defaults to `http://127.0.0.1:8765`. In the Hub, add modules and assessments, then add PDF or PPTX course materials to the relevant module/week. You can manage your modules and assessments there without editing JSON files. The current setup and Hub have been tested as a Python application, but the project is still early-stage software; the Blackboard browser integration in particular may require platform-specific browser setup.

Optional dependencies are only needed for the matching feature:

```sh
.venv/bin/pip install -e '.[ai]'          # OpenAI study and assignment workflows
.venv/bin/pip install -e '.[blackboard]'  # browser-backed Blackboard integration
.venv/bin/pip install -e '.[drive]'       # Google Drive integration
.venv/bin/pip install -e '.[test]'        # development and tests
```

To enable AI actions, install the `ai` extra and configure `OPENAI_API_KEY` in your environment. AI actions are explicitly invoked and labelled in the interface. Without that setup, local organisation, source management and academic-picture features remain available.

## Local data, AI calls and integrations

Personal academic state, imported materials, learning attempts and generated local study records are designed to live on your computer in the operating system's application-data location under `serapis`. `SERAPIS_HOME` can select another workspace directory. Explicit path overrides are also supported for advanced setups. Credentials are handled separately from academic state.

Ordinary Hub page views do not call an AI provider. When you explicitly invoke an AI action, the relevant bounded academic context, selected source excerpts and any response being evaluated may be sent to OpenAI. Read the provider's terms and your institution's course-material rules before using those actions. Optional Blackboard and Drive actions have separate external boundaries: Blackboard login/discovery/download requests contact the configured institution; Drive authentication and transfers contact Google. No hosted Serapis service is required for local use.

The repository's sample academic record is fictional and separate from personal workspace data. Do not commit private course files, notes, generated study outputs or credentials.

## Supported material formats

- **PPTX:** direct text extraction from readable slide text, using Python's standard ZIP/XML libraries; portable across platforms.
- **PDF:** direct text extraction through macOS PDFKit only. Other platforms can store and manage PDFs but cannot currently extract their text. OCR for scanned/image-only PDFs is not implemented.
- **DOCX and other formats:** not currently supported for source-text ingestion.

Extraction may also fail for damaged or textless files. Unextractable content is not passed to AI workflows.

## Roadmap

The immediate direction is practical and evidence-led:

1. **Assignment Coach:** resumable planning and progressive coaching.
2. **LMS / Blackboard:** safer discovery, change detection and reconciliation before considering scheduled features.
3. **Materials:** cross-platform PDF extraction, OCR investigation and useful format coverage.
4. **Learning quality:** student testing and evidence-led evaluation of generated teaching and questions.
5. **Onboarding:** simpler installation and first-run guidance.
6. **Provider flexibility:** preserve the option of future providers or local models; neither is implemented today.

See [ROADMAP.md](ROADMAP.md) for the concise work list and current validation priorities.

## Contributing and testing

Contributions that improve correctness, source visibility, accessibility, installation or student usability are welcome. Please keep changes grounded in the current code, avoid adding real course material or credentials to issues and pull requests, and describe the environment used for any integration report. External integrations should be tested with synthetic or appropriately authorized data.

Run the offline test suite with:

```sh
python3 -m pip install -e '.[test]'
python3 -m pytest -q
```

The current suite uses synthetic data and fake/offline integration paths; a passing suite does not establish live-provider or live-institution reliability. Serapis does not autonomously monitor courses, predict grades, claim a mastery score or guarantee academic outcomes.

## Project

Serapis is a free, open-source, local-first academic AI assistant for university students, developed by Selom Topanou. Development is AI-assisted using Claude and ChatGPT/Codex.

Licensed under Apache-2.0; see [LICENSE](LICENSE).
