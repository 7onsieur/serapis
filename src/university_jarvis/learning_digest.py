"""A bounded, honest digest of what a student's recorded answers show, for REVISE and TEACH.

Everything here is derived from attempts already stored in the week's academic record (quiz answers,
tutor turns, TEACH check questions). Nothing is inferred about the person.

Vocabulary, kept deliberately narrow:

- OBSERVED: a fact about a recorded answer (what was asked, the latest provisional judgement, whether help
  preceded it, how many attempts, whether attempts disagree). These are task-level model judgements, not
  grades.
- INFERRED: a suggestion derived from observations by fixed rules (what to revisit first, what to retest).
  It is labelled as a suggestion and is never presented as the student's level.
- NOT TESTED: absence of evidence. It is an evidence gap, never a weakness.

There is no mastery score. The strongest standing is ``DEMONSTRATED_UNAIDED`` and it always carries the
reminder that it reflects one task, answered once, at one time.

The student's raw answer text is never included (it is untrusted text and not needed to prioritise).
"""

from __future__ import annotations

import re
from typing import Any

from .sources import render_source_location
from .tutor_policy import classify_evidence
from .workspace import LEARNING_CAPABILITIES, effective_outcome, task_text_hash

NEEDS_WORK = "NEEDS_WORK"
PARTLY = "PARTLY_DEMONSTRATED"
MIXED = "MIXED_EVIDENCE"
UNCERTAIN = "UNCERTAIN"
AFTER_HELP = "DEMONSTRATED_AFTER_HELP"
DEMONSTRATED = "DEMONSTRATED_UNAIDED"

_RANK = {NEEDS_WORK: 0, PARTLY: 1, MIXED: 2, UNCERTAIN: 3, AFTER_HELP: 4, DEMONSTRATED: 5}
STANDING_TEXT = {
    NEEDS_WORK: "Your latest answer was not supported by the course material.",
    PARTLY: "Your latest answer was partly supported by the course material.",
    MIXED: "Your answers to this question disagree with each other (some supported, some not).",
    UNCERTAIN: "There is no clear judgement yet (unevaluated, unclear, or a judgement you disputed).",
    AFTER_HELP: "Your latest answer was supported, but only after help or after seeing the answer.",
    DEMONSTRATED: "Your latest answer was supported with no help (one question, answered once).",
}
ACTIVITY = {
    NEEDS_WORK: "Re-read the cited material, then answer the question again without looking.",
    PARTLY: "Compare your answer with the cited passage, note what is missing, then answer again.",
    MIXED: "Answer it again unaided so there is clearer evidence either way.",
    UNCERTAIN: "Answer it again unaided so there is something to judge.",
    AFTER_HELP: "Retest it unaided later; an answer after help shows less than one without.",
    DEMONSTRATED: "No revision priority from this evidence; revisit it later as spaced practice, not as proof you know it.",
}
MAX_ITEMS = 12
MAX_REASON_CHARS = 160


def _key(attempt: dict[str, Any]) -> str:
    return str(attempt.get("task_key") or attempt.get("origin") or task_text_hash(attempt.get("task")))


def _standing(attempts: list[dict[str, Any]]) -> tuple[str, bool]:
    """(standing, mixed) from the attempts at one task, oldest first."""
    latest = attempts[-1]
    evaluation = latest.get("evaluation")
    outcome = effective_outcome(evaluation)
    unaided = [a for a in attempts if a.get("assistance_status") == "UNAIDED" and a.get("evaluation")]
    unaided_outcomes = {effective_outcome(a["evaluation"]) for a in unaided} & {"SUPPORTED", "NOT_SUPPORTED"}
    mixed = unaided_outcomes == {"SUPPORTED", "NOT_SUPPORTED"}
    if mixed:
        return MIXED, True
    if outcome is None or outcome == "UNCLEAR":
        return UNCERTAIN, False
    if outcome == "NOT_SUPPORTED":
        return NEEDS_WORK, False
    if outcome == "PARTLY_SUPPORTED":
        return PARTLY, False
    # SUPPORTED
    if latest.get("assistance_status") == "UNAIDED":
        return DEMONSTRATED, False
    return AFTER_HELP, False


