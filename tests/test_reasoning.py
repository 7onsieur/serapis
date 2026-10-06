from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.cli import main
from university_jarvis.credentials import get_openai_api_key
from university_jarvis.reasoning import (
    GROUNDING_INSTRUCTIONS,
    OpenAIReasoningProvider,
    PREPARE_MAX_OUTPUT_TOKENS,
    PreparationBrief,
    ReasoningError,
    TokenUsage,
    build_reasoning_context,
    generate_prepare_brief,
    render_prepare_brief,
)


def sample_brief() -> PreparationBrief:
    section_names = (
        "week_overview",
        "before_class",
        "core_concepts",
        "examples_cases",
        "lecture_attention",
        "after_class_questions",
        "assessment_connections",
    )
    return PreparationBrief.from_dict(
        {
            section: [
                {
                    "text": f"Grounded content for {section}.",
                    "provenance": [
                        {"source_id": "syn101-w01-lecture-01-pdf", "pdf_page": 3}
                    ],
                }
            ]
            for section in section_names
        }
    )


def bounded_context() -> dict:
    sources = [
        {
            "id": "syn101-w01-lecture-01-pdf",
            "type": "lecture_pdf",
            "title": "Lecture 1 PDF",
            "locator": "must-not-reach-provider.pdf",
            "extraction": {
                "page_count": 42,
                "character_count": 8149,
                "fingerprint": {"algorithm": "sha256", "value": "a" * 64},
            },
        },
        {
            "id": "syn101-w01-example-reading",
            "type": "assigned_reading",
            "title": "Introduction to Example Studies",
            "authors": "Example Author",
            "pages": "31–51",
            "locator": "must-not-reach-provider.pdf",
            "extraction": {
                "page_count": 21,
                "character_count": 91594,
                "fingerprint": {"algorithm": "sha256", "value": "b" * 64},
            },
        },
    ]
    return {
        "workflow": "PREPARE_ME",
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
        "assessments": [{"title": "Individual written assignment"}],
        "items": [],
        "sources": sources,
        "source_contexts": [
            {
                "source_id": source["id"],
                "source_type": source["type"],
                "character_limit": 8000,
                "character_count": 20,
                "excerpts": [{"pdf_page": 3, "text": "Bounded source text.", "truncated": True}],
            }
            for source in sources
        ],
        "unbounded_pages": ["must not reach the provider"],
    }


class FakeReasoningProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.last_usage: TokenUsage | None = None

    def cache_identity(self) -> dict[str, str]:
        return {"provider": "fake", "model": "fake-v1"}

    def generate_structured_output(
        self, context: dict, instructions: str, output_format: dict
    ) -> dict:
        self.calls.append(context)
        self.last_usage = TokenUsage(
            input_tokens=1_000,
            output_tokens=500,
            total_tokens=1_500,
        )
        return sample_brief().to_dict()


