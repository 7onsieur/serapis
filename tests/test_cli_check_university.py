"""Milestone 5C: CLI-level proof of check-university discovery + reporting."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.blackboard import BlackboardClient, BlackboardSession, HttpResponse, sources_destination
from university_jarvis.cli import main
from university_jarvis.intake_ledger import load_ledger

BASE = "https://blackboard.example.test"
API = f"{BASE}/learn/api/public/v1"

MOD_TEACH = "ZZUNICLIA"
MOD_SUPPORT = "ZZUNICLISUP"


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class _Transport:
    def __init__(self, *, modified: str = "M1", download_bytes: bytes = b"lecture-v1") -> None:
        self._modified = modified
        self._download_bytes = download_bytes
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        if url == f"{API}/users/me/courses":
            return _json_response({"results": [{"courseId": "_teach_1"}, {"courseId": "_support_1"}]})
        if url == f"{API}/courses/_teach_1":
            return _json_response({"id": "_teach_1", "courseId": MOD_TEACH, "name": "Teaching Module"})
        if url == f"{API}/courses/_support_1":
            return _json_response({"id": "_support_1", "courseId": MOD_SUPPORT, "name": "Support Shell"})
        if url == f"{API}/courses/_teach_1/contents":
            return _json_response(
                {"results": [{"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}]}
            )
        if url == f"{API}/courses/_support_1/contents":
            return _json_response(
                {"results": [{"id": "_welcome", "title": "Getting Started", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}]}
            )
        if url == f"{API}/courses/_teach_1/contents/_wk1/children":
            return _json_response(
                {
                    "results": [
                        {
                            "id": "_doc1",
                            "title": "doc",
                            "contentHandler": {"id": "resource/x-bb-document"},
                            "modified": self._modified,
                            "body": f'<a href="{BASE}/download/lecture.pdf">lecture.pdf</a>',
                        }
                    ]
                }
            )
        if url == f"{BASE}/download/lecture.pdf":
            return HttpResponse(status=200, body=self._download_bytes)
        raise AssertionError(f"Unexpected URL requested: {url}")


def _client(transport: _Transport) -> BlackboardClient:
    session = BlackboardSession(base_url=BASE, cookie_header="test=1")
    return BlackboardClient(session, http_get=transport)


class CheckUniversityCliTests(unittest.TestCase):
    def setUp(self) -> None:
        module_root = sources_destination(MOD_TEACH, 1, "x").parent.parent
        self.addCleanup(lambda: shutil.rmtree(module_root, ignore_errors=True))

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.ledger_path = Path(tmpdir.name) / "intake-ledger.json"
        import os

        os.environ["JARVIS_LEDGER_FILE"] = str(self.ledger_path)
        self.addCleanup(lambda: os.environ.pop("JARVIS_LEDGER_FILE", None))

    def _run(self, transport: _Transport) -> str:
        client = _client(transport)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(["check-university"], blackboard_client=client)
        self.assertEqual(rc, 0)
        return stdout.getvalue()

    def test_discovers_only_teaching_module_and_reports_summary(self) -> None:
        output = self._run(_Transport())

        self.assertIn(MOD_TEACH, output)
        self.assertNotIn(MOD_SUPPORT, output)
        self.assertIn("[NEW] lecture.pdf", output)
        self.assertIn("teaching modules checked: 1", output)
        self.assertIn("new: 1", output)
        self.assertIn("Overall: success", output)
        self.assertTrue(self.ledger_path.exists())

    def test_repeated_run_reports_unchanged_from_persisted_ledger(self) -> None:
        self._run(_Transport())
        output = self._run(_Transport())

        self.assertIn("[UNCHANGED] lecture.pdf", output)
        self.assertIn("unchanged: 1", output)
        self.assertIn("Overall: success", output)

    def test_existing_single_module_check_command_still_works(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(
                ["check", MOD_TEACH, "--week", "1"],
                blackboard_client=_client(_Transport()),
            )
        self.assertEqual(rc, 0)
        self.assertIn("[NEW] lecture.pdf", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
