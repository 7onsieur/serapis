from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.cli import main
from university_jarvis.sources import SourceError, extract_pdf_text
from university_jarvis.state import get_module, load_state
from university_jarvis.workflows import build_prepare_context


class AcademicStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_state(Path(__file__).resolve().parents[1] / "data" / "academic-state.json")
        cls.context = build_prepare_context(cls.state, "SYN101", 1)

    def test_supplied_module_facts_are_loaded(self) -> None:
        module = get_module(self.state, "syn101")
        self.assertEqual(module["title"], "Introduction to Example Studies")
        self.assertEqual(module["teaching"]["lectures"]["count"], 1)
        self.assertEqual(module["assessments"][1]["weight_percent"], 25)
        self.assertEqual(module["assessments"][1]["deadline_status"], "confirmed_date")

    def test_prepare_retrieves_only_requested_week_sources(self) -> None:
        context = self.context
        self.assertEqual(context["module"]["code"], "SYN101")
        self.assertEqual(context["week"]["number"], 1)
        self.assertEqual(context["assessments"][1]["weight_percent"], 25)
        self.assertEqual(
            [source["id"] for source in context["sources"]],
            [
                "syn101-w01-lecture-01-pdf",
                "syn101-w01-example-reading",
            ],
        )

    def test_prepare_builds_bounded_provenance_context_without_a_brief(self) -> None:
        context = self.context
        self.assertEqual(context["generation"]["status"], "context_ready")
        self.assertFalse(context["generation"]["brief_generated"])
        self.assertEqual(context["week"]["topic"], "Asking clear questions about evidence")
        self.assertEqual(
            [source["source_id"] for source in context["source_contexts"]],
            [
                "syn101-w01-lecture-01-pdf",
                "syn101-w01-example-reading",
            ],
        )
        self.assertTrue(
            all(source["character_count"] <= 8_000 for source in context["source_contexts"])
        )
        self.assertEqual(context["source_contexts"][1]["academic_page_range"], "1")
        self.assertTrue(
            all(
                len(source["extraction"]["fingerprint"]["value"]) == 64
                for source in context["sources"]
            )
        )

    def test_direct_pdf_extraction_reports_counts_and_source_failures(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        extracted = extract_pdf_text(
            project_root / "sources" / "SYN101" / "week-01" / "example-week-1.pdf"
        )
        self.assertEqual(extracted["page_count"], 1)
        self.assertGreater(sum(len(page) for page in extracted["pages"]), 100)
        with self.assertRaisesRegex(SourceError, "Source file not found"):
            extract_pdf_text(project_root / "sources" / "missing.pdf")
        with tempfile.TemporaryDirectory() as temporary_directory:
            unreadable_pdf = Path(temporary_directory) / "unreadable.pdf"
            unreadable_pdf.write_text("not a PDF", encoding="utf-8")
            with self.assertRaisesRegex(SourceError, "PDF extraction returned invalid output"):
                extract_pdf_text(unreadable_pdf)

    def test_cli_status_succeeds(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["status"])
        self.assertEqual(result, 0)
        self.assertIn("SYN101 — Introduction to Example Studies", output.getvalue())


if __name__ == "__main__":
    unittest.main()