class ReasoningTests(unittest.TestCase):
    def test_only_bounded_requested_week_context_reaches_provider_and_cli_renders(self) -> None:
        provider = FakeReasoningProvider()
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = generate_prepare_brief(
                bounded_context(), provider, Path(temporary_directory)
            )
            self.assertEqual(result.cache_status, "generated")
            self.assertEqual(len(provider.calls), 1)
            supplied = provider.calls[0]
            self.assertEqual(supplied["workflow_scope"]["module_key"], "SYN101")
            self.assertIn("needs_verification", supplied["module_facts"])
            self.assertNotIn("module", supplied)
            self.assertEqual(supplied["week"]["number"], 1)
            self.assertEqual(
                [source["id"] for source in supplied["sources"]],
                [
                    "syn101-w01-lecture-01-pdf",
                    "syn101-w01-example-reading",
                ],
            )
            self.assertNotIn("unbounded_pages", supplied)
            self.assertNotIn("locator", supplied["sources"][0])
            self.assertLessEqual(
                sum(source["character_count"] for source in supplied["source_contexts"]),
                16_000,
            )

    def test_out_of_context_citation_is_rejected_before_cache_write(self) -> None:
        class InvalidCitationProvider(FakeReasoningProvider):
            def generate_structured_output(self, context, instructions, output_format):
                self.calls.append(context)
                invalid = sample_brief().to_dict()
                invalid["core_concepts"][0]["provenance"][0]["source_id"] = "not-supplied"
                return invalid

        provider = InvalidCitationProvider()
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_dir = Path(temporary_directory)
            with self.assertRaisesRegex(ReasoningError, "source not supplied"):
                generate_prepare_brief(bounded_context(), provider, cache_dir)
            self.assertEqual(list(cache_dir.iterdir()), [])

    def test_provider_context_groups_fact_values_by_trust_status(self) -> None:
        context = bounded_context()
        context["module"]["fact_provenance"] = {
            "title": {"status": "NEEDS_VERIFICATION", "evidence": []},
            "code": {"status": "UNKNOWN", "evidence": []},
        }
        context["assessments"] = [{
            "id": "a1",
            "title": "Synthetic essay",
            "deadline": "2030-01-02",
            "weight_percent": 40,
            "requirements": None,
            "fact_provenance": {
                "title": {"status": "CONFIRMED", "evidence": [{"source_id": "brief-1", "location": "Title"}]},
                "deadline": {"status": "NEEDS_VERIFICATION", "evidence": []},
                "weight_percent": {"status": "UNKNOWN", "evidence": []},
                "requirements": {"status": "UNKNOWN", "evidence": []},
            },
        }]
        context["truth_sources"] = [
            *context["sources"],
            {"id": "brief-1", "title": "Synthetic brief", "source_class": "UNIVERSITY_MATERIAL"},
        ]

        supplied = build_reasoning_context(context)

        self.assertNotIn("assessments", supplied)
        self.assertEqual(supplied["assessment_facts"][0]["facts"]["confirmed"][0]["value"], "Synthetic essay")
        self.assertEqual(supplied["assessment_facts"][0]["facts"]["needs_verification"][0]["value"], "2030-01-02")
        self.assertNotIn("value", supplied["assessment_facts"][0]["facts"]["unknown"][0])
        self.assertEqual(supplied["assessment_facts"][0]["facts"]["confirmed"][0]["evidence"][0]["source_class"], "UNIVERSITY_MATERIAL")

    def test_identical_input_uses_cache_and_fingerprint_change_regenerates(self) -> None:
        provider = FakeReasoningProvider()
        context = bounded_context()
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_dir = Path(temporary_directory)
            first = generate_prepare_brief(context, provider, cache_dir)
            provider.last_usage = None
            second = generate_prepare_brief(context, provider, cache_dir)
            changed = copy.deepcopy(context)
            changed["sources"][0]["extraction"]["fingerprint"]["value"] = "c" * 64
            third = generate_prepare_brief(changed, provider, cache_dir)

        self.assertEqual(first.cache_status, "generated")
        self.assertEqual(second.cache_status, "cached")
        self.assertEqual(third.cache_status, "generated")
        self.assertEqual(first.usage, TokenUsage(1_000, 500, 1_500))
        self.assertEqual(second.usage, first.usage)
        self.assertEqual(len(provider.calls), 2)
        self.assertNotEqual(first.cache_key, third.cache_key)

    def test_openai_provider_disables_retries_caps_output_and_captures_usage(self) -> None:
        responses = Mock()
        responses.create.return_value = SimpleNamespace(
            status="completed",
            incomplete_details=None,
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text")],
                )
            ],
            output_text=json.dumps(sample_brief().to_dict()),
            usage=SimpleNamespace(
                input_tokens=1_234,
                output_tokens=456,
                total_tokens=1_690,
            ),
        )
        client = SimpleNamespace(responses=responses)
        provider = OpenAIReasoningProvider()

        with patch(
            "university_jarvis.reasoning.get_openai_api_key",
            return_value="test-credential",
        ):
            with patch("openai.OpenAI", return_value=client) as openai_client:
                generated = provider.generate_structured_output(
                    bounded_context(), "instructions", {"type": "json_schema"}
                )

        openai_client.assert_called_once_with(
            api_key="test-credential", max_retries=0
        )
        responses.create.assert_called_once()
        self.assertEqual(
            responses.create.call_args.kwargs["max_output_tokens"],
            PREPARE_MAX_OUTPUT_TOKENS,
        )
        self.assertEqual(PREPARE_MAX_OUTPUT_TOKENS, 4_000)
        self.assertEqual(generated, sample_brief().to_dict())
        self.assertEqual(provider.last_usage, TokenUsage(1_234, 456, 1_690))

    def test_prepare_prompt_has_explicit_concise_content_budget(self) -> None:
        self.assertIn("1 to 3 concise items per section", GROUNDING_INSTRUCTIONS)
        self.assertIn("Avoid unnecessary repetition", GROUNDING_INSTRUCTIONS)
        self.assertIn("preserving academic usefulness", GROUNDING_INSTRUCTIONS)

    def test_post_response_failures_are_classified_keep_usage_and_never_cache(self) -> None:
        usage_value = SimpleNamespace(
            input_tokens=1_234,
            output_tokens=4_000,
            total_tokens=5_234,
        )
        expected_usage = TokenUsage(1_234, 4_000, 5_234)
        output_message = [
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text")],
            )
        ]
        cases = (
            (
                "token ceiling",
                SimpleNamespace(
                    status="incomplete",
                    incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                    output=output_message,
                    output_text='{"private_partial":',
                    usage=usage_value,
                ),
                "truncated at the output-token limit",
            ),
            (
                "content filter",
                SimpleNamespace(
                    status="incomplete",
                    incomplete_details=SimpleNamespace(reason="content_filter"),
                    output=output_message,
                    output_text='{"private_partial":',
                    usage=usage_value,
                ),
                "interrupted by the content filter",
            ),
            (
                "provider failure",
                SimpleNamespace(
                    status="failed",
                    incomplete_details=None,
                    output=[],
                    output_text="private provider payload",
                    usage=usage_value,
                ),
                "provider status: failed",
            ),
            (
                "malformed completed JSON",
                SimpleNamespace(
                    status="completed",
                    incomplete_details=None,
                    output=output_message,
                    output_text='{"private_partial":',
                    usage=usage_value,
                ),
                "completed with malformed structured JSON",
            ),
            (
                "refusal",
                SimpleNamespace(
                    status="completed",
                    incomplete_details=None,
                    output=[
                        SimpleNamespace(
                            type="message",
                            content=[
                                SimpleNamespace(
                                    type="refusal",
                                    refusal="private refusal payload",
                                )
                            ],
                        )
                    ],
                    output_text="",
                    usage=usage_value,
                ),
                "contained a refusal instead of structured output",
            ),
            (
                "missing output",
                SimpleNamespace(
                    status="completed",
                    incomplete_details=None,
                    output=[],
                    output_text="",
                    usage=usage_value,
                ),
                "completed without structured output",
            ),
        )

        for label, response, expected_message in cases:
            with self.subTest(label=label):
                responses = Mock()
                responses.create.return_value = response
                client = SimpleNamespace(responses=responses)
                provider = OpenAIReasoningProvider()
                with tempfile.TemporaryDirectory() as temporary_directory:
                    cache_dir = Path(temporary_directory)
                    with patch(
                        "university_jarvis.reasoning.get_openai_api_key",
                        return_value="test-credential",
                    ):
                        with patch("openai.OpenAI", return_value=client) as openai_client:
                            with self.assertRaisesRegex(
                                ReasoningError, expected_message
                            ) as raised:
                                generate_prepare_brief(
                                    bounded_context(), provider, cache_dir
                                )

                    openai_client.assert_called_once_with(
                        api_key="test-credential", max_retries=0
                    )
                    responses.create.assert_called_once()
                    self.assertEqual(provider.last_usage, expected_usage)
                    self.assertEqual(raised.exception.usage, expected_usage)
                    self.assertNotIn("private", str(raised.exception))
                    self.assertEqual(list(cache_dir.iterdir()), [])

    def test_failed_cli_reports_only_safe_numeric_usage(self) -> None:
        responses = Mock()
        responses.create.return_value = SimpleNamespace(
            status="completed",
            incomplete_details=None,
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text")],
                )
            ],
            output_text='{"private_response_body":',
            usage=SimpleNamespace(
                input_tokens=2_000,
                output_tokens=4_000,
                total_tokens=6_000,
            ),
        )
        client = SimpleNamespace(responses=responses)

        with tempfile.TemporaryDirectory() as temporary_directory:
            stderr = io.StringIO()
            with patch(
                "university_jarvis.reasoning.get_openai_api_key",
                return_value="test-credential",
            ):
                with patch("openai.OpenAI", return_value=client) as openai_client:
                    with patch("university_jarvis.cli.load_state", return_value={}):
                        with patch(
                            "university_jarvis.cli.build_prepare_context",
                            return_value=bounded_context(),
                        ):
                            with redirect_stderr(stderr):
                                result = main(
                                    ["prepare", "SYN101", "--week", "1"],
                                    cache_dir=Path(temporary_directory),
                                )

            self.assertEqual(result, 2)
            self.assertIn("completed with malformed structured JSON", stderr.getvalue())
            self.assertIn(
                "input_tokens=2000, output_tokens=4000, total_tokens=6000",
                stderr.getvalue(),
            )
            self.assertNotIn("private_response_body", stderr.getvalue())
            self.assertNotIn("test-credential", stderr.getvalue())
            self.assertEqual(list(Path(temporary_directory).iterdir()), [])
            openai_client.assert_called_once_with(
                api_key="test-credential", max_retries=0
            )
            responses.create.assert_called_once()

    def test_completed_schema_failure_keeps_usage_and_never_caches(self) -> None:
        responses = Mock()
        responses.create.return_value = SimpleNamespace(
            status="completed",
            incomplete_details=None,
            output=[
                SimpleNamespace(
                    type="message",
                    content=[SimpleNamespace(type="output_text")],
                )
            ],
            output_text=json.dumps({"unexpected": []}),
            usage=SimpleNamespace(
                input_tokens=1_500,
                output_tokens=250,
                total_tokens=1_750,
            ),
        )
        client = SimpleNamespace(responses=responses)
        provider = OpenAIReasoningProvider()

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache_dir = Path(temporary_directory)
            with patch(
                "university_jarvis.reasoning.get_openai_api_key",
                return_value="test-credential",
            ):
                with patch("openai.OpenAI", return_value=client) as openai_client:
                    with self.assertRaisesRegex(
                        ReasoningError,
                        "does not match the required seven sections",
                    ) as raised:
                        generate_prepare_brief(bounded_context(), provider, cache_dir)

            expected_usage = TokenUsage(1_500, 250, 1_750)
            self.assertEqual(raised.exception.usage, expected_usage)
            self.assertEqual(provider.last_usage, expected_usage)
            self.assertEqual(list(cache_dir.iterdir()), [])
            openai_client.assert_called_once_with(
                api_key="test-credential", max_retries=0
            )
            responses.create.assert_called_once()

    def test_provider_failure_makes_only_one_configured_request(self) -> None:
        responses = Mock()
        responses.create.side_effect = RuntimeError("provider failed")
        client = SimpleNamespace(responses=responses)
        provider = OpenAIReasoningProvider()

        with patch(
            "university_jarvis.reasoning.get_openai_api_key",
            return_value="test-credential",
        ):
            with patch("openai.OpenAI", return_value=client) as openai_client:
                with self.assertRaisesRegex(
                    ReasoningError, "failed before a response was received"
                ):
                    provider.generate_structured_output(
                        bounded_context(), "instructions", {"type": "json_schema"}
                    )

        openai_client.assert_called_once_with(
            api_key="test-credential", max_retries=0
        )
        responses.create.assert_called_once()
        self.assertIsNone(provider.last_usage)

    def test_brief_renders_exactly_seven_human_readable_sections(self) -> None:
        rendered = render_prepare_brief(sample_brief())
        headings = [line for line in rendered.splitlines() if line[:1].isdigit()]
        self.assertEqual(len(headings), 7)
        self.assertIn("1. What this week is about", rendered)
        self.assertIn("7. Assessment connections", rendered)
        self.assertIn("syn101-w01-lecture-01-pdf, PDF p. 3", rendered)

    def test_environment_credential_takes_precedence(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-environment-credential"}):
            with patch("university_jarvis.credentials.subprocess.run") as keychain:
                self.assertEqual(
                    get_openai_api_key(), "test-environment-credential"
                )
                keychain.assert_not_called()

    def test_keychain_fallback_uses_current_macos_user(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="test-keychain-credential\n", stderr=""
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch("university_jarvis.credentials.sys.platform", "darwin"):
                with patch(
                    "university_jarvis.credentials.getpass.getuser",
                    return_value="test-macos-user",
                ):
                    with patch(
                        "university_jarvis.credentials.subprocess.run",
                        return_value=completed,
                    ) as keychain:
                        self.assertEqual(
                            get_openai_api_key(), "test-keychain-credential"
                        )
        command = keychain.call_args.args[0]
        self.assertEqual(command[0:2], ["/usr/bin/security", "find-generic-password"])
        self.assertEqual(command[command.index("-a") + 1], "test-macos-user")
        self.assertEqual(
            command[command.index("-s") + 1], "Serapis-OpenAI"
        )

    def test_missing_openai_credentials_fail_at_provider_boundary(self) -> None:
        provider = OpenAIReasoningProvider()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch(
                "university_jarvis.reasoning.get_openai_api_key", return_value=None
            ):
                with self.assertRaisesRegex(
                    ReasoningError, "no OpenAI API credential is configured"
                ):
                    provider.generate_prepare_brief({})

    def test_prepare_cli_uses_fake_provider_without_live_api(self) -> None:
        provider = FakeReasoningProvider()
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    ["prepare", "SYN101", "--week", "1"],
                    reasoning_provider=provider,
                    cache_dir=Path(temporary_directory),
                )
        self.assertEqual(result, 0)
        self.assertIn("Reasoning result: generated", output.getvalue())
        self.assertIn("1. What this week is about", output.getvalue())
        self.assertEqual(len(provider.calls), 1)


if __name__ == "__main__":
    unittest.main()
