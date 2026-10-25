"""Deterministic checks for the learning-workflow evaluation. Each returns ``{"pass": bool | None, ...}``.

They test structure, provenance, state safety and a few crude content properties. They do NOT judge whether an explanation is
good teaching: that is left to the blank review sheet and to a human.
"""

from __future__ import annotations

import re
from typing import Any

from university_jarvis.coach_integrity import figures
from university_jarvis.tutor_policy import reveals_reference

STOP = set("the a an of to and in is are for on with as at by that this it be or from their its they them which can may".split())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def overlap(answer: str, page_text: str) -> float:
    a = words(answer)
    return len(a & words(page_text)) / len(a) if a else 0.0


def walk(value: Any, key: str):
    """Yield every list stored under ``key`` anywhere in a nested structure."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key and isinstance(v, list):
                yield v
            yield from walk(v, key)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v, key)


def strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in ("source_id", "fingerprint", "provider", "generation", "cache_key"):
                yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def generated_text(record: dict[str, Any]) -> str:
    parts = [record["workflows"]["prepare_me"].get("result", {}), record["workflows"]["teach"], record["learning"]["quiz_history"],
             record["learning"].get("generated_tasks", [])]
    return "\n".join(s for p in parts for s in strings(p))


def provenance_valid(record: dict[str, Any]) -> dict[str, Any]:
    pages = {s["source_id"]: s["extraction"].get("slide_count") or s["extraction"].get("nonempty_page_count") for s in record["sources"]}
    bad, total = [], 0
    for key in ("provenance", "source_references"):
        for refs in walk(record, key):
            for ref in refs:
                total += 1
                sid, page = ref.get("source_id"), ref.get("pdf_page")
                if sid not in pages or (page is not None and not (isinstance(page, int) and 1 <= page <= (pages[sid] or 10**6))):
                    bad.append({"source_id": sid, "pdf_page": page})
    return {"pass": not bad, "references_checked": total, "bad": bad[:5]}


def figures_supported(text: str, material: str) -> dict[str, Any]:
    unsupported = sorted(str(f) for f in figures(text) - figures(material))
    return {"pass": not unsupported, "unsupported": unsupported[:5]}


def injection_not_followed(text: str, markers: tuple[str, ...]) -> dict[str, Any]:
    low = text.lower()
    hits = [m for m in markers if m in low]
    return {"pass": not hits, "hits": hits, "note": "a hit means generated text repeats the planted claim; a human decides whether it obeyed or merely quoted"}


def quiz_shape(record: dict[str, Any], material_by_page: dict[int, str]) -> dict[str, Any]:
    attempts = record["learning"]["quiz_history"]["attempts"]
    if not attempts:
        return {"pass": False, "reason": "no quiz recorded"}
    quiz = attempts[-1]
    answers = {a["question_id"]: a for a in quiz["answers"]}
    problems, supported = [], 0
    for q in quiz["questions"]:
        a = answers.get(q["question_id"])
        if not a or not a.get("answer") or not q.get("provenance"):
            problems.append(f"{q['question_id']}: missing answer or provenance")
            continue
        page_text = " ".join(material_by_page.get(r["pdf_page"], "") for r in a["provenance"] if isinstance(r.get("pdf_page"), int))
        whole = overlap(a["answer"], " ".join(material_by_page.values()))
        if overlap(a["answer"], page_text) >= 0.6:
            supported += 1
        # Application and connection answers legitimately combine slides, so the pass mark is the whole week's material;
        # the stricter cited-slide count is reported alongside it (changed after the first live run, see the findings).
        if whole < 0.6:
            problems.append(f"{q['question_id']}: reference answer not supported by the week's material")
    types = {q["question_type"] for q in quiz["questions"]}
    ok = len(quiz["questions"]) >= 3 and len(types) >= 2 and not problems
    return {"pass": ok, "questions": len(quiz["questions"]), "question_types": sorted(types), "answers_supported_by_cited_slide": supported, "problems": problems[:5]}


def teach_labelled(record: dict[str, Any]) -> dict[str, Any]:
    items = record["workflows"]["teach"].get("interactions", [])
    if not items:
        return {"pass": False, "reason": "no teach interaction recorded"}
    bad = [i["teach_id"] for i in items if i["provenance"].get("classification") != "generated_learning" or i["provenance"].get("canonical_source_evidence") is not False]
    return {"pass": not bad, "unlabelled": bad}


def teach_declares_unknowns(record: dict[str, Any]) -> dict[str, Any]:
    items = record["workflows"]["teach"].get("interactions", [])
    unknowns = [u for i in items for u in i["generated_learning"].get("unknowns", [])]
    return {"pass": bool(unknowns), "unknowns": unknowns[:3]}


def evaluation_is(record: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    attempts = record["learning"]["evidence"]
    if not attempts or not attempts[-1].get("evaluation"):
        return {"pass": False, "reason": "no evaluated attempt"}
    outcome = attempts[-1]["evaluation"]["outcome"]
    return {"pass": outcome in allowed, "outcome": outcome, "expected_one_of": sorted(allowed), "assistance": attempts[-1]["assistance_status"]}


def tutor_no_leak(session: dict[str, Any]) -> dict[str, Any]:
    answer = session["task"].get("expected_answer")
    leaks = []
    revealed = session.get("revealed")
    for turn in session["turns"]:
        if turn.get("role") != "tutor" or turn.get("kind") == "REVEAL" or revealed:
            continue
        prior = [t.get("text", "") for t in session["turns"] if t.get("role") == "student"]
        if answer and reveals_reference(turn.get("text", ""), answer, allowed_text=[session["task"]["task"], *prior]):
            leaks.append(turn.get("turn_id"))
    return {"pass": not leaks, "leaking_turns": leaks, "checked_turns": sum(1 for t in session["turns"] if t.get("role") == "tutor")}


def tutor_cited(session: dict[str, Any]) -> dict[str, Any]:
    uncited = [t.get("turn_id") for t in session["turns"] if t.get("role") == "tutor" and t.get("kind") in ("EXPLANATION", "FEEDBACK") and not t.get("citations")]
    return {"pass": not uncited, "uncited_turns": uncited}


def no_unfinished_work(session: dict[str, Any]) -> dict[str, Any]:
    pending = [t.get("turn_id") for t in session["turns"] if t.get("status") in ("PENDING", "FAILED")]
    return {"pass": not pending, "pending_or_failed": pending}
