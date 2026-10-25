"""Deterministic gap and progress analysis of one Assignment Coach session.

Pure functions over the stored session dict: no model, no files, no clock. A gap says what the session does not
yet contain; it is never a judgement of the student's work. Progress is counts only: there is deliberately no
percentage, score or grade estimate.
"""

from __future__ import annotations

from typing import Any


def gap_report(session: dict[str, Any]) -> list[dict[str, str]]:
    """What is missing or unresolved, computed from the session alone (no model, no guessing)."""
    gaps: list[dict[str, str]] = []

    def gap(kind: str, text: str, ref: str = "") -> None:
        gaps.append({"kind": kind, "text": text, "ref": ref})

    live_requirements = [r for r in session["requirements"] if not r.get("removed_from_assessment")]
    if not live_requirements:
        gap("NO_REQUIREMENTS", "No requirements are recorded for this assignment. Add what your brief asks for, so the plan can be checked against it.")
    if not session["criteria"]:
        gap("NO_CRITERIA", "No marking criteria have been added. Copy them from your brief or rubric; I will not guess how it is marked.")
    status = session["assessment"].get("fact_status", {})
    for field, label, verb in (("deadline", "deadline", "is"), ("weight_percent", "weighting", "is"), ("requirements", "requirements", "are")):
        if status.get(field) != "CONFIRMED":
            known = status.get(field) == "NEEDS_VERIFICATION"
            gap("FACT_UNVERIFIED", f"The {label} {verb} {'unverified (student-entered)' if known else 'unknown'}: check {'it' if verb == 'is' else 'them'} against your official brief.", field)
    if not any(m["readable"] for m in session.get("materials", [])):
        gap("NO_READABLE_MATERIAL", "No readable course material is available for this module, so coaching cannot point you to sources.")
    addressed = {a for sec in session["sections"] for a in sec["addresses"]}
    if not session["sections"] and not session["plan"].get("main_argument"):
        gap("NO_PLAN", "You have not started a plan: add your main argument or a first section.")
    for kind, label in (("requirements", "Requirement"), ("criteria", "Criterion")):
        if session["sections"]:
            for item in session[kind]:
                if item["id"] not in addressed and not item.get("removed_from_assessment"):
                    gap("REQUIREMENT_UNADDRESSED" if kind == "requirements" else "CRITERION_UNADDRESSED",
                        f"{label} not yet addressed by any planned section: {item['text']}", item["id"])
    found = {e["evidence_id"] for e in session["evidence"] if e["status"] == "FOUND"}
    for sec in session["sections"]:
        if not sec["evidence_ids"]:
            gap("SECTION_NO_EVIDENCE", f"Section “{sec['heading']}” has no evidence linked yet.", sec["section_id"])
        elif not set(sec["evidence_ids"]) & found:
            gap("SECTION_EVIDENCE_NOT_FOUND", f"Section “{sec['heading']}” only has evidence you still need to find.", sec["section_id"])
    for ev in session["evidence"]:
        if ev["status"] == "NEEDED":
            gap("EVIDENCE_NEEDED", f"Evidence still to find: {ev['description']}", ev["evidence_id"])
    for q in session["questions"]:
        if q["status"] == "OPEN":
            gap("QUESTION_OPEN", f"Unresolved question: {q['text']}", q["question_id"])
    return gaps


def progress_summary(session: dict[str, Any]) -> dict[str, Any]:
    """Counts only. There is deliberately no percentage, score or grade estimate."""
    addressed = {a for sec in session["sections"] for a in sec["addresses"]}
    live_requirements = [r for r in session["requirements"] if not r.get("removed_from_assessment")]
    summary = {
        "stage": session["stage"],
        "requirements": {"total": len(live_requirements), "addressed": sum(r["id"] in addressed for r in live_requirements)},
        "criteria": {"total": len(session["criteria"]), "addressed": sum(c["id"] in addressed for c in session["criteria"])},
        "sections": {"total": len(session["sections"]),
                     "drafting": sum(s["status"] == "DRAFTING" for s in session["sections"]),
                     "done": sum(s["status"] == "DONE" for s in session["sections"])},
        "evidence": {"total": len(session["evidence"]), "found": sum(e["status"] == "FOUND" for e in session["evidence"]),
                     "needed": sum(e["status"] == "NEEDED" for e in session["evidence"])},
        "questions": {"total": len(session["questions"]), "open": sum(q["status"] == "OPEN" for q in session["questions"]),
                      "resolved": sum(q["status"] == "RESOLVED" for q in session["questions"])},
        "messages": sum(1 for t in session["turns"] if t["role"] == "student" and t["status"] == "COMPLETE"),
    }
    if not live_requirements and not session["criteria"]:
        step = "Add the requirements and marking criteria from your brief, so the coach and your plan work from them."
    elif not session["sections"] and not session["plan"].get("main_argument"):
        step = "Write your main argument in your own words, or sketch the first section of your plan."
    elif summary["requirements"]["total"] + summary["criteria"]["total"] > summary["requirements"]["addressed"] + summary["criteria"]["addressed"]:
        step = "Link each requirement and criterion to the section that will address it."
    elif summary["evidence"]["needed"] or any(not s["evidence_ids"] for s in session["sections"]):
        step = "Find the evidence your sections still need, and mark it found when you have it."
    elif summary["questions"]["open"]:
        step = "Answer your open questions, or ask the coach to help you think them through."
    else:
        step = "Write your own draft from this plan, then share a passage with the coach for feedback against the criteria."
    summary["next_step"] = step
    return summary


