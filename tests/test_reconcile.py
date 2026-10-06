from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.blackboard import (
    BlackboardClient,
    BlackboardSession,
    HttpResponse,
    sources_destination,
)
from university_jarvis.drive import DriveClient, DriveError
from university_jarvis.intake import AMBIGUOUS, DUPLICATE_FILE_NAME_IN_WEEK, FAILED
from university_jarvis.intake_ledger import (
    all_document_entries,
    get_document_entry,
    load_ledger,
    new_ledger,
    save_ledger,
)
from university_jarvis.reconcile import (
    CHANGED,
    DOWNLOAD_FAILED,
    DRIVE_SYNC_FAILED,
    METADATA_CHANGED,
    MISSING_SINCE_LAST_CHECK,
    NEW,
    UNCHANGED,
    reconcile_week,
)
from university_jarvis.blackboard import WEEK_NOT_YET_PUBLISHED

from tests.test_drive import _FakeDriveService

TEST_MODULE = "ZZRECONCILETEST"


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class _RoutedTransport:
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


def _fixture(modified: str, created: str = "C1", href: str = "/download/_doc1/Lecture.pdf", link_text: str = "Lecture.pdf") -> dict:
    return {
        "/contents": [
            {
                "id": "_wk1",
                "title": "Week 1",
                "contentHandler": {"id": "resource/x-bb-lesson"},
                "hasChildren": True,
            }
        ],
        "/contents/_wk1/children": [
            {
                "id": "_doc1",
                "title": "ultraDocumentBody",
                "contentHandler": {"id": "resource/x-bb-document"},
                "modified": modified,
                "created": created,
                "body": f'<a href="{href}">{link_text}</a>',
            }
        ],
    }


class _FailingUploadDriveClient:
    """Duck-typed stand-in for DriveClient whose upload always fails."""

    def __init__(self, real_client: DriveClient) -> None:
        self._real = real_client

    def find_or_create_folder(self, name, parent_id=None):
        return self._real.find_or_create_folder(name, parent_id)

    def upload_or_update_file(self, local_path, name, parent_id):
        raise DriveError("simulated Drive outage")


