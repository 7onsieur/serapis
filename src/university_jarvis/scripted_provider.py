"""A deterministic, offline stand-in for the AI provider.

``ScriptedStudyProvider`` implements the same ``ReasoningProvider`` boundary as the OpenAI provider
but never contacts any service and spends nothing. It exists so that the synthetic demonstration
and the end-to-end acceptance tests can drive every real Serapis code path (retrieval, validation,
provenance, persistence) repeatably.

It is **not an AI tutor** and its output must never be presented as one. It composes replies by
quoting the passages it is handed and by simple word-overlap rules, so its wording is plain and its
"judgements" are only a lexical heuristic. Everything it returns still has to pass the same
citation, grounding and integrity checks as a real model reply; if it did not, the tests would fail.
"""

from __future__ import annotations

import re
from typing import Any

IDENTITY = {"provider": "scripted-demo", "model": "deterministic-v1"}
_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset("a an and are as at be by for from in is it of on or that the their they this to was were what which with".split())


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2}


def _passages(context: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for source_context in context.get("source_contexts") or []:
        for excerpt in source_context.get("excerpts") or []:
            if isinstance(excerpt.get("pdf_page"), int) and (excerpt.get("text") or "").strip():
                found.append({"source_id": source_context["source_id"], "page": excerpt["pdf_page"],
                              "text": " ".join(excerpt["text"].split()), "title": excerpt.get("title")})
    return found


def _ref(passage: dict[str, Any]) -> dict[str, Any]:
    return {"source_id": passage["source_id"], "pdf_page": passage["page"]}


def _first_sentence(text: str, limit: int = 220) -> str:
    sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    return sentence if len(sentence) <= limit else sentence[:limit].rsplit(" ", 1)[0]


def _overlap(response: str, reference: str) -> float:
    wanted = _tokens(reference)
    return len(_tokens(response) & wanted) / len(wanted) if wanted else 0.0


def _gist(text: str, words: int = 8) -> str:
    return " ".join(text.split()[:words]).rstrip(".,;:")


class ScriptedStudyProvider:
    """Deterministic provider for demos and offline acceptance tests (no network, no cost)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_usage = None

    def cache_identity(self) -> dict[str, str]:
        return dict(IDENTITY)

    def generate_structured_output(self, context: dict[str, Any], instructions: str,
                                   output_format: dict[str, Any]) -> dict[str, Any]:
        name = output_format["name"]
        self.calls.append(name)
        handler = {
            "preparation_brief": self._sections,
            "teach_brief": self._teach,
            "quiz_brief": self._quiz,
            "learning_task": self._learning_task,
            "learning_evaluation": self._evaluation,
            "tutor_turn": self._tutor_turn,
            "tutor_question": self._tutor_question,
            "assignment_coach_turn": self._coach_turn,
        }.get(name, self._sections)
        return handler(context, output_format)

    # -- sectioned briefs (PREPARE, REVISE, AFTER_LECTURE, one-off assignment brief) -----------------------------
    def _sections(self, context: dict[str, Any], output_format: dict[str, Any]) -> dict[str, Any]:
        passages = _passages(context)
        fields = list(output_format["schema"]["properties"])
        out: dict[str, Any] = {}
        for index, field in enumerate(fields):
            if not passages:
                out[field] = []
                continue
            passage = passages[index % len(passages)]
            label = field.replace("_", " ")
            out[field] = [{"text": f"[Scripted demo] On {label}: the material says \"{_first_sentence(passage['text'], 160)}\"",
                           "provenance": [_ref(passage)]}]
        return out

    def _teach(self, context: dict[str, Any], _fmt: dict[str, Any]) -> dict[str, Any]:
        passages = _passages(context)
        if not passages:
            raise ValueError("scripted TEACH needs at least one supplied passage")
        first = passages[0]
        second = passages[1 % len(passages)]
        topic = (context.get("teach_request") or {}).get("topic") or "this idea"
        return {
            "direct_explanation": {"text": f"[Scripted demo] In short, for {topic}: {_first_sentence(first['text'])}", "provenance": [_ref(first)]},
            "teaching_sequence": [{"move_type": "build_understanding", "title": "Start from the source",
                                   "explanation": _first_sentence(second["text"]), "why_it_follows": None,
                                   "provenance": [_ref(second)]}],
            "mental_model": {"text": f"Hold onto this: {_gist(first['text'], 14)}.", "provenance": [_ref(first)]},
            "check_questions": [
                {"text": f"In your own words, what does the lecture mean by \"{_gist(first['text'], 5)}\"?", "provenance": [_ref(first)]},
                {"text": f"Why does the lecture say \"{_gist(second['text'], 5)}\"?", "provenance": [_ref(second)]}],
            "unknowns": ["Scripted demonstration content: it only restates the supplied slides."],
        }

    def _quiz(self, context: dict[str, Any], _fmt: dict[str, Any]) -> dict[str, Any]:
        passages = _passages(context)
        if not passages:
            raise ValueError("scripted QUIZ needs at least one supplied passage")
        kinds = [("recall", "What does the material state about \"{g}\"?"),
                 ("explanation", "Explain, in your own words, the idea behind \"{g}\"."),
                 ("application", "How could you apply the idea \"{g}\" to an organisation you know?"),
                 ("connection", "How does \"{g}\" connect to the rest of this week's material?")]
        questions, answers = [], []
        for index in range(6):  # QUIZ requires 6 to 8 questions covering all four kinds
            kind, template = kinds[index % len(kinds)]
            passage = passages[index % len(passages)]
            qid = f"q{index + 1}"
            questions.append({"question_id": qid, "question_type": kind,
                              "question": template.format(g=_gist(passage["text"], 6 + index // 4)), "provenance": [_ref(passage)]})
            answers.append({"question_id": qid, "answer": _first_sentence(passage["text"], 300), "provenance": [_ref(passage)]})
        return {"questions": questions, "answers": answers}

    def _learning_task(self, context: dict[str, Any], _fmt: dict[str, Any]) -> dict[str, Any]:
        passages = _passages(context)
        if not passages:
            raise ValueError("scripted learning task needs a passage")
        passage = passages[0]
        capability = str(context.get("capability", "recall")).lower()
        return {"task": f"Using the material, give a {capability} answer about \"{_gist(passage['text'], 6)}\".",
                "expected_answer_or_rubric": _first_sentence(passage["text"], 300), "source_references": [_ref(passage)]}

    def _evaluation(self, context: dict[str, Any], _fmt: dict[str, Any]) -> dict[str, Any]:
        reference = str(context.get("expected_answer_or_rubric") or "")
        score = _overlap(str(context.get("student_response") or ""), reference)
        outcome = "SUPPORTED" if score >= 0.5 else "PARTLY_SUPPORTED" if score >= 0.2 else "NOT_SUPPORTED"
        refs = context.get("source_references") or []
        evidence = [{"source_id": r["source_id"], "location": f"p. {r['pdf_page']}"} for r in refs[:1] if isinstance(r.get("pdf_page"), int)]
        return {"outcome": outcome, "evidence_references": evidence,
                "reason": f"[Scripted demo] Word overlap with the reference was {round(score * 100)}%. A real model would judge meaning, not words."}

    # -- tutor ---------------------------------------------------------------------------------------------------
    def _tutor_turn(self, context: dict[str, Any], _fmt: dict[str, Any]) -> dict[str, Any]:
        passages = _passages(context)
        if not passages:
            raise ValueError("scripted tutor needs a passage")
        action = context["action"]
        cite = [_ref(passages[0])]
        if action == "EXPLAIN":
            return {"message": "[Scripted demo] Start by re-reading the cited passage and asking how it relates to the question.",
                    "diagnosis": "none", "citations": cite, "misconception": None}
        if action == "HINT":
            return {"message": "[Scripted demo] Look again at the cited passage: which words in it answer the question?",
                    "diagnosis": "none", "citations": cite, "misconception": None}
        score = _overlap(str(context.get("student_response") or ""), str(context.get("expected_answer_or_rubric") or ""))
        diagnosis = "correct" if score >= 0.6 else "partial" if score >= 0.25 else "unclear"
        message = {"correct": "[Scripted demo] That lines up with the passage. Well done; try explaining why it matters.",
                   "partial": "[Scripted demo] You have part of it. Re-read the cited passage and add what is missing.",
                   "unclear": "[Scripted demo] I can't tell how this connects to the passage yet. Re-read it and try again."}[diagnosis]
        return {"message": message, "diagnosis": diagnosis, "citations": cite, "misconception": None}

    def _tutor_question(self, context: dict[str, Any], _fmt: dict[str, Any]) -> dict[str, Any]:
        passages = _passages(context)
        previous = " ".join(q["text"] for q in context.get("previous_questions", []))
        chosen = next((p for p in passages if _gist(p["text"], 6) not in previous), passages[-1] if passages else None)
        if chosen is None:
            raise ValueError("scripted tutor question needs a passage")
        return {"question": f"Which point does the material make about \"{_gist(chosen['text'], 6)}\"?",
                "expected_answer": _first_sentence(chosen["text"], 300), "citations": [_ref(chosen)], "calculation": None}

    # -- assignment coach ----------------------------------------------------------------------------------------
    def _coach_turn(self, context: dict[str, Any], _fmt: dict[str, Any]) -> dict[str, Any]:
        passages = _passages(context)
        criteria = [c["text"] for c in context.get("marking_criteria", [])]
        requirements = [r["text"] for r in context.get("requirements", [])]
        message_text = str(context.get("student_message") or "")
        top = max(passages, key=lambda p: len(_tokens(p["text"]) & _tokens(message_text)), default=None)
        parts = []
        follow_ups: list[str] = []
        needs: list[str] = []
        cites: list[dict[str, Any]] = []
        if context.get("shared_work"):
            parts.append("[Scripted demo] Thanks for sharing your own wording. I won't rewrite it. Check it against your criteria:")
            parts.append("\n".join(f"- Does it show: {c}?" for c in criteria[:3]) or "- You haven't added marking criteria yet, so I can't compare it to anything.")
            follow_ups.append("Which criterion does your passage address most weakly, and why?")
        elif top is not None:
            parts.append(f"[Scripted demo] Your course material says: \"{_first_sentence(top['text'], 200)}\"")
            cites.append(_ref(top))
            parts.append("Think about how that connects to what the assignment asks you to do.")
            follow_ups.append("Which requirement does this idea help you meet, and how?")
            needs.append("A specific example that supports this point")
        else:
            parts.append("[Scripted demo] I couldn't find anything in your course materials that matches that, so this is process advice only.")
            parts.append("Pick one requirement and write down, in your own words, what evidence it would need.")
            follow_ups.append("What would count as evidence for the first requirement?")
        if requirements:
            parts.append(f"Requirement to keep in view: {requirements[0]}")
        return {"message": "\n\n".join(parts), "follow_up_questions": follow_ups[:1], "evidence_needs": needs[:1], "citations": cites}