def _short(text: str, limit: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _places(attempt: dict[str, Any], titles: dict[str, dict[str, Any]]) -> list[str]:
    places = []
    for ref in attempt.get("source_references") or []:
        source = titles.get(ref.get("source_id"), {})
        name = source.get("title") or ref.get("source_title") or "a course material"
        where = render_source_location(source.get("extraction", {}).get("method"), ref.get("pdf_page")).lstrip(", ")
        places.append(", ".join(p for p in (name, where) if p))
    return places


def build_learning_digest(record: dict[str, Any] | None) -> dict[str, Any]:
    """Digest of one week's recorded learning evidence. ``status`` is NONE when nothing was answered."""
    learning = (record or {}).get("learning", {})
    attempts = [a for a in learning.get("evidence", []) if isinstance(a, dict) and a.get("task")]
    titles = {s.get("source_id"): s for s in (record or {}).get("sources", [])}
    empty = {"status": "NONE", "attempt_count": 0, "evaluated_count": 0, "items": [], "priority_order": [],
             "untested_capabilities": list(LEARNING_CAPABILITIES), "limits": []}
    if not attempts:
        return empty
    grouped: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts:
        grouped.setdefault(_key(attempt), []).append(attempt)
    items = []
    for number, (key, rows) in enumerate(grouped.items(), start=1):
        standing, mixed = _standing(rows)
        latest = rows[-1]
        evaluation = latest.get("evaluation") or {}
        items.append({
            "id": f"E{number}",
            "task": str(latest.get("task"))[:300],
            "capability": latest.get("capability"),
            "topic": latest.get("topic"),
            "standing": standing,
            "latest_outcome": effective_outcome(latest.get("evaluation")),
            "evaluation_basis": evaluation.get("basis"),
            "evidence_class": classify_evidence(latest),
            "attempts": len(rows),
            "mixed": mixed,
            "disputed": bool(evaluation.get("dispute")),
            "reason": str(evaluation.get("reason") or "")[:MAX_REASON_CHARS] or None,
            "misconception_label": (evaluation.get("misconception") or {}).get("label"),
            "source_references": [
                {"source_id": r.get("source_id"), "pdf_page": r.get("pdf_page")}
                for r in latest.get("source_references") or [] if r.get("source_id")],
            "places": _places(latest, titles),
            "_order": number,
        })
    ranked = sorted(items, key=lambda i: (_RANK[i["standing"]], -i["_order"]))[:MAX_ITEMS]
    for item in ranked:
        item.pop("_order", None)
    tested = {i["capability"] for i in ranked}
    evaluated = sum(1 for a in attempts if a.get("evaluation"))
    limits = ["Each judgement is a provisional AI opinion about one answer, not a grade or a measure of mastery."]
    if len(attempts) < 3:
        limits.append("Fewer than three answers are recorded, so priorities are tentative.")
    if len(items) > MAX_ITEMS:
        limits.append(f"Only the {MAX_ITEMS} highest-priority questions are listed.")
    return {"status": "SOME", "attempt_count": len(attempts), "evaluated_count": evaluated, "items": ranked,
            "priority_order": [i["id"] for i in ranked],
            "untested_capabilities": [c for c in LEARNING_CAPABILITIES if c not in tested],
            "limits": limits}


def model_view(digest: dict[str, Any]) -> dict[str, Any] | None:
    """What a model may see: observations and the rule-based priority order; None when there is nothing."""
    if digest.get("status") != "SOME":
        return None
    keep = ("id", "task", "capability", "standing", "latest_outcome", "evidence_class", "attempts", "mixed",
            "disputed", "reason", "misconception_label", "source_references")
    return {
        "note": "Observed = facts about this student's recorded answers. priority_order is a rule-based "
                "suggestion, not a measure of ability. A missing capability is an evidence gap, not a weakness.",
        "attempt_count": digest["attempt_count"], "evaluated_count": digest["evaluated_count"],
        "items": [{k: i[k] for k in keep} for i in digest["items"]],
        "priority_order": digest["priority_order"],
        "untested_capabilities": digest["untested_capabilities"],
        "limits": digest["limits"],
    }


_TERMS = re.compile(r"[a-z0-9]+")
_STOP = frozenset("the a an of and or to in on for with is are was were what why how does do did this that these those "
                  "between about explain define difference understand really should".split())


def _terms(text: str) -> set[str]:
    return {t for t in _TERMS.findall((text or "").lower()) if len(t) >= 4 and t not in _STOP}


def relevant_to_topic(digest: dict[str, Any], topic: str, *, limit: int = 3) -> dict[str, Any]:
    """The part of a digest that bears on one TEACH topic: questions sharing at least one content term with it."""
    wanted = _terms(topic)
    picked = [i for i in digest.get("items", []) if wanted & (_terms(i["task"]) | _terms(i.get("topic") or ""))]
    if not picked:
        return {**digest, "status": "NONE", "items": [], "priority_order": []}
    picked = picked[:limit]
    return {**digest, "items": picked, "priority_order": [i["id"] for i in picked]}


def render_digest(digest: dict[str, Any]) -> str:
    """Plain-text 'what your recorded answers show' block. Deterministic: no model involved."""
    if digest.get("status") != "SOME":
        return ("No answers are recorded for this week yet, so this revision brief is general to the week's material "
                "and is not tailored to you. Take the quiz (or ask Tutor to test you) and Serapis will use what you "
                "answer to decide what to revise first.")
    lines = ["What your recorded answers show (observed)"]
    for item in digest["items"]:
        marker = f"- {STANDING_TEXT[item['standing']]} Question: {item['task']}"
        lines.append(marker)
        extras = []
        if item["attempts"] > 1:
            extras.append(f"{item['attempts']} attempts")
        if item.get("misconception_label"):
            extras.append(f"suspected misunderstanding: {item['misconception_label']}")
        if item["places"]:
            extras.append("see " + "; ".join(item["places"]))
        if extras:
            lines.append("  (" + "; ".join(extras) + ")")
    lines.append("")
    lines.append("What to do next (suggested from those answers, not a measure of how well you know the topic)")
    for number, item in enumerate((i for i in digest["items"] if i["standing"] != DEMONSTRATED), start=1):
        lines.append(f"{number}. {ACTIVITY[item['standing']]} ({_short(item['task'])})")
    done = [i for i in digest["items"] if i["standing"] == DEMONSTRATED]
    if done:
        lines.append(f"{len(done)} question(s) were answered well with no help; " + ACTIVITY[DEMONSTRATED].lower())
    if digest["untested_capabilities"]:
        lines.append("Not tested yet (an evidence gap, not a weakness): "
                     + ", ".join(c.lower() for c in digest["untested_capabilities"]) + ".")
    lines.extend(digest["limits"])
    return "\n".join(lines)


def render_teach_evidence(used: list[dict[str, Any]]) -> str | None:
    """One honest line per recorded answer that shaped a lesson; None when the lesson was not personalised."""
    if not used:
        return None
    lines = ["This explanation took these recorded answers of yours into account (observed):"]
    lines += [f"- {STANDING_TEXT[u['standing']]} Question: {u['task']}" for u in used]
    lines.append("It uses them only to choose where to start and how much worked detail to give. "
                 "They are single provisional judgements, not a measure of what you know.")
    return "\n".join(lines)