class ReconcileWeekTests(unittest.TestCase):
    def setUp(self) -> None:
        module_root = sources_destination(TEST_MODULE, 1, "x").parent.parent
        self.addCleanup(lambda: shutil.rmtree(module_root, ignore_errors=True))

    def test_first_observation_is_new(self) -> None:
        transport = _RoutedTransport(_fixture("M1"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client = _client(transport)
        drive_client = DriveClient(_FakeDriveService())
        ledger = new_ledger()

        result = reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        self.assertTrue(result.success)
        self.assertEqual(len(result.items), 1)
        item = result.items[0]
        self.assertEqual(item.status, NEW)
        self.assertEqual(item.local_path.read_bytes(), b"bytes-v1")
        self.assertIsNotNone(item.drive_file_id)
        entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")
        self.assertEqual(entry["modified"], "M1")
        self.assertEqual(entry["attachments"]["Lecture.pdf"]["content_sha256"], __import__("hashlib").sha256(b"bytes-v1").hexdigest())

    def test_same_id_and_modified_is_unchanged_and_skips_download(self) -> None:
        transport = _RoutedTransport(_fixture("M1"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client = _client(transport)
        drive_client = DriveClient(_FakeDriveService())
        ledger = new_ledger()
        reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)
        transport.calls.clear()

        result = reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        self.assertEqual(result.items[0].status, UNCHANGED)
        download_calls = [c for c in transport.calls if "download" in c]
        self.assertEqual(download_calls, [])

    def test_modified_differs_and_hash_differs_is_changed(self) -> None:
        transport = _RoutedTransport(_fixture("M1"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client = _client(transport)
        drive_client = DriveClient(_FakeDriveService())
        ledger = new_ledger()
        reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        transport2 = _RoutedTransport(_fixture("M2"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v2"})
        client2 = _client(transport2)
        result = reconcile_week(client2, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        self.assertEqual(result.items[0].status, CHANGED)
        self.assertEqual(result.items[0].local_path.read_bytes(), b"bytes-v2")
        entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")
        self.assertEqual(entry["modified"], "M2")

    def test_modified_differs_but_hash_same_is_metadata_changed_no_drive_write(self) -> None:
        transport = _RoutedTransport(_fixture("M1"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client = _client(transport)
        service = _FakeDriveService()
        drive_client = DriveClient(service)
        ledger = new_ledger()
        reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)
        upload_calls_before = [c for c in service._files_resource.calls if c[0] in ("create", "update")]

        transport2 = _RoutedTransport(_fixture("M2"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client2 = _client(transport2)
        result = reconcile_week(client2, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        self.assertEqual(result.items[0].status, METADATA_CHANGED)
        entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")
        self.assertEqual(entry["modified"], "M2")
        upload_calls_after = [c for c in service._files_resource.calls if c[0] in ("create", "update")]
        file_uploads_before = [c for c in upload_calls_before if c[1].get("body", {}).get("mimeType") != "application/vnd.google-apps.folder"]
        file_uploads_after = [c for c in upload_calls_after if c[1].get("body", {}).get("mimeType") != "application/vnd.google-apps.folder" or "media_body" in c[1]]
        # No new file-content upload happened on the second (metadata-only) run.
        self.assertEqual(
            len([c for c in upload_calls_after if c not in upload_calls_before]),
            0,
        )

    def test_previously_seen_item_absent_is_missing_since_last_check(self) -> None:
        transport = _RoutedTransport(_fixture("M1"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client = _client(transport)
        drive_client = DriveClient(_FakeDriveService())
        ledger = new_ledger()
        reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        no_attachment_transport = _RoutedTransport(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {
                        "id": "_overview",
                        "title": "Overview",
                        "contentHandler": {"id": "resource/x-bb-document"},
                        "body": "<p>Welcome, no attachments here.</p>",
                    }
                ],
            }
        )
        client2 = _client(no_attachment_transport)
        result = reconcile_week(client2, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        statuses = [item.status for item in result.items]
        self.assertIn(MISSING_SINCE_LAST_CHECK, statuses)
        missing_item = next(item for item in result.items if item.status == MISSING_SINCE_LAST_CHECK)
        self.assertEqual(missing_item.file_name, "Lecture.pdf")
        # Local file untouched, never deleted.
        local_path = sources_destination(TEST_MODULE, 1, "Lecture.pdf")
        self.assertTrue(local_path.exists())

    def test_failed_download_does_not_destroy_previous_local_file_or_advance_ledger(self) -> None:
        transport = _RoutedTransport(_fixture("M1"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client = _client(transport)
        drive_client = DriveClient(_FakeDriveService())
        ledger = new_ledger()
        reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)
        before_entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")

        transport2 = _RoutedTransport(_fixture("M2"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v2"})
        transport2.fail_on.add("/download/_doc1/Lecture.pdf")
        client2 = _client(transport2)
        result = reconcile_week(client2, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        self.assertEqual(result.items[0].status, FAILED)
        self.assertEqual(result.items[0].reason, DOWNLOAD_FAILED)
        local_path = sources_destination(TEST_MODULE, 1, "Lecture.pdf")
        self.assertEqual(local_path.read_bytes(), b"bytes-v1")
        after_entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")
        self.assertEqual(after_entry, before_entry)

    def test_failed_drive_sync_does_not_falsely_mark_new_version_complete(self) -> None:
        transport = _RoutedTransport(_fixture("M1"), downloads={"/download/_doc1/Lecture.pdf": b"bytes-v1"})
        client = _client(transport)
        real_drive_client = DriveClient(_FakeDriveService())
        failing_drive_client = _FailingUploadDriveClient(real_drive_client)
        ledger = new_ledger()

        result = reconcile_week(client, failing_drive_client, "_333_1", TEST_MODULE, 1, ledger)

        self.assertEqual(result.items[0].status, FAILED)
        self.assertEqual(result.items[0].reason, DRIVE_SYNC_FAILED)
        self.assertFalse(result.success)
        self.assertIsNone(get_document_entry(ledger, TEST_MODULE, 1, "_doc1"))
        # Local file was still retrieved (Intake V1 per-item partial-success behaviour).
        local_path = sources_destination(TEST_MODULE, 1, "Lecture.pdf")
        self.assertEqual(local_path.read_bytes(), b"bytes-v1")

    def test_week_not_yet_published_is_preserved(self) -> None:
        transport = _RoutedTransport(
            {
                "/contents": [
                    {"id": "_wk2", "title": "Week 2", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk2/children": [],
            }
        )
        client = _client(transport)
        ledger = new_ledger()

        result = reconcile_week(client, None, "_333_1", TEST_MODULE, 2, ledger, sync_to_drive=False)

        self.assertEqual(result.status, WEEK_NOT_YET_PUBLISHED)
        self.assertEqual(result.items, [])

    def test_ambiguous_structure_is_preserved(self) -> None:
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
        ledger = new_ledger()

        result = reconcile_week(client, None, "_333_1", TEST_MODULE, 1, ledger, sync_to_drive=False)

        self.assertEqual(result.items[0].status, AMBIGUOUS)
        self.assertFalse(result.success)

    def test_multiple_attachments_under_one_document_are_ledgered_separately(self) -> None:
        fixture = {
            "/contents": [
                {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
            ],
            "/contents/_wk1/children": [
                {
                    "id": "_doc1",
                    "title": "ultraDocumentBody",
                    "contentHandler": {"id": "resource/x-bb-document"},
                    "modified": "M1",
                    "body": (
                        '<a href="/download/_doc1/Slides.pdf">Slides.pdf</a>'
                        '<a href="/download/_doc1/Handout.pdf">Handout.pdf</a>'
                    ),
                }
            ],
        }
        transport = _RoutedTransport(
            fixture,
            downloads={
                "/download/_doc1/Slides.pdf": b"slides-bytes",
                "/download/_doc1/Handout.pdf": b"handout-bytes",
            },
        )
        client = _client(transport)
        drive_client = DriveClient(_FakeDriveService())
        ledger = new_ledger()

        result = reconcile_week(client, drive_client, "_333_1", TEST_MODULE, 1, ledger)

        self.assertTrue(result.success)
        statuses = {item.file_name: item.status for item in result.items}
        self.assertEqual(statuses["Slides.pdf"], NEW)
        self.assertEqual(statuses["Handout.pdf"], NEW)
        entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")
        self.assertEqual(set(entry["attachments"].keys()), {"Slides.pdf", "Handout.pdf"})
        self.assertNotEqual(
            entry["attachments"]["Slides.pdf"]["content_sha256"],
            entry["attachments"]["Handout.pdf"]["content_sha256"],
        )

    def test_duplicate_file_name_in_week_is_ambiguous_not_ledgered(self) -> None:
        fixture = {
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
                    "modified": "M1",
                    "body": '<a href="/download/A/Slides.pdf">Slides.pdf</a>',
                }
            ],
            "/contents/_folderB/children": [
                {
                    "id": "_docB",
                    "title": "docB",
                    "contentHandler": {"id": "resource/x-bb-document"},
                    "modified": "M1",
                    "body": '<a href="/download/B/Slides.pdf">Slides.pdf</a>',
                }
            ],
        }
        transport = _RoutedTransport(
            fixture,
            downloads={"/download/A/Slides.pdf": b"content-a", "/download/B/Slides.pdf": b"content-b"},
        )
        client = _client(transport)
        ledger = new_ledger()

        result = reconcile_week(client, None, "_333_1", TEST_MODULE, 1, ledger, sync_to_drive=False)

        self.assertFalse(result.success)
        for item in result.items:
            self.assertEqual(item.status, AMBIGUOUS)
            self.assertEqual(item.reason, DUPLICATE_FILE_NAME_IN_WEEK)
        self.assertEqual(all_document_entries(ledger, TEST_MODULE, 1), {})


class LedgerPersistenceTests(unittest.TestCase):
    def test_atomic_save_and_reload_round_trips(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = new_ledger()
            ledger["modules"]["SYN101"] = {
                "weeks": {"1": {"documents": {"_doc1": {"content_id": "_doc1", "attachments": {}}}}}
            }
            save_ledger(ledger, path)
            self.assertFalse((Path(tmp) / "ledger.json.tmp").exists())

            reloaded = load_ledger(path)
            self.assertEqual(reloaded, ledger)

    def test_load_missing_ledger_returns_fresh_ledger(self) -> None:
        missing_path = Path("/tmp/does-not-exist-jarvis-ledger-test.json")
        ledger = load_ledger(missing_path)
        self.assertEqual(ledger["modules"], {})


if __name__ == "__main__":
    unittest.main()
