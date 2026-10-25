"""A complete, fully synthetic student demonstration (``serapis demo``).

Everything here is invented: the university, the student, the modules, the lecture decks and the
assessment brief. Nothing is read from a real workspace and nothing leaves the machine: the
"AI" is ``ScriptedStudyProvider`` (deterministic, offline, free), Blackboard and Google Drive are
never touched, and all data lives in one throw-away directory that carries a marker file so the
command can never overwrite a real workspace.

The seeding goes through the same service functions the Hub uses, so running it also exercises
the real setup, import, retrieval, study, evidence and Assignment Coach paths.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from xml.sax.saxutils import escape

from .state import StateError

MARKER = ".serapis-demo"
ENV_KEYS = ("SERAPIS_HOME", "JARVIS_WORKSPACE_DIR", "JARVIS_CACHE_DIR", "JARVIS_STATE_FILE", "JARVIS_LEDGER_FILE")

# Original, invented teaching content. Plain statements, written for this demonstration.
BUS101_WEEK1 = ("Week 1 - Organisations and stakeholders (synthetic)", [
    ("Organisations and stakeholders",
     "An organisation is a group of people who work together to pursue shared goals. Stakeholders are the people and groups who affect or are affected by what an organisation does."),
    ("Primary and secondary stakeholders",
     "Primary stakeholders such as customers, employees and owners have a direct financial or operational relationship with the organisation. Secondary stakeholders such as local communities and the media are affected indirectly but can still influence its reputation."),
    ("Stakeholder interests can conflict",
     "Shareholders may want higher dividends while employees want higher wages. A manager must weigh these competing interests and explain the reasoning behind each decision."),
    ("Mapping influence and interest",
     "A stakeholder map plots each group by how much power it has and how interested it is. Groups with high power and high interest need close engagement, while groups with low power and low interest need only monitoring."),
])
BUS101_WEEK2 = ("Week 2 - Strategic analysis (synthetic)", [
    ("Why analyse the environment?",
     "Strategic analysis helps managers understand where an organisation stands before choosing a direction. Good analysis uses evidence rather than opinion."),
    ("SWOT analysis",
     "A SWOT analysis lists internal strengths and weaknesses and external opportunities and threats. Its value depends on the evidence behind each entry, not on the length of the lists."),
    ("Common weaknesses in SWOT work",
     "Common mistakes include listing items without evidence, mixing internal and external factors, and stopping at description without drawing a conclusion for action."),
    ("From analysis to recommendation",
     "A recommendation should follow from the analysis. It should say which finding matters most, what action that finding suggests and what risk remains."),
])
BUS101_BRIEF = ("Reflective report brief (synthetic)", [
    ("Assessment brief",
     "Reflective report of 1,500 words. Choose one organisation you know and reflect on how it handles competing stakeholder interests. Use at least two ideas from weeks 1 and 2 and support your points with evidence."),
    ("Marking criteria",
     "Understanding of stakeholder concepts. Quality of the evidence used. Depth of reflection on your own learning. Clarity of structure and referencing."),
    ("Submission rules",
     "Submit a single document. Reference every source you use. Your reflection must be your own work."),
])

_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_SLIDE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"


def build_pptx(path: Path, slides: list[tuple[str, str]]) -> Path:
    """Write a small, valid .pptx with one title and one body paragraph per slide (stdlib only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>' for i in range(len(slides)))
    rels = "".join(f'<Relationship Id="rId{i + 1}" Type="{_SLIDE_REL}" Target="slides/slide{i + 1}.xml"/>' for i in range(len(slides)))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                         '<Default Extension="xml" ContentType="application/xml"/></Types>')
        archive.writestr("ppt/presentation.xml",
                         f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:presentation {_NS}><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>')
        archive.writestr("ppt/_rels/presentation.xml.rels",
                         f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{_REL}">{rels}</Relationships>')
        for i, (title, body) in enumerate(slides, start=1):
            archive.writestr(
                f"ppt/slides/slide{i}.xml",
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><p:sld {_NS}><p:cSld><p:spTree>'
                f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>'
                f'<p:txBody><a:p><a:r><a:t>{escape(title)}</a:t></a:r></a:p></p:txBody></p:sp>'
                f'<p:sp><p:nvSpPr><p:cNvPr id="3" name="Body"/><p:cNvSpPr/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>'
                f'<p:txBody><a:p><a:r><a:t>{escape(body)}</a:t></a:r></a:p></p:txBody></p:sp>'
                f'</p:spTree></p:cSld></p:sld>')
    return path


@contextmanager
def demo_environment(home: Path) -> Iterator[Path]:
    """Point every Serapis path at ``home`` for the duration, restoring the previous environment after."""
    previous = {key: os.environ.get(key) for key in ENV_KEYS}
    os.environ["SERAPIS_HOME"] = str(home)
    os.environ["JARVIS_WORKSPACE_DIR"] = str(home / "workspace")
    os.environ["JARVIS_CACHE_DIR"] = str(home / "cache")
    os.environ["JARVIS_LEDGER_FILE"] = str(home / "intake-ledger.json")
    os.environ.pop("JARVIS_STATE_FILE", None)
    try:
        yield home
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def prepare_directory(home: Path, *, reset: bool = False) -> Path:
    """Create the demo directory, refusing to touch anything that is not a previous demo."""
    from .state import personal_data_dir

    home = home.expanduser().resolve()
    if home == personal_data_dir().resolve() or home == Path.home().resolve():
        raise StateError("Choose a separate folder for the demonstration; it must not be your real Serapis workspace.")
    if home.exists():
        if not (home / MARKER).is_file():
            if any(home.iterdir()):
                raise StateError(f"{home} exists and is not a Serapis demonstration folder, so it was left alone.")
        elif reset:
            shutil.rmtree(home)
        else:
            raise StateError(f"A demonstration already exists at {home}. Use --reset to rebuild it, or open it with --serve.")
    home.mkdir(parents=True, exist_ok=True)
    (home / MARKER).write_text("Synthetic Serapis demonstration. Safe to delete.\n", encoding="utf-8")
    return home


def seed_demo(home: Path, provider: Any | None = None) -> dict[str, Any]:
    """Build the synthetic student's workspace inside ``home`` and return a summary of what exists.

    Must run inside ``demo_environment(home)``. Uses the same functions the Hub calls.
    """
    from . import assignment_coach, hub_service
    from .scripted_provider import ScriptedStudyProvider
    from .state import load_state
    from .student_setup import add_module, edit_profile, import_material, initialize_personal_state, save_assessment

    provider = provider or ScriptedStudyProvider()
    root = Path(os.environ["JARVIS_WORKSPACE_DIR"])
    initialize_personal_state()
    edit_profile(university="Example University (fictional)", programme="BA Business Studies (fictional)")
    add_module("BUS101", "Introduction to Business (synthetic)")
    add_module("STA110", "Statistics Foundations (synthetic, no materials yet)")
    save_assessment("BUS101", title="Reflective report", deadline="2030-05-02", weight_percent="40", requirements=(
        "Choose one organisation you know and reflect on how it handles competing stakeholder interests\n"
        "Use at least two ideas from weeks 1 and 2\nSupport your points with evidence"))
    save_assessment("BUS101", title="Group presentation")

    sources = home / "synthetic-source"
    for name, (_title, slides) in {"bus101-week1.pptx": BUS101_WEEK1, "bus101-week2.pptx": BUS101_WEEK2,
                                   "bus101-reflective-report-brief.pptx": BUS101_BRIEF}.items():
        build_pptx(sources / name, slides)
    import_material("BUS101", sources / "bus101-week1.pptx", week=1)
    import_material("BUS101", sources / "bus101-week2.pptx", week=2)
    import_material("BUS101", sources / "bus101-reflective-report-brief.pptx")

    state = load_state()
    for week in (1, 2):
        hub_service.materialize_workspace("BUS101", week, state=state, provider=provider, workspace_root=root)
    quiz = hub_service.generate_quiz("BUS101", 1, state=state, provider=provider, workspace_root=root)
    good = hub_service.answer_quiz_question("BUS101", 1, quiz["quiz_id"], "q1",
                                            "Primary stakeholders such as customers, employees and owners have a direct financial or operational relationship with the organisation.", workspace_root=root)
    weak = hub_service.answer_quiz_question("BUS101", 1, quiz["quiz_id"], "q2", "Stakeholders are people.", workspace_root=root)
    for attempt in (good, weak):
        hub_service.evaluate_learning_attempt("BUS101", 1, attempt["attempt_id"], state=state, provider=provider, workspace_root=root)
    hub_service.teach_topic("BUS101", 1, topic="stakeholders", state=state, provider=provider, workspace_root=root)

    assessment = next(a for a in state["modules"][0]["assessments"] if a["title"] == "Reflective report")
    started = assignment_coach.start_session(state, "BUS101", assessment["id"], client_request_id="demo-start", workspace_root=root)
    sid = started["session_id"]
    assignment_coach.add_brief_items("BUS101", sid, kind="criteria", workspace_root=root, text=(
        "Understanding of stakeholder concepts\nQuality of the evidence used\nDepth of reflection on your own learning\nClarity of structure and referencing"))
    assignment_coach.send_message(state, "BUS101", sid, client_turn_id="demo-turn-1", provider=provider, workspace_root=root,
                                  text="What does the brief mean by competing stakeholder interests, and where do my course materials cover it?")
    assignment_coach.send_message(state, "BUS101", sid, client_turn_id="demo-turn-2", provider=provider, workspace_root=root,
                                  text="Please write my introduction for me.")  # refused before any model call
    assignment_coach.save_plan_overview("BUS101", sid, workspace_root=root,
                                        main_argument="My organisation balances customers and staff well but under-weights the local community.",
                                        notes="Pick the organisation by Friday.")
    plan = assignment_coach.load_session("BUS101", sid, workspace_root=root)
    req_ids = [r["id"] for r in plan["requirements"]]
    crit_ids = [c["id"] for c in plan["criteria"]]
    assignment_coach.save_evidence("BUS101", sid, description="Week 1 slide on conflicting stakeholder interests", kind="COURSE_MATERIAL",
                                   status="FOUND", source_id=next(m["source_id"] for m in plan["materials"] if "week1" in m["title"].lower()),
                                   pdf_page=3, workspace_root=root)
    plan = assignment_coach.load_session("BUS101", sid, workspace_root=root)
    found = next(e["evidence_id"] for e in plan["evidence"] if e["status"] == "FOUND")
    assignment_coach.save_section("BUS101", sid, heading="Who the stakeholders are", point="Name the groups and why each matters.",
                                  addresses=req_ids[:1] + crit_ids[:1], evidence_ids=[found], status="DRAFTING", workspace_root=root)
    assignment_coach.save_section("BUS101", sid, heading="Where their interests conflict", point="One concrete conflict and how it was handled.",
                                  addresses=req_ids[1:2] + crit_ids[1:2], workspace_root=root)
    assignment_coach.add_question("BUS101", sid, text="Does the word limit include the reference list?", workspace_root=root)
    assignment_coach.set_stage("BUS101", sid, "PLAN", workspace_root=root)

    final = assignment_coach.load_session("BUS101", sid, workspace_root=root)
    return {
        "home": str(home), "modules": ["BUS101", "STA110"], "materials": 3, "weeks_built": [1, 2],
        "quiz_attempts": 2, "coach_session": sid, "coach_url": f"/modules/BUS101/coach/{sid}",
        "coach_gaps": len(final["gaps"]), "coach_stage": final["stage"],
        "integrity_refusals": sum(1 for t in final["turns"] if t.get("kind") == "REFUSAL"),
    }
