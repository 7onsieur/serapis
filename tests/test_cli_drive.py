from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.cli import main
from university_jarvis.drive import DriveClient
from tests.test_drive import _FakeDriveService


class DriveSyncCliTests(unittest.TestCase):
    def test_drive_sync_command_uploads_and_prints_file_id(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "CLIexample-lecture.pdf"
            local_path.write_bytes(b"%PDF-fake-cli-drive-bytes")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    ["drive-sync", "CLISYN200", "--week", "1", "--file", str(local_path)],
                    drive_client=client,
                )
            self.assertEqual(rc, 0)
            self.assertIn("Synced to Google Drive: file id", stdout.getvalue())

    def test_drive_sync_without_credential_makes_no_request_and_fails_clearly(self) -> None:
        stderr = io.StringIO()
        with patch("university_jarvis.cli.get_google_drive_token_json", return_value=None):
            with redirect_stderr(stderr):
                rc = main(["drive-sync", "SYN101", "--week", "1", "--file", "irrelevant.pdf"])
        self.assertEqual(rc, 2)
        self.assertIn("No Google Drive credential found", stderr.getvalue())


class _FakeCredentials:
    def to_json(self) -> str:
        return '{"token": "fake-minted-token", "refresh_token": "fake-minted-refresh"}'


class DriveAuthCliTests(unittest.TestCase):
    def test_drive_auth_runs_consent_and_stores_token_without_printing_it(self) -> None:
        fake_client_json = '{"client_id": "fake-id.apps.googleusercontent.com", "client_secret": "fake-secret"}'
        fake_runner = lambda client_config: _FakeCredentials()  # noqa: E731
        stdout = io.StringIO()

        with patch(
            "university_jarvis.cli.get_google_oauth_client_json", return_value=fake_client_json
        ), patch("university_jarvis.cli.store_google_drive_token", return_value=True) as store_mock:
            with redirect_stdout(stdout):
                rc = main(["drive-auth"], oauth_flow_runner=fake_runner)

        self.assertEqual(rc, 0)
        store_mock.assert_called_once_with('{"token": "fake-minted-token", "refresh_token": "fake-minted-refresh"}')
        output = stdout.getvalue()
        self.assertIn("stored in the macOS Keychain", output)
        self.assertNotIn("fake-minted-token", output)
        self.assertNotIn("fake-minted-refresh", output)

    def test_drive_auth_without_oauth_client_makes_no_request_and_fails_clearly(self) -> None:
        stderr = io.StringIO()
        with patch("university_jarvis.cli.get_google_oauth_client_json", return_value=None):
            with redirect_stderr(stderr):
                rc = main(["drive-auth"])
        self.assertEqual(rc, 2)
        self.assertIn("No Google OAuth client found", stderr.getvalue())

    def test_drive_auth_reports_failure_when_keychain_store_fails(self) -> None:
        fake_client_json = '{"client_id": "fake-id", "client_secret": "fake-secret"}'
        fake_runner = lambda client_config: _FakeCredentials()  # noqa: E731
        stderr = io.StringIO()

        with patch(
            "university_jarvis.cli.get_google_oauth_client_json", return_value=fake_client_json
        ), patch("university_jarvis.cli.store_google_drive_token", return_value=False):
            with redirect_stderr(stderr):
                rc = main(["drive-auth"], oauth_flow_runner=fake_runner)

        self.assertEqual(rc, 2)
        self.assertIn("Failed to store the Google Drive token", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
