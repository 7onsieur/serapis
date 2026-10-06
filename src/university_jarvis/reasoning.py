"""Minimal reasoning-provider boundary for source-grounded preparation briefs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Protocol

from .credentials import get_openai_api_key
from .sources import PROJECT_ROOT, render_source_location
from .state import StateError, personal_data_dir


DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
PREPARE_MAX_OUTPUT_TOKENS = 4_000
PREPARE_PROMPT_VERSION = "prepare-grounding-v2"
PREPARATION_SCHEMA_VERSION = 1
WORKFLOW_SCHEMA_VERSION = 1
TEACH_SCHEMA_VERSION = 2
TEACH_PROMPT_VERSION = "teach-tutoring-v1.1"
OBJECTIVE_INSTRUCTION_VERSION = "mission-objectives-v1"


OBJECTIVE_INSTRUCTIONS = """Use objective_context as shared decision guidance. Genuine learning
and academic integrity are hard constraints, not tradeable preferences. The cohort-position stretch
objective is not evidence of cohort position: never claim or infer a position unless
reliable_cohort_information_available is true. Do not invent missing academic or student-state
information. Prefer the smallest useful response and avoid unnecessary AI work.

Academic facts are explicitly grouped as CONFIRMED, NEEDS_VERIFICATION, or UNKNOWN. Treat only
CONFIRMED values as established academic facts. Describe NEEDS_VERIFICATION values as unverified
claims and UNKNOWN values as unknown. Never promote, reconcile, or change a fact's trust status."""


class ReasoningError(StateError):
    """Raised when a preparation brief cannot be generated or loaded."""

    def __init__(self, message: str, *, usage: "TokenUsage | None" = None) -> None:
        super().__init__(message)
        self.usage = usage


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    @classmethod
    def from_value(cls, value: Any) -> "TokenUsage | None":
        if value is None:
            return None
        getter = (
            value.get
            if isinstance(value, dict)
            else lambda key: getattr(value, key, None)
        )
        counts = tuple(
            getter(field)
            for field in ("input_tokens", "output_tokens", "total_tokens")
        )
        if not all(
            isinstance(count, int) and not isinstance(count, bool)
            for count in counts
        ):
            return None
        return cls(*counts)

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class SourceReference:
    source_id: str
    pdf_page: int | None


@dataclass(frozen=True)
class BriefItem:
    text: str
    provenance: list[SourceReference]


@dataclass(frozen=True)
class PreparationBrief:
    week_overview: list[BriefItem]
    before_class: list[BriefItem]
    core_concepts: list[BriefItem]
    examples_cases: list[BriefItem]
    lecture_attention: list[BriefItem]
    after_class_questions: list[BriefItem]
    assessment_connections: list[BriefItem]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PreparationBrief":
        expected = set(_SECTION_FIELDS)
        if not isinstance(value, dict) or set(value) != expected:
            raise ReasoningError("Preparation brief does not match the required seven sections")
        return cls(**{field: _parse_items(value[field], field) for field in _SECTION_FIELDS})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SectionWorkflow:
    name: str
    cache_name: str
    prompt_version: str
    sections: tuple[tuple[str, str], ...]
    instructions: str


@dataclass(frozen=True)
class SectionedBrief:
    sections: dict[str, list[BriefItem]]

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], workflow: SectionWorkflow
    ) -> "SectionedBrief":
        fields = tuple(field for field, _ in workflow.sections)
        if not isinstance(value, dict) or set(value) != set(fields):
            raise ReasoningError(
                f"{workflow.name} output does not match its required sections"
            )
        return cls({field: _parse_items(value[field], field) for field in fields})

    def to_dict(self) -> dict[str, Any]:
        return {
            field: [asdict(item) for item in items]
            for field, items in self.sections.items()
        }


@dataclass(frozen=True)
class TeachingMove:
    move_type: str
    title: str
    explanation: str
    why_it_follows: str | None
    provenance: list[SourceReference]


