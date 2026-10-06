# Serapis

Serapis is a local-first academic organizer. It helps you keep modules, assessments, and course materials together, inspect what is known and where it came from, and optionally use AI for richer study help. Serapis is useful without AI and substantially more powerful with AI.

## Student quick start

Python 3.11 or newer is required.

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/serapis setup
```

Setup creates or continues your private workspace. It does not change the fictional sample included with the project. You can add modules, assessments, and course files during setup, then open the Hub with:

```sh
.venv/bin/serapis hub
```

In the Hub, open a module to add or manage assessments and PDF or PowerPoint materials. Module and assessment details can be edited without editing JSON. The Hub is local to your computer and binds to `127.0.0.1` by default.

## What works without AI

Setup, module and assessment management, supported material import, Hub navigation, academic picture, source inspection, and trust status are local. Serapis does not claim that an unknown fact is false or that a student-entered fact is confirmed.

## Optional AI study help

To enable the current OpenAI-backed preparation, teaching, quiz, and revision features, install the AI extra and configure an API credential:

```sh
.venv/bin/pip install -e '.[ai]'
export OPENAI_API_KEY='your-key'
```

AI actions are explicit. When used, selected source excerpts and relevant student input may be sent to OpenAI. Setup, imports, and ordinary Hub page loads do not call an AI provider. Review your institution's rules before using course material with an external provider.

## Local storage and privacy

Personal state, imported materials, records, and generated files are stored locally in the operating system's application-data location under `serapis`. `SERAPIS_HOME` selects a different workspace directory. Existing `JARVIS_STATE_FILE`, `JARVIS_WORKSPACE_DIR`, `JARVIS_CACHE_DIR`, `JARVIS_LEDGER_FILE`, and other explicit overrides continue to be honored. Credentials are not stored in academic state.

The repository's sample data is fictional and is separate from your personal workspace. Do not commit private course files, notes, generated study outputs, or credentials.

## Supported materials and platforms

- **PPTX:** direct text extraction uses Python's standard ZIP/XML libraries and is portable.
- **PDF:** direct text extraction currently uses macOS PDFKit. On other platforms a PDF can be stored and managed, but its text cannot currently be extracted by Serapis.
- **DOCX and other formats:** not currently supported for source text extraction/import.

Text extraction can still fail for damaged files, image-only PDFs, or files without extractable text. Serapis reports that condition and does not send unextractable content to AI workflows.

## Optional integrations

Core installation includes the local Hub. Extra packages are available only for features that need them:

```sh
.venv/bin/pip install -e '.[ai]'          # OpenAI study workflows
.venv/bin/pip install -e '.[blackboard]'  # browser-backed Blackboard sign-in
.venv/bin/pip install -e '.[drive]'       # Google Drive sync
.venv/bin/pip install -e '.[test]'        # development and tests
```

Blackboard and Drive features are advanced, explicitly invoked integrations. They are not needed for normal first use. Blackboard retrieval is read-only; Drive actions communicate with Google when invoked. No cloud account or hosted Serapis service is required.

## Sample and development

The fictional example is in `data/academic-state.json` and is marked as sample data. To inspect it without creating personal state, use a clean `SERAPIS_HOME` or point `JARVIS_STATE_FILE` at that file.

Run the offline tests with:

```sh
python3 -m pytest -q
```

Tests use synthetic data and block real network sockets. Serapis does not monitor courses autonomously, measure mastery, predict grades, or guarantee academic outcomes. Licensed under Apache-2.0; see [LICENSE](LICENSE).
