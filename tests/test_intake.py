from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.blackboard import (
    BlackboardClient,
    BlackboardError,
    BlackboardSession,
    HttpResponse,
    sources_destination,
)
from university_jarvis.drive import DriveClient
from university_jarvis.intake import (
    AMBIGUOUS,
    DUPLICATE_FILE_NAME_IN_WEEK,
    FAILED,
    RETRIEVED,
    SKIPPED,
    SYNCED,
    WEEK_NOT_FOUND,
    intake_week,
)
from university_jarvis.blackboard import SKIPPED_EXTERNAL, SKIPPED_TOOL_LINK, WEEK_NOT_YET_PUBLISHED

from tests.test_drive import _FakeDriveService

# Distinct fake module code so cleanup only ever touches this test's own
# gitignored sources/ subtree, never real material.
TEST_MODULE = "ZZINTAKETEST"


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class _RoutedTransport:
    """Maps URL suffixes to canned JSON, and downloads to fixed byte payloads."""

    def __init__(self, contents_by_path: dict[str, list[dict]], downloads: dict[str, bytes] | None = None) -> None:
        self._base = "https://blackboard.example.test/learn/api/public/v1/courses/_333_1"
        self._contents_by_path = contents_by_path
        self._downloads = downloads or {}
        self.calls: list[str] = []
        self.fail_on: set[str] = set()

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        for path, results in self._contents_by_path.items():
            if url == f"{self._base}{path}":
                return _json_response({"results": results})
        for download_url, body in self._downloads.items():
            if url == download_url or url.endswith(download_url):
                if download_url in self.fail_on:
                    return HttpResponse(status=500, body=b"boom")
                return HttpResponse(status=200, body=body)
        raise AssertionError(f"Unexpected URL requested: {url}")


def _client(transport: _RoutedTransport) -> BlackboardClient:
    session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
    return BlackboardClient(session, http_get=transport)