@dataclass(frozen=True)
class TeachBrief:
    direct_explanation: BriefItem
    teaching_sequence: list[TeachingMove]
    mental_model: BriefItem
    check_questions: list[BriefItem]
    unknowns: list[str]

    @classmethod
    def from_dict(
        cls, value: dict[str, Any], allowed_source_ids: set[str]
    ) -> "TeachBrief":
        expected = {
            "direct_explanation",
            "teaching_sequence",
            "mental_model",
            "check_questions",
            "unknowns",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ReasoningError("TEACH output does not match the required structure")
        direct_explanation = _parse_single_item(
            value["direct_explanation"], "direct_explanation"
        )
        mental_model = _parse_single_item(value["mental_model"], "mental_model")
        check_questions = _parse_items(value["check_questions"], "check_questions")
        if not 2 <= len(check_questions) <= 4:
            raise ReasoningError("TEACH must contain 2 to 4 unscored check questions")
        raw_sequence = value["teaching_sequence"]
        if not isinstance(raw_sequence, list) or not raw_sequence:
            raise ReasoningError("TEACH teaching_sequence must not be empty")
        teaching_sequence = [
            _parse_teaching_move(item, index)
            for index, item in enumerate(raw_sequence, start=1)
        ]
        references = [
            direct_explanation,
            mental_model,
            *check_questions,
            *teaching_sequence,
        ]
        for item in references:
            provenance = item.provenance
            if not provenance:
                raise ReasoningError("TEACH source-supported content has no provenance")
            if any(
                reference.source_id not in allowed_source_ids
                for reference in provenance
            ):
                raise ReasoningError(
                    "TEACH output cites a source outside the requested module/week"
                )
        unknowns = value["unknowns"]
        if not isinstance(unknowns, list) or not all(
            isinstance(item, str) and item.strip() for item in unknowns
        ):
            raise ReasoningError("TEACH unknowns must be a list of non-empty strings")
        return cls(
            direct_explanation=direct_explanation,
            teaching_sequence=teaching_sequence,
            mental_model=mental_model,
            check_questions=check_questions,
            unknowns=unknowns,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuizQuestion:
    question_id: str
    question_type: str
    question: str
    provenance: list[SourceReference]


@dataclass(frozen=True)
class QuizAnswer:
    question_id: str
    answer: str
    provenance: list[SourceReference]


@dataclass(frozen=True)
class QuizBrief:
    questions: list[QuizQuestion]
    answers: list[QuizAnswer]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QuizBrief":
        if not isinstance(value, dict) or set(value) != {"questions", "answers"}:
            raise ReasoningError("QUIZ output does not match the required structure")
        if not isinstance(value["questions"], list) or not isinstance(
            value["answers"], list
        ):
            raise ReasoningError("QUIZ questions and answers must be lists")
        if not 6 <= len(value["questions"]) <= 8 or len(value["answers"]) != len(
            value["questions"]
        ):
            raise ReasoningError("QUIZ must contain 6 to 8 matched questions and answers")
        questions = []
        for raw in value["questions"]:
            if not isinstance(raw, dict) or set(raw) != {
                "question_id",
                "question_type",
                "question",
                "provenance",
            }:
                raise ReasoningError("Invalid QUIZ question")
            if raw["question_type"] not in {"recall", "explanation", "application", "connection"}:
                raise ReasoningError("Invalid QUIZ question type")
            questions.append(
                QuizQuestion(
                    question_id=_require_string(raw["question_id"], "question_id"),
                    question_type=raw["question_type"],
                    question=_require_string(raw["question"], "question"),
                    provenance=_parse_references(raw["provenance"], "questions"),
                )
            )
        answers = []
        for raw in value["answers"]:
            if not isinstance(raw, dict) or set(raw) != {
                "question_id",
                "answer",
                "provenance",
            }:
                raise ReasoningError("Invalid QUIZ answer")
            answers.append(
                QuizAnswer(
                    question_id=_require_string(raw["question_id"], "question_id"),
                    answer=_require_string(raw["answer"], "answer"),
                    provenance=_parse_references(raw["provenance"], "answers"),
                )
            )
        question_ids = {question.question_id for question in questions}
        answer_ids = {answer.question_id for answer in answers}
        if (
            len(question_ids) != len(questions)
            or len(answer_ids) != len(answers)
            or question_ids != answer_ids
        ):
            raise ReasoningError("QUIZ questions and answers do not match")
        if {question.question_type for question in questions} != {
            "recall",
            "explanation",
            "application",
            "connection",
        }:
            raise ReasoningError("QUIZ must cover all required question types")
        return cls(questions=questions, answers=answers)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECTION_FIELDS = (
    "week_overview",
    "before_class",
    "core_concepts",
    "examples_cases",
    "lecture_attention",
    "after_class_questions",
    "assessment_connections",
)

_SECTION_TITLES = (
    ("week_overview", "What this week is about"),
    ("before_class", "What I should understand before class"),
    ("core_concepts", "Core concepts"),
    ("examples_cases", "Important examples/cases"),
    ("lecture_attention", "What to pay particular attention to in the lecture"),
    ("after_class_questions", "Questions I should be able to answer afterwards"),
    ("assessment_connections", "Assessment connections"),
)

_TEACH_MOVE_TYPES = (
    "build_understanding",
    "contrast",
    "reasoning_step",
    "worked_example",
    "likely_confusion",
    "supported_connection",
    "assessment_connection",
)

_REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "pdf_page": {"type": ["integer", "null"]},
    },
    "required": ["source_id", "pdf_page"],
    "additionalProperties": False,
}

_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "provenance": {"type": "array", "items": _REFERENCE_SCHEMA},
    },
    "required": ["text", "provenance"],
    "additionalProperties": False,
}

_TEACH_MOVE_SCHEMA = {
    "type": "object",
    "properties": {
        "move_type": {"type": "string", "enum": list(_TEACH_MOVE_TYPES)},
        "title": {"type": "string"},
        "explanation": {"type": "string"},
        "why_it_follows": {"type": ["string", "null"]},
        "provenance": {"type": "array", "items": _REFERENCE_SCHEMA},
    },
    "required": [
        "move_type",
        "title",
        "explanation",
        "why_it_follows",
        "provenance",
    ],
    "additionalProperties": False,
}

PREPARATION_BRIEF_FORMAT = {
    "type": "json_schema",
    "name": "preparation_brief",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            field: {"type": "array", "items": _ITEM_SCHEMA}
            for field in _SECTION_FIELDS
        },
        "required": list(_SECTION_FIELDS),
        "additionalProperties": False,
    },
}

