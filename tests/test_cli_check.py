"""Milestone 5B: CLI-level proof that intake memory survives separate invocations."""

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

from university_jarvis.blackboard import (
    BlackboardClient,
    BlackboardSession,
    HttpResponse,
    sources_destination,
)
from university_jarvis.cli import main
from university_jarvis.intake_ledger import get_document_entry, load_ledger

TEST_MODULE = "ZZCLICHECK"

MEMBERSHIPS = [{"courseId": "_222003_1"}]
COURSE_DETAILS = {"id": "_222003_1", "courseId": TEST_MODULE, "name": "Sample Module"}
TOP_LEVEL_CONTENTS = [
    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}
]

BASE = "https://blackboard.example.test"
DOWNLOAD_URL = f"{BASE}/download/_doc1/CLI_Check_Lecture.pdf"


def _json_response(payload: dict) -> HttpResponse:
    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


def _week_children(modified: str) -> list[dict]:
    return [
        {
            "id": "_doc1",
            "title": "ultraDocumentBody",
            "contentHandler": {"id": "resource/x-bb-document"},
            "modified": modified,
            "created": "C1",
            "body": f'<a href="{DOWNLOAD_URL}">CLI_Check_Lecture.pdf</a>',
        }
    ]


class _RecordingTransport:
    """Fake Blackboard HTTP transport recording every call, so tests can assert
    zero attachment downloads on an UNCHANGED observation."""

    def __init__(self, modified: str, download_bytes: bytes, *, fail_download: bool = False) -> None:
        self._modified = modified
        self._download_bytes = download_bytes
        self._fail_download = fail_download
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        if url == f"{BASE}/learn/api/public/v1/users/me/courses":
            return _json_response({"results": MEMBERSHIPS})
        if url == f"{BASE}/learn/api/public/v1/courses/_222003_1":
            return _json_response(COURSE_DETAILS)
        if url == f"{BASE}/learn/api/public/v1/courses/_222003_1/contents":
            return _json_response({"results": TOP_LEVEL_CONTENTS})
        if url == f"{BASE}/learn/api/public/v1/courses/_222003_1/contents/_wk1/children":
            return _json_response({"results": _week_children(self._modified)})
        if url == DOWNLOAD_URL:
            if self._fail_download:
                return HttpResponse(status=500, body=b"boom")
            return HttpResponse(status=200, body=self._download_bytes)
        raise AssertionError(f"Unexpected URL requested: {url}")


def _client(transport: _RecordingTransport) -> BlackboardClient:
    session = BlackboardSession(base_url=BASE, cookie_header="test-session-cookie=1")
    return BlackboardClient(session, http_get=transport)


class CheckCliMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        module_root = sources_destination(TEST_MODULE, 1, "x").parent.parent
        self.addCleanup(lambda: shutil.rmtree(module_root, ignore_errors=True))

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.ledger_path = Path(tmpdir.name) / "intake-ledger.json"
        patcher_env = _EnvPatch("JARVIS_LEDGER_FILE", str(self.ledger_path))
        patcher_env.start()
        self.addCleanup(patcher_env.stop)

    def _run(self, transport: _RecordingTransport) -> str:
        client = _client(transport)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            rc = main(["check", TEST_MODULE, "--week", "1"], blackboard_client=client)
        self.assertEqual(rc, 0)
        return stdout.getvalue()

    def test_first_invocation_no_ledger_is_new_and_persists(self) -> None:
        self.assertFalse(self.ledger_path.exists())
        transport = _RecordingTransport("M1", b"bytes-v1")

        output = self._run(transport)

        self.assertIn("[NEW] CLI_Check_Lecture.pdf", output)
        self.assertIn("Overall: success", output)
        self.assertTrue(self.ledger_path.exists())
        ledger = load_ledger(self.ledger_path)
        entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")
        self.assertEqual(entry["modified"], "M1")

    def test_second_process_style_invocation_loads_persisted_ledger_as_unchanged(self) -> None:
        first_transport = _RecordingTransport("M1", b"bytes-v1")
        self._run(first_transport)

        second_transport = _RecordingTransport("M1", b"bytes-v1")
        output = self._run(second_transport)

        self.assertIn("[UNCHANGED] CLI_Check_Lecture.pdf", output)
        self.assertIn("Overall: success", output)
        self.assertNotIn(DOWNLOAD_URL, second_transport.calls)

    def test_changed_material_persists_updated_observation(self) -> None:
        self._run(_RecordingTransport("M1", b"bytes-v1"))

        output = self._run(_RecordingTransport("M2", b"bytes-v2"))

        self.assertIn("[CHANGED] CLI_Check_Lecture.pdf", output)
        ledger = load_ledger(self.ledger_path)
        entry = get_document_entry(ledger, TEST_MODULE, 1, "_doc1")
        self.assertEqual(entry["modified"], "M2")
        import hashlib

        self.assertEqual(
            entry["attachments"]["CLI_Check_Lecture.pdf"]["content_sha256"],
            hashlib.sha256(b"bytes-v2").hexdigest(),
        )

    def test_failed_download_preserves_prior_ledger(self) -> None:
        self._run(_RecordingTransport("M1", b"bytes-v1"))
        prior_ledger_bytes = self.ledger_path.read_bytes()

        transport = _RecordingTransport("M2", b"bytes-v2", fail_download=True)
        output = self._run(transport)

        self.assertIn("[FAILED] CLI_Check_Lecture.pdf", output)
        self.assertIn("Overall: incomplete", output)
        self.assertEqual(self.ledger_path.read_bytes(), prior_ledger_bytes)


class _EnvPatch:
    """Minimal os.environ patch helper (avoids importing unittest.mock at module load)."""

    def __init__(self, key: str, value: str) -> None:
        self._key = key
        self._value = value
        self._had_prior = False
        self._prior = None

    def start(self) -> None:
        import os

        if self._key in os.environ:
            self._had_prior = True
            self._prior = os.environ[self._key]
        os.environ[self._key] = self._value

    def stop(self) -> None:
        import os

        if self._had_prior:
            os.environ[self._key] = self._prior
        else:
            os.environ.pop(self._key, None)


if __name__ == "__main__":
    unittest.main()
