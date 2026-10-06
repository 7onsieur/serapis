from __future__ import annotations

import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.blackboard import (
    BlackboardClient,
    BlackboardSession,
    HttpResponse,
    sources_destination,
)
from university_jarvis.cli import main
from university_jarvis.drive import DriveClient

from tests.test_drive import _FakeDriveService

TEST_MODULE = "ZZCLIINTAKE"

MEMBERSHIPS = [{"courseId": "_222002_1"}]
COURSE_DETAILS = {"id": "_222002_1", "courseId": TEST_MODULE, "name": "Sample Module"}
TOP_LEVEL_CONTENTS = [
    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}
]
WEEK_1_CHILDREN = [
    {
        "id": "_doc1",
        "title": "ultraDocumentBody",
        "contentHandler": {"id": "resource/x-bb-document"},
        "body": '<a href="/download/_doc1/CLI_Intake_Lecture1.pdf">CLI_Intake_Lecture1.pdf</a>',
    }
]


class FakeTransport:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self._responses = responses

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        if url not in self._responses:
            raise AssertionError(f"Unexpected URL requested: {url}")
        return self._responses[url]


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class IntakeCliTests(unittest.TestCase):
    def setUp(self) -> None:
        module_root = sources_destination(TEST_MODULE, 1, "x").parent.parent
        self.addCleanup(lambda: shutil.rmtree(module_root, ignore_errors=True))

    def _fake_client(self) -> BlackboardClient:
        base = "https://blackboard.example.test"
        download_url = f"{base}/download/_doc1/CLI_Intake_Lecture1.pdf"
        transport = FakeTransport(
            {
                f"{base}/learn/api/public/v1/users/me/courses": _json_response({"results": MEMBERSHIPS}),
                f"{base}/learn/api/public/v1/courses/_222002_1": _json_response(COURSE_DETAILS),
                f"{base}/learn/api/public/v1/courses/_222002_1/contents": _json_response(
                    {"results": TOP_LEVEL_CONTENTS}
                ),
                f"{base}/learn/api/public/v1/courses/_222002_1/contents/_wk1/children": _json_response(
                    {"results": WEEK_1_CHILDREN}
                ),
                download_url: HttpResponse(status=200, body=b"%PDF-fake-cli-intake-bytes"),
            }
        )
        session = BlackboardSession(base_url=base, cookie_header="test-session-cookie=1")
        return BlackboardClient(session, http_get=transport)

    def test_intake_command_discovers_retrieves_and_syncs(self) -> None:
        client = self._fake_client()
        drive_client = DriveClient(_FakeDriveService())
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(
                ["intake", TEST_MODULE, "--week", "1"],
                blackboard_client=client,
                drive_client=drive_client,
            )
        self.assertEqual(rc, 0)
        output = stdout.getvalue()
        self.assertIn("[synced] CLI_Intake_Lecture1.pdf", output)
        self.assertIn("Overall: success", output)

    def test_intake_command_no_drive_sync_retrieves_only(self) -> None:
        client = self._fake_client()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(
                ["intake", TEST_MODULE, "--week", "1", "--no-drive-sync"],
                blackboard_client=client,
            )
        self.assertEqual(rc, 0)
        self.assertIn("[retrieved] CLI_Intake_Lecture1.pdf", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
