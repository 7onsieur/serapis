"""Milestone 5C: automatic university-wide discovery + reconciliation orchestration."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.blackboard import (
    BlackboardClient,
    BlackboardSession,
    HttpResponse,
    WEEK_AMBIGUOUS_DUPLICATE,
    WEEK_NOT_YET_PUBLISHED,
    sources_destination,
)
from university_jarvis.intake_ledger import get_document_entry, new_ledger
from university_jarvis.reconcile import CHANGED, DOWNLOAD_FAILED, FAILED, NEW, UNCHANGED
from university_jarvis.university import check_university

BASE = "https://blackboard.example.test/learn/api/public/v1"

MOD_A = "ZZUNIA"
MOD_B = "ZZUNIB"


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class _UniversityTransport:
    """Fake transport for full university-wide runs: memberships, course
    detail, root contents, week-lesson children, and attachment downloads."""

    def __init__(
        self,
        *,
        memberships: list[dict],
        courses: dict[str, dict],
        contents: dict[str, list[dict]],
        children: dict[str, list[dict]],
        downloads: dict[str, bytes] | None = None,
        fail_downloads: set[str] | None = None,
    ) -> None:
        self.memberships = memberships
        self.courses = courses
        self.contents = contents
        self.children = children
        self.downloads = downloads or {}
        self.fail_downloads = fail_downloads or set()
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        if url == f"{BASE}/users/me/courses":
            return _json_response({"results": self.memberships})
        for system_id, course in self.courses.items():
            if url == f"{BASE}/courses/{system_id}":
                return _json_response(course)
            if url == f"{BASE}/courses/{system_id}/contents":
                return _json_response({"results": self.contents.get(system_id, [])})
            for node in self.contents.get(system_id, []):
                content_id = node.get("id")
                if content_id and url == f"{BASE}/courses/{system_id}/contents/{content_id}/children":
                    return _json_response({"results": self.children.get(content_id, [])})
        for download_url, body in self.downloads.items():
            if url == download_url:
                if download_url in self.fail_downloads:
                    return HttpResponse(status=500, body=b"boom")
                return HttpResponse(status=200, body=body)
        raise AssertionError(f"Unexpected URL requested: {url}")


def _client(transport: _UniversityTransport) -> BlackboardClient:
    session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
    return BlackboardClient(session, http_get=transport)


def _week_lesson(lesson_id: str, week_title: str) -> dict:
    return {"id": lesson_id, "title": week_title, "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}


def _document_child(doc_id: str, modified: str, href: str, link_text: str) -> dict:
    return {
        "id": doc_id,
        "title": "doc",
        "contentHandler": {"id": "resource/x-bb-document"},
        "modified": modified,
        "body": f'<a href="{href}">{link_text}</a>',
    }


class CheckUniversityTests(unittest.TestCase):
    def setUp(self) -> None:
        # check_university() calls save_ledger(ledger) with no path, which
        # falls back to default_ledger_path() -- the REAL, gitignored
        # data/intake-ledger.json -- unless JARVIS_LEDGER_FILE points
        # elsewhere. Every test in this module must be isolated from it.
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        previous = os.environ.get("JARVIS_LEDGER_FILE")
        os.environ["JARVIS_LEDGER_FILE"] = str(Path(tmpdir.name) / "intake-ledger.json")

        def _restore() -> None:
            if previous is None:
                os.environ.pop("JARVIS_LEDGER_FILE", None)
            else:
                os.environ["JARVIS_LEDGER_FILE"] = previous

        self.addCleanup(_restore)

        for module in (MOD_A, MOD_B):
            root = sources_destination(module, 1, "x").parent.parent
            self.addCleanup(lambda root=root: shutil.rmtree(root, ignore_errors=True))

    def _two_module_transport(self, *, mod_a_modified: str = "M1", mod_a_bytes: bytes = b"a-v1") -> _UniversityTransport:
        return _UniversityTransport(
            memberships=[{"courseId": "_a_1"}, {"courseId": "_b_1"}],
            courses={
                "_a_1": {"id": "_a_1", "courseId": MOD_A, "name": "Module A"},
                "_b_1": {"id": "_b_1", "courseId": MOD_B, "name": "Module B"},
            },
            contents={
                "_a_1": [_week_lesson("_wk1a", "Week 1")],
                "_b_1": [_week_lesson("_wk1b", "Week 1"), _week_lesson("_wk2b", "Week 2")],
            },
            children={
                "_wk1a": [_document_child("_doca", mod_a_modified, "/download/a.pdf", "a.pdf")],
                "_wk1b": [_document_child("_docb", "M1", "/download/b.pdf", "b.pdf")],
                "_wk2b": [],
            },
            downloads={
                "https://blackboard.example.test/download/a.pdf": mod_a_bytes,
                "https://blackboard.example.test/download/b.pdf": b"b-v1",
            },
        )

    def test_multiple_modules_and_weeks_discovered_and_reconciled(self) -> None:
        transport = self._two_module_transport()
        client = _client(transport)
        ledger = new_ledger()

        result = check_university(client, None, ledger)

        codes = sorted(m.module_code for m in result.modules)
        self.assertEqual(codes, [MOD_A, MOD_B])
        mod_b = next(m for m in result.modules if m.module_code == MOD_B)
        self.assertEqual([w.week for w in mod_b.weeks], [1, 2])
        week2 = next(w for w in mod_b.weeks if w.week == 2)
        self.assertEqual(week2.status, WEEK_NOT_YET_PUBLISHED)
        self.assertEqual(result.scope_issues, [])

    def test_successful_week_persists_memory(self) -> None:
        transport = self._two_module_transport()
        client = _client(transport)
        ledger = new_ledger()

        check_university(client, None, ledger)

        entry = get_document_entry(ledger, MOD_A, 1, "_doca")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["modified"], "M1")

    def test_repeated_run_is_unchanged_and_downloads_nothing(self) -> None:
        transport = self._two_module_transport()
        client = _client(transport)
        ledger = new_ledger()
        check_university(client, None, ledger)

        transport2 = self._two_module_transport()
        client2 = _client(transport2)
        result = check_university(client2, None, ledger)

        mod_a = next(m for m in result.modules if m.module_code == MOD_A)
        self.assertEqual(mod_a.weeks[0].items[0].status, UNCHANGED)
        download_calls = [c for c in transport2.calls if "download" in c]
        self.assertEqual(download_calls, [])

    def test_drive_is_never_called_by_default(self) -> None:
        transport = self._two_module_transport()
        client = _client(transport)
        ledger = new_ledger()

        class _ExplodingDriveClient:
            def find_or_create_folder(self, *a, **k):
                raise AssertionError("Drive must not be called by default")

            def upload_or_update_file(self, *a, **k):
                raise AssertionError("Drive must not be called by default")

        check_university(client, None, ledger, sync_to_drive=False)
        # Even passing a Drive client through is inert while sync_to_drive=False.
        check_university(client, _ExplodingDriveClient(), new_ledger(), sync_to_drive=False)

    def test_one_failed_week_does_not_roll_back_or_block_other_modules(self) -> None:
        transport = _UniversityTransport(
            memberships=[{"courseId": "_a_1"}, {"courseId": "_b_1"}],
            courses={
                "_a_1": {"id": "_a_1", "courseId": MOD_A, "name": "Module A"},
                "_b_1": {"id": "_b_1", "courseId": MOD_B, "name": "Module B"},
            },
            contents={
                "_a_1": [_week_lesson("_wk1a", "Week 1")],
                "_b_1": [_week_lesson("_wk1b", "Week 1")],
            },
            children={
                "_wk1a": [_document_child("_doca", "M1", "https://blackboard.example.test/download/a.pdf", "a.pdf")],
                "_wk1b": [_document_child("_docb", "M1", "https://blackboard.example.test/download/b.pdf", "b.pdf")],
            },
            downloads={
                "https://blackboard.example.test/download/a.pdf": b"a-v1",
                "https://blackboard.example.test/download/b.pdf": b"b-v1",
            },
            fail_downloads={"https://blackboard.example.test/download/b.pdf"},
        )
        client = _client(transport)
        ledger = new_ledger()

        result = check_university(client, None, ledger)

        mod_a = next(m for m in result.modules if m.module_code == MOD_A)
        mod_b = next(m for m in result.modules if m.module_code == MOD_B)
        self.assertEqual(mod_a.weeks[0].items[0].status, NEW)
        self.assertTrue(mod_a.weeks[0].success)
        self.assertEqual(mod_b.weeks[0].items[0].status, FAILED)
        self.assertEqual(mod_b.weeks[0].items[0].reason, DOWNLOAD_FAILED)
        self.assertFalse(mod_b.weeks[0].success)
        # Module A's successful observation was persisted despite Module B's failure.
        self.assertIsNotNone(get_document_entry(ledger, MOD_A, 1, "_doca"))
        self.assertIsNone(get_document_entry(ledger, MOD_B, 1, "_docb"))

    def test_later_failure_does_not_roll_back_earlier_success_across_repeated_runs(self) -> None:
        transport = _UniversityTransport(
            memberships=[{"courseId": "_a_1"}, {"courseId": "_b_1"}],
            courses={
                "_a_1": {"id": "_a_1", "courseId": MOD_A, "name": "Module A"},
                "_b_1": {"id": "_b_1", "courseId": MOD_B, "name": "Module B"},
            },
            contents={
                "_a_1": [_week_lesson("_wk1a", "Week 1")],
                "_b_1": [_week_lesson("_wk1b", "Week 1")],
            },
            children={
                "_wk1a": [_document_child("_doca", "M1", "https://blackboard.example.test/download/a.pdf", "a.pdf")],
                "_wk1b": [_document_child("_docb", "M1", "https://blackboard.example.test/download/b.pdf", "b.pdf")],
            },
            downloads={
                "https://blackboard.example.test/download/a.pdf": b"a-v1",
                "https://blackboard.example.test/download/b.pdf": b"b-v1",
            },
        )
        client = _client(transport)
        ledger = new_ledger()
        check_university(client, None, ledger)
        a_entry_before = get_document_entry(ledger, MOD_A, 1, "_doca")

        failing_transport = _UniversityTransport(
            memberships=[{"courseId": "_a_1"}, {"courseId": "_b_1"}],
            courses=transport.courses,
            contents=transport.contents,
            children={
                "_wk1a": [_document_child("_doca", "M1", "https://blackboard.example.test/download/a.pdf", "a.pdf")],
                "_wk1b": [_document_child("_docb", "M2", "https://blackboard.example.test/download/b.pdf", "b.pdf")],
            },
            downloads={
                "https://blackboard.example.test/download/a.pdf": b"a-v1",
                "https://blackboard.example.test/download/b.pdf": b"b-v2",
            },
            fail_downloads={"https://blackboard.example.test/download/b.pdf"},
        )
        check_university(_client(failing_transport), None, ledger)

        self.assertEqual(get_document_entry(ledger, MOD_A, 1, "_doca"), a_entry_before)

    def test_duplicate_week_number_is_ambiguous_not_reconciled(self) -> None:
        transport = _UniversityTransport(
            memberships=[{"courseId": "_a_1"}],
            courses={"_a_1": {"id": "_a_1", "courseId": MOD_A, "name": "Module A"}},
            contents={
                "_a_1": [
                    {"id": "_wk1x", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                    {"id": "_wk1y", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ]
            },
            children={"_wk1x": [], "_wk1y": []},
        )
        client = _client(transport)
        ledger = new_ledger()

        result = check_university(client, None, ledger)

        mod_a = result.modules[0]
        self.assertEqual(len(mod_a.weeks), 1)
        self.assertEqual(mod_a.weeks[0].status, WEEK_AMBIGUOUS_DUPLICATE)
        self.assertFalse(mod_a.weeks[0].success)
        self.assertEqual(mod_a.weeks[0].items, [])


if __name__ == "__main__":
    unittest.main()