TEACH_FORMAT = {
    "type": "json_schema",
    "name": "teach_brief",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "direct_explanation": _ITEM_SCHEMA,
            "teaching_sequence": {
                "type": "array",
                "items": _TEACH_MOVE_SCHEMA,
            },
            "mental_model": _ITEM_SCHEMA,
            "check_questions": {"type": "array", "items": _ITEM_SCHEMA},
            "unknowns": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "direct_explanation",
            "teaching_sequence",
            "mental_model",
            "check_questions",
            "unknowns",
        ],
        "additionalProperties": False,
    },
}

GROUNDING_INSTRUCTIONS = """Create a concise PREPARE_ME teaching brief for use before class.
The supplied university sources are authoritative. Do not silently introduce unsupported academic
claims. Keep lecture material and assigned reading distinguishable where relevant. Attach the given
source_id and PDF page to claims and examples wherever practical; do not infer academic pagination
from PDF numbering. Identify missing information rather than inventing it. Synthesise and teach,
rather than merely summarising, and prioritise what is useful before the lecture. Make assessment
connections only when supported by the supplied module or assessment context. Do not write assessed
work for submission. Use no outside knowledge, web content, or tools. Keep every section concise.
Target 1 to 3 concise items per section where appropriate. Avoid unnecessary repetition, while
preserving academic usefulness, explanation, source grounding, and genuinely useful distinctions.
"""


def _sectioned_format(workflow: SectionWorkflow) -> dict[str, Any]:
    fields = [field for field, _ in workflow.sections]
    return {
        "type": "json_schema",
        "name": workflow.cache_name,
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                field: {"type": "array", "items": _ITEM_SCHEMA} for field in fields
            },
            "required": fields,
            "additionalProperties": False,
        },
    }


_QUIZ_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "question_id": {"type": "string"},
        "question_type": {
            "type": "string",
            "enum": ["recall", "explanation", "application", "connection"],
        },
        "question": {"type": "string"},
        "provenance": {"type": "array", "items": _REFERENCE_SCHEMA},
    },
    "required": ["question_id", "question_type", "question", "provenance"],
    "additionalProperties": False,
}

_QUIZ_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "question_id": {"type": "string"},
        "answer": {"type": "string"},
        "provenance": {"type": "array", "items": _REFERENCE_SCHEMA},
    },
    "required": ["question_id", "answer", "provenance"],
    "additionalProperties": False,
}

QUIZ_FORMAT = {
    "type": "json_schema",
    "name": "quiz_brief",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": _QUIZ_QUESTION_SCHEMA,
            },
            "answers": {
                "type": "array",
                "items": _QUIZ_ANSWER_SCHEMA,
            },
        },
        "required": ["questions", "answers"],
        "additionalProperties": False,
    },
}


AFTER_LECTURE_WORKFLOW = SectionWorkflow(
    name="AFTER_LECTURE",
    cache_name="after_lecture_brief",
    prompt_version="after-lecture-grounding-v1",
    sections=(
        ("what_was_taught", "What was taught"),
        ("core_concepts", "Core concepts I should now understand"),
        ("examples_cases", "Important examples/cases"),
        ("lecturer_emphasis", "Lecturer emphasis or assessment-relevant points"),
        ("lecture_reading_connections", "Connections between the lecture and assigned reading"),
        ("review_or_clarify", "What I should review or clarify"),
        ("understanding_questions", "Questions to test my understanding"),
        ("assessment_connections", "Assessment connections"),
    ),
    instructions="""Create a concise AFTER_LECTURE consolidation brief from only the supplied
university context. Distinguish lecture material from assigned reading and preserve source_id/PDF
page provenance wherever practical. Never invent lecturer comments or emphasis: if it is not present
in the supplied material, explicitly say it cannot be determined. Identify other missing information
rather than assuming it. Consolidate and test understanding, and do not write assessed work for
submission. Use no outside knowledge, web content, or tools.""",
)

TEACH_INSTRUCTIONS = """Act as a patient, adaptive tutor for the single concept in teach_request,
using only claims supported by the supplied university source_contexts. Begin direct_explanation with
a simple answer to the requested topic or captured confusion, rather than a generic topic overview.
Then use teaching_sequence as an ordered path from simple to deeper understanding. Select only the
pedagogical moves that help this concept: break reasoning into steps; explicitly contrast easily
confused concepts; explain why a relationship or conclusion follows; anticipate a likely confusion;
or connect to the module or assessment when the supplied sources genuinely support it. Do not force
every move type into every response.

When a source supplies an example or case, a worked_example must walk through what happens, which
source-supported concept applies, and why the example demonstrates that concept; do not merely name
or summarise the case. For contrast, reasoning_step, worked_example, supported_connection, and
assessment_connection moves, why_it_follows must explicitly give the supported reasoning. Finish with
a concise mental_model the student can use to organise the idea, then provide 2 to 4 unscored
retrieval or self-explanation questions. Never claim or imply that the student now understands it.

The cached PREPARE_ME material may guide emphasis and structure, but it is not a new source:
citations must refer to identified university source IDs. student_context is the student's own report
and may be used only to determine what needs explaining; directly address it, but never present it as
an official-source claim. State genuinely unsupported or missing points in unknowns instead of using
general model knowledge, external examples, analogies, web content, or tools. Every source-supported
item and teaching move must cite at least one supplied university source_id and PDF page where
available. Do not write assessed work for submission."""

