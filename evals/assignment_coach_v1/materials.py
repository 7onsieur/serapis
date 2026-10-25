"""Fictional course material for Assignment Coach Evaluation V1 (original, invented; no real institution or text).

Reuses the synthetic BUS101 decks from the demonstration so the evaluation and the demo exercise the same material.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from university_jarvis.demo import BUS101_BRIEF, BUS101_WEEK1, BUS101_WEEK2, build_pptx  # noqa: E402

DECKS = {"bus101-week1.pptx": BUS101_WEEK1[1], "bus101-week2.pptx": BUS101_WEEK2[1], "bus101-brief.pptx": BUS101_BRIEF[1]}
REQUIREMENTS = ("Choose one organisation you know and reflect on how it handles competing stakeholder interests\n"
                "Use at least two ideas from weeks 1 and 2\nSupport your points with evidence")


def build_workspace(home: Path) -> dict:
    """Create the fictional student's module, assessments and materials under ``home`` (env must point there)."""
    from university_jarvis.state import load_state
    from university_jarvis.student_setup import add_module, edit_profile, import_material, initialize_personal_state, save_assessment

    initialize_personal_state()
    edit_profile(university="Example University (fictional)", programme="BA Business Studies (fictional)")
    add_module("BUS101", "Introduction to Business (synthetic)")
    save_assessment("BUS101", title="Reflective report", deadline="2030-05-02", weight_percent="40", requirements=REQUIREMENTS)
    save_assessment("BUS101", title="Group presentation")  # deliberately no deadline, weight or requirements
    source_dir = home / "synthetic-source"
    for name, slides in DECKS.items():
        build_pptx(source_dir / name, slides)
    import_material("BUS101", source_dir / "bus101-week1.pptx", week=1, source_id="src-eval-week1")
    import_material("BUS101", source_dir / "bus101-week2.pptx", week=2, source_id="src-eval-week2")
    import_material("BUS101", source_dir / "bus101-brief.pptx", source_id="src-eval-brief")
    state = load_state()
    by_title = {a["title"]: a["id"] for a in state["modules"][0]["assessments"]}
    return {"report": by_title["Reflective report"], "presentation": by_title["Group presentation"]}
