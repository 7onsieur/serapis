from __future__ import annotations

import copy
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.cli import main
from university_jarvis.reasoning import (
    AFTER_LECTURE_WORKFLOW,
    ASSIGNMENT_WORKFLOW,
    REVISE_WORKFLOW,
    SectionedBrief,
    generate_sectioned_brief,
    render_sectioned_brief,
)
from university_jarvis.state import load_state
from university_jarvis.workflows import build_assignment_context


SOURCE_IDS = [
    "syn101-w01-lecture-01-pdf",
    "syn101-w01-example-reading",
]


def week_context(workflow: str = "TEACH") -> dict:
    sources = [
        {
            "id": source_id,
            "type": "lecture_pdf" if index == 0 else "assigned_reading",
            "title": "Lecture 1 PDF" if index == 0 else "Introduction to Example Studies",
            "pages": None if index == 0 else "31–51",
            "locator": "must-not-reach-provider.pdf",
            "extraction": {
                "fingerprint": {"algorithm": "sha256", "value": character * 64},
                "character_count": 8_149 if index == 0 else 91_594,
            },
        }
        for index, (source_id, character) in enumerate(zip(SOURCE_IDS, ("a", "b")))
    ]
    return {
        "workflow": workflow,
        "objective_context": {
            "version": 1,
            "primary_objective": "Build understanding toward the learners stated academic goals.",
            "stretch_objective": "Use reliable evidence and available time to make thoughtful learning choices.",
            "operating_principles": ["Genuine learning over outsourcing thinking."],
            "hard_constraints": ["Maintain academic integrity as a hard constraint."],
            "reliable_cohort_information_available": False,
        },
        "module": {"code": "SYN101", "title": "Introduction to Example Studies"},
        "week": {"number": 1, "topic": None},
        "assessments": [
            {
                "title": "Individual written assignment",
                "context": "A fictional exercise in framing a question and identifying relevant evidence",
            }
        ],
        "items": [],
        "sources": sources,
        "source_contexts": [
            {
                "source_id": source["id"],
                "source_type": source["type"],
                "character_count": 20,
                "excerpts": [
                    {"pdf_page": 3, "text": "Bounded source text.", "truncated": True}
                ],
            }
            for source in sources
        ],
        "unbounded_pages": ["must not reach provider"],
    }


def assignment_context() -> dict:
    context = week_context("ASSIGNMENT_COACH")
    context.pop("week")
    context.pop("items")
    context["weeks"] = [
        {"number": 1, "topic": None, "items": [], "source_ids": SOURCE_IDS}
    ]
    return context


class FakeWorkflowProvider:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "fake-v1"}

    def generate_structured_output(
        self, context: dict, instructions: str, output_format: dict
    ) -> dict:
        self.requests.append(
            {
                "context": context,
                "instructions": instructions,
                "format": output_format,
            }
        )
        if output_format["name"] == "quiz_brief":
            types = (
                "recall",
                "explanation",
                "application",
                "connection",
                "explanation",
                "application",
            )
            questions = [
                {
                    "question_id": f"q{index}",
                    "question_type": question_type,
                    "question": f"Grounded {question_type} question {index}?",
                    "provenance": [
                        {"source_id": SOURCE_IDS[0], "pdf_page": 3}
                    ],
                }
                for index, question_type in enumerate(types, start=1)
            ]
            return {
                "questions": questions,
                "answers": [
                    {
                        "question_id": question["question_id"],
                        "answer": f"Answer to {question['question_id']}.",
                        "provenance": question["provenance"],
                    }
                    for question in questions
                ],
            }
        return {
            field: [
                {
                    "text": f"Grounded content for {field}.",
                    "provenance": [
                        {"source_id": SOURCE_IDS[0], "pdf_page": 3}
                    ],
                }
            ]
            for field in output_format["schema"]["properties"]
        }


class AcademicWorkflowTests(unittest.TestCase):
    def test_each_cli_command_routes_and_renders_expected_structure(self) -> None:
        provider = FakeWorkflowProvider()

        def fake_week_builder(state, module, week, workflow):
            return week_context(workflow)

        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch(
                "university_jarvis.cli.build_week_context",
                side_effect=fake_week_builder,
            ):
                with patch(
                    "university_jarvis.cli.build_assignment_context",
                    return_value=assignment_context(),
                ):
                    commands = (
                        (["quiz", "SYN101", "--week", "1"], "Answers"),
                        (["revise", "SYN101", "--week", "1"], "7. Assessment relevance"),
                        (["assignment", "SYN101"], "9. Next actions"),
                    )
                    for index, (arguments, expected) in enumerate(commands):
                        output = io.StringIO()
                        with redirect_stdout(output):
                            result = main(
                                arguments,
                                reasoning_provider=provider,
                                cache_dir=Path(temporary_directory) / str(index),
                            )
                        self.assertEqual(result, 0)
                        self.assertIn(expected, output.getvalue())
                        self.assertIn(SOURCE_IDS[0], output.getvalue())

        self.assertEqual(len(provider.requests), 3)
        for request in provider.requests:
            supplied = request["context"]
            self.assertNotIn("unbounded_pages", supplied)
            self.assertNotIn("locator", supplied["sources"][0])
            self.assertEqual([source["id"] for source in supplied["sources"]], SOURCE_IDS)
            if "week" in supplied:
                self.assertEqual(supplied["week"]["number"], 1)

    def test_shared_cache_reuses_result_and_fingerprint_change_invalidates(self) -> None:
        provider = FakeWorkflowProvider()
        context = week_context("REVISE")
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_dir = Path(temporary_directory)
            first = generate_sectioned_brief(
                context, provider, REVISE_WORKFLOW, cache_dir
            )
            second = generate_sectioned_brief(
                context, provider, REVISE_WORKFLOW, cache_dir
            )
            changed = copy.deepcopy(context)
            changed["sources"][0]["extraction"]["fingerprint"]["value"] = "c" * 64
            third = generate_sectioned_brief(
                changed, provider, REVISE_WORKFLOW, cache_dir
            )

        self.assertEqual(first.cache_status, "generated")
        self.assertEqual(second.cache_status, "cached")
        self.assertEqual(third.cache_status, "generated")
        self.assertEqual(len(provider.requests), 2)

    def test_assignment_context_contains_known_assessments_and_relevant_sources(self) -> None:
        state = load_state(
            Path(__file__).resolve().parents[1] / "data" / "academic-state.json"
        )
        context = build_assignment_context(state, "SYN101")
        self.assertEqual(
            [assessment["title"] for assessment in context["assessments"]],
            ["Practice outline", "Example learning reflection"],
        )
        self.assertEqual(context["assessments"][1]["weight_percent"], 25)
        self.assertEqual([source["id"] for source in context["sources"]], SOURCE_IDS)
        self.assertEqual(context["sources"][1]["pages"], "1")

    def test_integrity_and_missing_information_boundaries_are_explicit(self) -> None:
        instructions = ASSIGNMENT_WORKFLOW.instructions
        self.assertIn("must not produce a finished assignment response", instructions)
        self.assertIn("fabricate evidence or references", instructions)
        self.assertIn("identify anything missing", instructions)
        self.assertIn("cannot be determined", AFTER_LECTURE_WORKFLOW.instructions)

        empty = SectionedBrief(
            {field: [] for field, _ in REVISE_WORKFLOW.sections}
        )
        rendered = render_sectioned_brief(empty, REVISE_WORKFLOW)
        self.assertIn("No source-grounded information was provided", rendered)


if __name__ == "__main__":
    unittest.main()