REVISE_WORKFLOW = SectionWorkflow(
    name="REVISE",
    cache_name="revise_brief",
    prompt_version="revise-grounding-v1",
    sections=(
        ("essential_knowledge", "Essential knowledge"),
        ("concepts_definitions", "Key concepts/definitions"),
        ("important_examples", "Important examples"),
        ("concept_connections", "Connections between concepts"),
        ("recall_questions", "High-value recall questions"),
        ("areas_to_revisit", "Areas worth revisiting"),
        ("assessment_relevance", "Assessment relevance"),
    ),
    instructions="""Create a concise revision brief from only the supplied university sources.
Prioritise essential, high-value knowledge over trivia. Distinguish lecture and assigned reading where
relevant, preserve source_id/PDF page provenance, and state when information cannot be determined.
Assessment relevance must be supported by the supplied context. Do not write assessed work for
submission. Use no outside knowledge, web content, or tools.""",
)

ASSIGNMENT_WORKFLOW = SectionWorkflow(
    name="ASSIGNMENT_COACH",
    cache_name="assignment_coach_brief",
    prompt_version="assignment-coach-grounding-v1",
    sections=(
        ("assignment_request", "What the assignment is asking"),
        ("deliverables_constraints", "Deliverables and constraints"),
        ("marking_criteria", "Marking criteria"),
        ("relevant_material", "Relevant concepts/source material"),
        ("planning_questions", "Planning questions"),
        ("work_stages", "Suggested work stages"),
        ("evidence_needs", "Evidence/research needs"),
        ("risks_mistakes", "Risks or common mistakes"),
        ("next_actions", "Next actions"),
    ),
    instructions="""Act only as an academic-integrity-preserving ASSIGNMENT COACH. Use the supplied
assessment state and university sources as authoritative. You may explain the brief and concepts,
interpret marking criteria, identify relevant course material, ask planning questions, suggest research
directions, and structure the student's process. You must not produce a finished assignment response,
write assessed work for submission as if authored by the student, fabricate evidence or references,
or invent requirements. Explicitly identify anything missing rather than filling gaps with assumptions.
Retain source_id/PDF page provenance wherever practical. Use no outside knowledge, web content, or tools.""",
)

QUIZ_PROMPT_VERSION = "quiz-grounding-v1"
QUIZ_INSTRUCTIONS = """Create 6 to 8 useful questions that test understanding of only the supplied
week's university sources, not trivia. Include recall, explanation, application, and connection
questions. Keep answers separate from questions and match them using question_id. Preserve source_id
and PDF page provenance. State limitations in an answer rather than inventing missing information.
Do not create assessed work for submission. Use no outside knowledge, web content, or tools."""


class ReasoningProvider(Protocol):
    """Provider-neutral boundary used by academic workflows."""

    def cache_identity(self) -> dict[str, str]: ...

    def generate_structured_output(
        self,
        context: dict[str, Any],
        instructions: str,
        output_format: dict[str, Any],
    ) -> dict[str, Any]: ...


