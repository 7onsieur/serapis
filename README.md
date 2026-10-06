# Serapis by Limitless

Serapis is a local-first academic workflow assistant developed by Selom Topanou. Development is AI-assisted using Claude and ChatGPT/Codex.

It helps learners organise supplied course information, prepare bounded source-based context, capture their own lecture notes, and create study artefacts. The sample state is fictional and uses Avery Example at Example University.

## Current capabilities

- Loads and validates editable version 2 academic state.
- Selects a requested module/week and its directly referenced sources.
- Extracts local PDF text on macOS and builds bounded, source-labelled preparation context.
- Uses a reasoning-provider boundary for preparation, teaching, quiz, revision, and assignment-planning workflows. OpenAI requests require configuration and may send the selected context externally.
- Builds a persistent JSON academic record, Word study pack, and Markdown source for manual NotebookLM upload from cached preparation.
- Captures learner-reported after-class notes locally without a model call.
- Provides read-only Blackboard retrieval and optional Google Drive sync flows when explicitly invoked and configured.
- Includes a localhost academic Hub. Loading a Hub page does not itself call Blackboard, Drive, or a model.

These are bounded user-invoked workflows. Serapis does not monitor courses autonomously, measure mastery, predict grades, or guarantee academic outcomes.

## Architecture

Editable state lives in `data/academic-state.json`. The candidate includes one tiny, original fictional SYN101 PDF so the example source workflow has input; it contains no real course material. Other source files are referenced by project-relative locators and are not bundled. The `university_jarvis` Python package validates state, selects relevant sources, creates bounded workflow contexts, and stores generated workflow cache separately from the canonical study record. The internal Python package name remains `university_jarvis` to avoid unnecessary churn in the existing implementation; the product, package metadata, and command are Serapis.

## Installation

Python 3.11 or newer is required. Local PDF extraction currently uses macOS PDFKit. From this directory:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/serapis status
```

Install Playwright's Chromium browser only if using the optional browser-backed Blackboard sign-in flow.

## Configuration and use

Start with `./serapis status` or the installed `serapis status` command. The included state has one fictional module, `SYN101`, week 1. Preparation and model-backed workflows require a local source file at the locator in state and configured reasoning credentials. Set `OPENAI_API_KEY` for uncached reasoning, or configure a supported local credential source; `JARVIS_REASONING_MODEL` selects the model. Generated preparation is cached under `.jarvis-cache/`; `JARVIS_CACHE_DIR` changes that location. `JARVIS_STATE_FILE` selects another state file.

To use your own materials, edit the state to reflect information you are permitted to use, place source files in your local project, and update their locators. Do not commit private course files, personal notes, generated study outputs, or credentials. Use `JARVIS_WORKSPACE_DIR` to choose where study records and derived files are stored.

Example local commands:

```sh
./serapis status
./serapis prepare SYN101 --week 1
./serapis workspace SYN101 --week 1
./serapis after-lecture SYN101 --week 1 --notes "My recollection of the topic"
./serapis teach SYN101 --week 1 --topic "questions and evidence"
./serapis quiz SYN101 --week 1
```

Blackboard commands require either `JARVIS_BLACKBOARD_BASE_URL` or an explicit `--base-url`. For example, set it to your institution's Blackboard host before using a Blackboard command. Sign in through your institution's sign-in/SSO in the dedicated browser profile when prompted. The API integration is read-only; retrieval and Drive sync are user initiated. Google Drive operations require Google OAuth configuration and can upload selected files.

## Privacy and external services

State, sources, caches, and workspaces are local files. Model-backed commands may send the selected source excerpts, state-derived context, and user-entered notes to the configured provider. Blackboard retrieval sends requests to the configured institution host; Drive commands communicate with Google when invoked. NotebookLM upload is manual and sends the selected Markdown file to Google. Review provider and institutional policies before using personal or course material. Credentials and browser authentication state must remain private and outside version control.

## NotebookLM

Serapis can generate a Markdown study source from an existing academic record. Upload it manually through NotebookLM if desired. NotebookLM output is a study aid and is not automatically imported as academic evidence. See [NotebookLM workflow](docs/notebooklm-integration.md).

## Academic integrity

Serapis supports explanation, practice, organisation, planning, and critique. The learner remains responsible for checking institutional rules and producing their own assessed work. Verify generated claims against cited source material.

## Limitations and status

This is an early software candidate. PDF extraction support is platform dependent; Blackboard response shapes and institutional authentication vary. The sample dataset and source are fictional. Integrations require separate configuration and have not been exercised against external services as part of this project.

## Development

Run the test suite offline with mocked providers and transports (the pytest fixture blocks real socket connections):

```sh
python3 -m pytest -q
```

The suite blocks real network sockets globally. Tests use synthetic data and fakes. See [SECURITY.md](SECURITY.md) for reporting and local-data handling guidance. Licensed under Apache-2.0; see [LICENSE](LICENSE).