SINGLE_ATTACHMENT_FIXTURE = {
    "/contents": [
        {
            "id": "_wk1",
            "title": "Week 1 w/c 01/09/2025 - Introduction",
            "contentHandler": {"id": "resource/x-bb-lesson"},
            "hasChildren": True,
        }
    ],
    "/contents/_wk1/children": [
        {"id": "_thisweek", "title": "This Week", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
    ],
    "/contents/_thisweek/children": [
        {
            "id": "_doc1",
            "title": "ultraDocumentBody",
            "contentHandler": {"id": "resource/x-bb-document"},
            "body": '<a href="/download/_doc1/SBM_Lecture1.pdf">SBM_Lecture1.pdf</a>',
        }
    ],
}


class IntakeWeekTests(unittest.TestCase):
    def setUp(self) -> None:
        module_root = sources_destination(TEST_MODULE, 1, "x").parent.parent
        self.addCleanup(lambda: shutil.rmtree(module_root, ignore_errors=True))

    def test_retrieves_and_syncs_the_only_discovered_attachment(self) -> None:
        transport = _RoutedTransport(
            SINGLE_ATTACHMENT_FIXTURE,
            downloads={"/download/_doc1/SBM_Lecture1.pdf": b"%PDF-fake-bytes"},
        )
        client = _client(transport)
        drive_client = DriveClient(_FakeDriveService())

        result = intake_week(client, drive_client, "_333_1", TEST_MODULE, 1)

        self.assertTrue(result.success)
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.status, SYNCED)
        self.assertEqual(item.file_name, "SBM_Lecture1.pdf")
        self.assertTrue(item.local_path.exists())
        self.assertEqual(item.local_path.read_bytes(), b"%PDF-fake-bytes")
        self.assertIsNotNone(item.drive_file_id)

    def test_retrieval_without_drive_client_marks_retrieved_not_synced(self) -> None:
        transport = _RoutedTransport(
            SINGLE_ATTACHMENT_FIXTURE,
            downloads={"/download/_doc1/SBM_Lecture1.pdf": b"%PDF-fake-bytes"},
        )
        client = _client(transport)

        result = intake_week(client, None, "_333_1", TEST_MODULE, 1, sync_to_drive=False)

        self.assertTrue(result.success)
        self.assertEqual(result.items[0].status, RETRIEVED)
        self.assertIsNone(result.items[0].drive_file_id)

    def test_rerun_is_idempotent_on_drive(self) -> None:
        transport = _RoutedTransport(
            SINGLE_ATTACHMENT_FIXTURE,
            downloads={"/download/_doc1/SBM_Lecture1.pdf": b"%PDF-fake-bytes"},
        )
        client = _client(transport)
        service = _FakeDriveService()
        drive_client = DriveClient(service)

        first = intake_week(client, drive_client, "_333_1", TEST_MODULE, 1)
        second = intake_week(client, drive_client, "_333_1", TEST_MODULE, 1)

        self.assertEqual(first.items[0].drive_file_id, second.items[0].drive_file_id)
        create_calls = [call for call in service._files_resource.calls if call[0] == "create"]
        folder_creates = [c for c in create_calls if c[1]["body"].get("mimeType") == "application/vnd.google-apps.folder"]
        file_creates = [c for c in create_calls if c[1]["body"].get("mimeType") != "application/vnd.google-apps.folder"]
        self.assertEqual(len(folder_creates), 3)  # University / SYN101 / Week 01 -- created once, not twice
        self.assertEqual(len(file_creates), 1)  # file created once; second run updates in place

    def test_week_not_yet_published_is_not_an_error(self) -> None:
        transport = _RoutedTransport(
            {
                "/contents": [
                    {
                        "id": "_wk2",
                        "title": "Week 2 (Oct 5-9)",
                        "contentHandler": {"id": "resource/x-bb-lesson"},
                        "hasChildren": True,
                    }
                ],
                "/contents/_wk2/children": [],
            }
        )
        client = _client(transport)

        result = intake_week(client, None, "_333_1", TEST_MODULE, 2, sync_to_drive=False)

        self.assertEqual(result.status, WEEK_NOT_YET_PUBLISHED)
        self.assertEqual(result.items, [])
        self.assertTrue(result.success)

    def test_week_not_found_is_reported_explicitly(self) -> None:
        transport = _RoutedTransport(
            {
                "/contents": [
                    {
                        "id": "_wk1",
                        "title": "Week 1",
                        "contentHandler": {"id": "resource/x-bb-lesson"},
                        "hasChildren": False,
                    }
                ],
            }
        )
        client = _client(transport)

        result = intake_week(client, None, "_333_1", TEST_MODULE, 9, sync_to_drive=False)

        self.assertEqual(result.status, WEEK_NOT_FOUND)
        self.assertFalse(result.success)

    def test_tool_link_and_external_link_are_skipped_not_failed(self) -> None:
        transport = _RoutedTransport(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_reflect", "title": "'Reflect' recordings", "contentHandler": {"id": "resource/x-bb-bltiplacement-Panopto"}},
                    {"id": "_libsearch", "title": "Library Search", "contentHandler": {"id": "resource/x-bb-externallink"}},
                ],
            }
        )
        client = _client(transport)

        result = intake_week(client, None, "_333_1", TEST_MODULE, 1, sync_to_drive=False)

        self.assertTrue(result.success)
        reasons = {(item.status, item.reason) for item in result.items}
        self.assertIn((SKIPPED, SKIPPED_TOOL_LINK), reasons)
        self.assertIn((SKIPPED, SKIPPED_EXTERNAL), reasons)

    def test_ambiguous_structure_is_surfaced_and_marks_incomplete(self) -> None:
        transport = _RoutedTransport(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_mystery", "title": "Some New Thing", "contentHandler": {"id": "resource/x-bb-asmt-test-link"}},
                ],
            }
        )
        client = _client(transport)

        result = intake_week(client, None, "_333_1", TEST_MODULE, 1, sync_to_drive=False)

        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].status, AMBIGUOUS)
        self.assertFalse(result.success)

    def test_duplicate_file_name_across_distinct_resources_is_ambiguous(self) -> None:
        transport = _RoutedTransport(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_folderA", "title": "Folder A", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                    {"id": "_folderB", "title": "Folder B", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                ],
                "/contents/_folderA/children": [
                    {
                        "id": "_docA",
                        "title": "docA",
                        "contentHandler": {"id": "resource/x-bb-document"},
                        "body": '<a href="/download/A/Slides.pdf">Slides.pdf</a>',
                    }
                ],
                "/contents/_folderB/children": [
                    {
                        "id": "_docB",
                        "title": "docB",
                        "contentHandler": {"id": "resource/x-bb-document"},
                        "body": '<a href="/download/B/Slides.pdf">Slides.pdf</a>',
                    }
                ],
            },
            downloads={
                "/download/A/Slides.pdf": b"content-a",
                "/download/B/Slides.pdf": b"content-b",
            },
        )
        client = _client(transport)

        result = intake_week(client, None, "_333_1", TEST_MODULE, 1, sync_to_drive=False)

        self.assertFalse(result.success)
        self.assertEqual(len(result.items), 2)
        for item in result.items:
            self.assertEqual(item.status, AMBIGUOUS)
            self.assertEqual(item.reason, DUPLICATE_FILE_NAME_IN_WEEK)
        # Neither colliding attachment was retrieved -- no silent overwrite.
        self.assertEqual(transport.calls.count("https://blackboard.example.test/download/A/Slides.pdf"), 0)

    def test_one_attachment_failure_does_not_mask_others_or_overall_success(self) -> None:
        transport = _RoutedTransport(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_folderA", "title": "Folder A", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                    {"id": "_folderB", "title": "Folder B", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                ],
                "/contents/_folderA/children": [
                    {
                        "id": "_docA",
                        "title": "docA",
                        "contentHandler": {"id": "resource/x-bb-document"},
                        "body": '<a href="/download/A/Good.pdf">Good.pdf</a>',
                    }
                ],
                "/contents/_folderB/children": [
                    {
                        "id": "_docB",
                        "title": "docB",
                        "contentHandler": {"id": "resource/x-bb-document"},
                        "body": '<a href="/download/B/Bad.pdf">Bad.pdf</a>',
                    }
                ],
            },
            downloads={
                "/download/A/Good.pdf": b"good-bytes",
                "/download/B/Bad.pdf": b"unused",
            },
        )
        transport.fail_on.add("/download/B/Bad.pdf")
        client = _client(transport)

        result = intake_week(client, None, "_333_1", TEST_MODULE, 1, sync_to_drive=False)

        self.assertFalse(result.success)
        statuses = {item.file_name: item.status for item in result.items}
        self.assertEqual(statuses["Good.pdf"], RETRIEVED)
        self.assertEqual(statuses["Bad.pdf"], FAILED)


if __name__ == "__main__":
    unittest.main()