class OpenAIReasoningProvider:
    """Responses API implementation of the reasoning boundary."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("JARVIS_REASONING_MODEL", DEFAULT_OPENAI_MODEL)
        self.last_usage: TokenUsage | None = None

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "openai", "model": self.model}

    def generate_structured_output(
        self,
        context: dict[str, Any],
        instructions: str,
        output_format: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_usage = None
        api_key = get_openai_api_key()
        if not api_key:
            raise ReasoningError(
                "Reasoning cannot run because no OpenAI API credential is configured in OPENAI_API_KEY or macOS Keychain. For this AI action, install the optional AI extra and configure OPENAI_API_KEY; local setup and Hub features remain available without it."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ReasoningError(
                "The OpenAI SDK is not installed. Run `pip install -e '.[ai]'` to enable AI study actions."
            ) from exc

        request = {
            "model": self.model,
            "instructions": instructions,
            "input": json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            "text": {"format": output_format},
        }
        if context.get("workflow") == "PREPARE_ME":
            request["max_output_tokens"] = PREPARE_MAX_OUTPUT_TOKENS

        try:
            response = OpenAI(api_key=api_key, max_retries=0).responses.create(**request)
        except Exception as exc:
            raise ReasoningError(
                "OpenAI reasoning request failed before a response was received"
            ) from exc

        self.last_usage = TokenUsage.from_value(getattr(response, "usage", None))
        status = getattr(response, "status", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete_details, "reason", None)

        if status == "incomplete":
            if incomplete_reason == "max_output_tokens":
                raise ReasoningError(
                    "OpenAI reasoning response was truncated at the output-token limit",
                    usage=self.last_usage,
                )
            if incomplete_reason == "content_filter":
                message = "OpenAI reasoning response was interrupted by the content filter"
            else:
                message = "OpenAI reasoning response was incomplete for another provider reason"
            raise ReasoningError(message, usage=self.last_usage)

        if status != "completed":
            if status in {"failed", "cancelled", "in_progress", "queued"}:
                message = f"OpenAI reasoning response ended with provider status: {status}"
            else:
                message = "OpenAI reasoning response returned an unrecognised provider status"
            raise ReasoningError(message, usage=self.last_usage)

        for output_item in getattr(response, "output", None) or ():
            if getattr(output_item, "type", None) != "message":
                continue
            for content_item in getattr(output_item, "content", None) or ():
                if getattr(content_item, "type", None) == "refusal":
                    raise ReasoningError(
                        "OpenAI reasoning response contained a refusal instead of structured output",
                        usage=self.last_usage,
                    )

        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise ReasoningError(
                "OpenAI reasoning response completed without structured output",
                usage=self.last_usage,
            )

        try:
            return json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise ReasoningError(
                "OpenAI reasoning response completed with malformed structured JSON",
                usage=self.last_usage,
            ) from exc

    def generate_prepare_brief(self, context: dict[str, Any]) -> PreparationBrief:
        """Compatibility entry point for the original PREPARE_ME boundary."""
        return PreparationBrief.from_dict(
            self.generate_structured_output(
                context, GROUNDING_INSTRUCTIONS, PREPARATION_BRIEF_FORMAT
            )
        )


@dataclass(frozen=True)
class PreparationResult:
    brief: Any
    cache_status: str
    cache_key: str
    usage: TokenUsage | None = None


def _parse_items(value: Any, field: str) -> list[BriefItem]:
    if not isinstance(value, list):
        raise ReasoningError(f"Preparation brief section is not a list: {field}")
    items = []
    for raw_item in value:
        if not isinstance(raw_item, dict) or set(raw_item) != {"text", "provenance"}:
            raise ReasoningError(f"Invalid preparation brief item in: {field}")
        if not isinstance(raw_item["text"], str) or not isinstance(
            raw_item["provenance"], list
        ):
            raise ReasoningError(f"Invalid preparation brief item in: {field}")
        references = _parse_references(raw_item["provenance"], field)
        items.append(BriefItem(text=raw_item["text"], provenance=references))
    return items


def _parse_single_item(value: Any, field: str) -> BriefItem:
    items = _parse_items([value], field)
    return items[0]


def _parse_teaching_move(value: Any, index: int) -> TeachingMove:
    expected = {
        "move_type",
        "title",
        "explanation",
        "why_it_follows",
        "provenance",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ReasoningError(f"Invalid TEACH teaching move: {index}")
    move_type = value["move_type"]
    if move_type not in _TEACH_MOVE_TYPES:
        raise ReasoningError(f"Invalid TEACH move type: {move_type}")
    why_it_follows = value["why_it_follows"]
    if why_it_follows is not None and not (
        isinstance(why_it_follows, str) and why_it_follows.strip()
    ):
        raise ReasoningError(f"Invalid TEACH reasoning in move: {index}")
    reasoning_required = {
        "contrast",
        "reasoning_step",
        "worked_example",
        "supported_connection",
        "assessment_connection",
    }
    if move_type in reasoning_required and why_it_follows is None:
        raise ReasoningError(f"TEACH move requires explicit reasoning: {move_type}")
    return TeachingMove(
        move_type=move_type,
        title=_require_string(value["title"], "teaching move title"),
        explanation=_require_string(
            value["explanation"], "teaching move explanation"
        ),
        why_it_follows=why_it_follows,
        provenance=_parse_references(value["provenance"], "teaching_sequence"),
    )


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReasoningError(f"Invalid string field: {field}")
    return value


def _parse_references(value: Any, field: str) -> list[SourceReference]:
    if not isinstance(value, list):
        raise ReasoningError(f"Invalid source provenance in: {field}")
    references = []
    for raw_reference in value:
        if not isinstance(raw_reference, dict) or set(raw_reference) != {
            "source_id",
            "pdf_page",
        }:
            raise ReasoningError(f"Invalid source provenance in: {field}")
        source_id = raw_reference["source_id"]
        pdf_page = raw_reference["pdf_page"]
        if not isinstance(source_id, str) or not (
            pdf_page is None or isinstance(pdf_page, int)
        ):
            raise ReasoningError(f"Invalid source provenance in: {field}")
        references.append(SourceReference(source_id=source_id, pdf_page=pdf_page))
    return references


def _trusted_fact_groups(
    owner: dict[str, Any], field_names: tuple[str, ...], source_by_id: dict[str, dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "confirmed": [],
        "needs_verification": [],
        "unknown": [],
    }
    metadata = owner.get("fact_provenance", {})
    for field in field_names:
        fact = metadata.get(field, {"status": "UNKNOWN", "evidence": []})
        status = fact.get("status", "UNKNOWN")
        group = {
            "CONFIRMED": "confirmed",
            "NEEDS_VERIFICATION": "needs_verification",
            "UNKNOWN": "unknown",
        }.get(status, "unknown")
        item: dict[str, Any] = {"field": field, "status": status}
        if group != "unknown" and field in owner:
            item["value"] = owner[field]
        evidence = []
        for reference in fact.get("evidence", []):
            source_id = reference.get("source_id")
            source = source_by_id.get(source_id, {})
            evidence_item = {"source_id": source_id}
            if reference.get("location"):
                evidence_item["location"] = reference["location"]
            if source.get("source_class"):
                evidence_item["source_class"] = source["source_class"]
            if source.get("title"):
                evidence_item["title"] = source["title"]
            evidence.append(evidence_item)
        item["evidence"] = evidence
        groups[group].append(item)
    return groups


def _fact_evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if "status" in value and "evidence" in value and isinstance(value["evidence"], list):
            found.update(
                ref.get("source_id")
                for ref in value["evidence"]
                if isinstance(ref, dict) and isinstance(ref.get("source_id"), str)
            )
        for child in value.values():
            found.update(_fact_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_fact_evidence_ids(child))
    return found


def build_reasoning_context(context: dict[str, Any]) -> dict[str, Any]:
    """Expose only selected state and bounded academic context to a provider."""
    sources = []
    for source in context["sources"]:
        sources.append(
            {
                key: source.get(key)
                for key in ("id", "type", "title", "authors", "pages", "source_class", "extraction")
                if source.get(key) is not None
            }
        )
    source_by_id = {
        source["id"]: source
        for source in context.get("truth_sources", context.get("sources", []))
        if source.get("id")
    }
    module = context["module"]
    module_facts = _trusted_fact_groups(
        module, ("code", "title", "semester", "academic_year"), source_by_id
    )
    assessment_facts = []
    for assessment in context.get("assessments", []):
        assessment_facts.append(
            {
                "assessment_id": assessment.get("id"),
                "facts": _trusted_fact_groups(
                    assessment,
                    ("title", "deadline", "deadline_status", "weight_percent", "requirements"),
                    source_by_id,
                ),
            }
        )
    referenced_fact_sources = _fact_evidence_ids({
        "module_facts": module_facts,
        "assessment_facts": assessment_facts,
    })
    supplied_source_ids = {source["id"] for source in context.get("sources", [])}
    fact_evidence_sources = []
    for source_id in sorted(referenced_fact_sources):
        source = source_by_id.get(source_id)
        if source is None:
            continue
        fact_evidence_sources.append({
            key: source.get(key)
            for key in ("id", "type", "title", "authors", "pages", "source_class")
            if source.get(key) is not None
        })
    reasoning_context = {
        "workflow": context["workflow"],
        "objective_context": context["objective_context"],
        # This is a local selection key, not an assertion that the identifier
        # has been institutionally verified. Consequential details are below.
        "workflow_scope": {
            "module_key": module["code"],
            "week": context.get("week", {}).get("number"),
        },
        "module_facts": module_facts,
        "assessment_facts": assessment_facts,
        "sources": sources,
        "fact_evidence_sources": fact_evidence_sources,
        "source_contexts": context["source_contexts"],
    }
    for key in (
        "week",
        "weeks",
        "items",
        "teach_request",
        "prepare_me",
        "student_context",
    ):
        if key in context:
            reasoning_context[key] = context[key]
    return reasoning_context


def _validate_citation_ids(value: Any, allowed_source_ids: set[str]) -> None:
    """Reject citations not present in the source metadata/context sent to the provider."""
    if isinstance(value, dict):
        provenance = value.get("provenance")
        if isinstance(provenance, list):
            for reference in provenance:
                if isinstance(reference, dict):
                    source_id = reference.get("source_id")
                    if source_id not in allowed_source_ids:
                        raise ReasoningError(
                            f"Generated output cited a source not supplied to this workflow: {source_id!r}"
                        )
        for child in value.values():
            _validate_citation_ids(child, allowed_source_ids)
    elif isinstance(value, list):
        for child in value:
            _validate_citation_ids(child, allowed_source_ids)


def _cache_key(
    reasoning_context: dict[str, Any],
    provider: ReasoningProvider,
    prompt_version: str,
    schema_version: int,
) -> str:
    identity = {
        "module": reasoning_context["workflow_scope"]["module_key"],
        "workflow": reasoning_context["workflow"],
        "reasoning_context": reasoning_context,
        "prompt_version": prompt_version,
        "objective_instruction_version": OBJECTIVE_INSTRUCTION_VERSION,
        "schema_version": schema_version,
        "provider": provider.cache_identity(),
    }
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def default_cache_dir(cache_name: str = "prepare") -> Path:
    configured = os.environ.get("JARVIS_CACHE_DIR")
    legacy = PROJECT_ROOT / ".jarvis-cache"
    root = Path(configured) if configured else (legacy if legacy.exists() else personal_data_dir() / "cache")
    return root / cache_name


def _load_cached_result(
    cache_path: Path,
    cache_key: str,
    parser: Callable[[dict[str, Any]], Any],
) -> PreparationResult:
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("cache_key") != cache_key:
            raise ReasoningError("Cached workflow key does not match its filename")
        brief = parser(cached["brief"])
        usage = TokenUsage.from_value(cached.get("usage"))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ReasoningError) as exc:
        raise ReasoningError(f"Invalid academic workflow cache: {cache_path}") from exc
    return PreparationResult(
        brief=brief,
        cache_status="cached",
        cache_key=cache_key,
        usage=usage,
    )


def _generate_cached(
    reasoning_context: dict[str, Any],
    provider: ReasoningProvider,
    *,
    cache_name: str,
    prompt_version: str,
    schema_version: int,
    instructions: str,
    output_format: dict[str, Any],
    parser: Callable[[dict[str, Any]], Any],
    serializer: Callable[[Any], dict[str, Any]],
    cache_dir: Path | None,
) -> PreparationResult:
    cache_key = _cache_key(
        reasoning_context, provider, prompt_version, schema_version
    )
    target_dir = cache_dir or default_cache_dir(cache_name)
    cache_path = target_dir / f"{cache_key}.json"

    allowed_source_ids = {source["id"] for source in reasoning_context.get("sources", [])}

    def checked_parser(raw: dict[str, Any]) -> Any:
        _validate_citation_ids(raw, allowed_source_ids)
        return parser(raw)

    if cache_path.is_file():
        return _load_cached_result(cache_path, cache_key, checked_parser)

    raw_brief = provider.generate_structured_output(
        reasoning_context,
        f"{OBJECTIVE_INSTRUCTIONS}\n\n{instructions}",
        output_format,
    )
    usage = getattr(provider, "last_usage", None)
    if not isinstance(usage, TokenUsage):
        usage = None
    try:
        brief = checked_parser(raw_brief)
    except ReasoningError as exc:
        raise ReasoningError(str(exc), usage=usage) from exc
    target_dir.mkdir(parents=True, exist_ok=True)
    cache_record = {
        "cache_key": cache_key,
        "prompt_version": prompt_version,
        "objective_instruction_version": OBJECTIVE_INSTRUCTION_VERSION,
        "schema_version": schema_version,
        "provider": provider.cache_identity(),
        "usage": usage.to_dict() if usage else None,
        "brief": serializer(brief),
    }
    temporary_path = cache_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(cache_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(cache_path)
    return PreparationResult(
        brief=brief,
        cache_status="generated",
        cache_key=cache_key,
        usage=usage,
    )


def generate_prepare_brief(
    context: dict[str, Any],
    provider: ReasoningProvider,
    cache_dir: Path | None = None,
) -> PreparationResult:
    """Load a matching preparation or invoke the provider once and cache it."""
    reasoning_context = build_reasoning_context(context)
    return _generate_cached(
        reasoning_context,
        provider,
        cache_name="prepare",
        prompt_version=PREPARE_PROMPT_VERSION,
        schema_version=PREPARATION_SCHEMA_VERSION,
        instructions=GROUNDING_INSTRUCTIONS,
        output_format=PREPARATION_BRIEF_FORMAT,
        parser=PreparationBrief.from_dict,
        serializer=lambda brief: brief.to_dict(),
        cache_dir=cache_dir,
    )


def load_cached_prepare_brief(
    context: dict[str, Any],
    provider: ReasoningProvider,
    cache_dir: Path | None = None,
) -> PreparationResult:
    """Load one matching PREPARE_ME result without invoking the provider."""
    reasoning_context = build_reasoning_context(context)
    cache_key = _cache_key(
        reasoning_context,
        provider,
        PREPARE_PROMPT_VERSION,
        PREPARATION_SCHEMA_VERSION,
    )
    target_dir = cache_dir or default_cache_dir("prepare")
    cache_path = target_dir / f"{cache_key}.json"
    if not cache_path.is_file():
        raise ReasoningError(
            "No matching cached PREPARE_ME result; run prepare explicitly before "
            "building the academic workspace"
        )
    allowed_source_ids = {source["id"] for source in reasoning_context.get("sources", [])}
    return _load_cached_result(
        cache_path,
        cache_key,
        lambda raw: _validate_citation_ids(raw, allowed_source_ids) or PreparationBrief.from_dict(raw),
    )


def generate_sectioned_brief(
    context: dict[str, Any],
    provider: ReasoningProvider,
    workflow: SectionWorkflow,
    cache_dir: Path | None = None,
) -> PreparationResult:
    reasoning_context = build_reasoning_context(context)
    return _generate_cached(
        reasoning_context,
        provider,
        cache_name=workflow.cache_name,
        prompt_version=workflow.prompt_version,
        schema_version=WORKFLOW_SCHEMA_VERSION,
        instructions=workflow.instructions,
        output_format=_sectioned_format(workflow),
        parser=lambda value: SectionedBrief.from_dict(value, workflow),
        serializer=lambda brief: brief.to_dict(),
        cache_dir=cache_dir,
    )


def generate_quiz_brief(
    context: dict[str, Any],
    provider: ReasoningProvider,
    cache_dir: Path | None = None,
) -> PreparationResult:
    reasoning_context = build_reasoning_context(context)
    return _generate_cached(
        reasoning_context,
        provider,
        cache_name="quiz_brief",
        prompt_version=QUIZ_PROMPT_VERSION,
        schema_version=WORKFLOW_SCHEMA_VERSION,
        instructions=QUIZ_INSTRUCTIONS,
        output_format=QUIZ_FORMAT,
        parser=QuizBrief.from_dict,
        serializer=lambda brief: brief.to_dict(),
        cache_dir=cache_dir,
    )


def generate_teach_brief(
    context: dict[str, Any],
    provider: ReasoningProvider,
    cache_dir: Path | None = None,
) -> PreparationResult:
    """Generate or load one source-grounded, student-targeted TEACH response."""
    reasoning_context = build_reasoning_context(context)
    allowed_source_ids = {source["id"] for source in reasoning_context["sources"]}
    if not allowed_source_ids:
        raise ReasoningError("TEACH requires at least one configured university source")
    return _generate_cached(
        reasoning_context,
        provider,
        cache_name="teach_brief",
        prompt_version=TEACH_PROMPT_VERSION,
        schema_version=TEACH_SCHEMA_VERSION,
        instructions=TEACH_INSTRUCTIONS,
        output_format=TEACH_FORMAT,
        parser=lambda value: TeachBrief.from_dict(value, allowed_source_ids),
        serializer=lambda brief: brief.to_dict(),
        cache_dir=cache_dir,
    )


def build_source_location_index(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map each source_id to its extraction method and any known per-unit titles.

    Built once from a workflow's own ``context`` (never persisted, never part
    of the reasoning cache key) and passed to a render function so citations
    can say "Slide N (Title)" for a PPTX source instead of misreporting every
    source as a PDF page. Source-context excerpt titles are only available
    for the run that generated them; a later render of the same cached brief
    without that context still gets the correct PDF-vs-slide label from
    ``extraction.method`` alone, just without the optional title.
    """
    index: dict[str, dict[str, Any]] = {}
    for source in context.get("sources", []):
        source_id = source.get("id")
        if not source_id:
            continue
        method = (source.get("extraction") or {}).get("method")
        index[source_id] = {"method": method, "titles": {}}
    for source_context in context.get("source_contexts", []) or []:
        source_id = source_context.get("source_id")
        entry = index.setdefault(source_id, {"method": None, "titles": {}})
        for excerpt in source_context.get("excerpts", []) or []:
            unit_number = excerpt.get("pdf_page")
            title = excerpt.get("title")
            if unit_number is not None and title:
                entry["titles"][unit_number] = title
    return index


def render_prepare_brief(
    brief: PreparationBrief, location_index: dict[str, dict[str, Any]] | None = None
) -> str:
    """Render the typed seven-section brief for terminal use."""
    lines = []
    for number, (field, title) in enumerate(_SECTION_TITLES, start=1):
        lines.append(f"{number}. {title}")
        lines.extend(_render_items(getattr(brief, field), location_index))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_sectioned_brief(
    brief: SectionedBrief,
    workflow: SectionWorkflow,
    location_index: dict[str, dict[str, Any]] | None = None,
) -> str:
    lines = []
    for number, (field, title) in enumerate(workflow.sections, start=1):
        lines.append(f"{number}. {title}")
        lines.extend(_render_items(brief.sections[field], location_index))
        lines.append("")
    return "\n".join(lines).rstrip()


def render_quiz_brief(
    brief: QuizBrief, location_index: dict[str, dict[str, Any]] | None = None
) -> str:
    lines = ["Questions"]
    for question in brief.questions:
        provenance = _render_provenance(question.provenance, location_index)
        lines.append(
            f"- {question.question_id} ({question.question_type}): "
            f"{question.question}{provenance}"
        )
    lines.extend(["", "Answers"])
    for answer in brief.answers:
        provenance = _render_provenance(answer.provenance, location_index)
        lines.append(f"- {answer.question_id}: {answer.answer}{provenance}")
    return "\n".join(lines)


def render_teach_brief(
    brief: TeachBrief,
    teach_request: dict[str, Any],
    student_context: list[dict[str, Any]],
    location_index: dict[str, dict[str, Any]] | None = None,
) -> str:
    lines = [f"Topic: {teach_request['topic']}", ""]
    if student_context:
        lines.append("Student-reported context (not an official-source claim)")
        for item in student_context:
            lines.append(
                f"- {item['kind']}: {item['text']} "
                f"[{item['item_id']}; {item['capture_id']}]"
            )
        lines.append("")
    lines.append("Start here")
    lines.extend(_render_items([brief.direct_explanation], location_index))
    lines.extend(["", "Build the idea"])
    for number, move in enumerate(brief.teaching_sequence, start=1):
        move_label = move.move_type.replace("_", " ").title()
        lines.append(
            f"{number}. {move.title} ({move_label})\n"
            f"   {move.explanation}{_render_provenance(move.provenance, location_index)}"
        )
        if move.why_it_follows:
            lines.append(f"   Why this follows: {move.why_it_follows}")
    lines.extend(["", "Mental model"])
    lines.extend(_render_items([brief.mental_model], location_index))
    lines.extend(["", "Unscored retrieval checks"])
    lines.extend(_render_items(brief.check_questions, location_index))
    lines.append("")
    lines.append("Unknown or unsupported from the supplied university material")
    if brief.unknowns:
        lines.extend(f"- {item}" for item in brief.unknowns)
    else:
        lines.append("- No additional unknowns were identified.")
    return "\n".join(lines).rstrip()


def _render_items(
    items: list[BriefItem], location_index: dict[str, dict[str, Any]] | None = None
) -> list[str]:
    if not items:
        return ["- No source-grounded information was provided."]
    return [
        f"- {item.text}{_render_provenance(item.provenance, location_index)}"
        for item in items
    ]


def _render_provenance(
    references: list[SourceReference],
    location_index: dict[str, dict[str, Any]] | None = None,
) -> str:
    provenance = []
    for reference in references:
        entry = (location_index or {}).get(reference.source_id, {})
        location = render_source_location(
            entry.get("method"),
            reference.pdf_page,
            title=entry.get("titles", {}).get(reference.pdf_page),
        )
        provenance.append(f"{reference.source_id}{location}")
    return f" [{'; '.join(provenance)}]" if provenance else ""
