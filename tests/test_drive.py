from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.drive import (
    DEFAULT_UPLOAD_MIMETYPE,
    DRIVE_FILE_SCOPE,
    DriveClient,
    DriveError,
    build_drive_credentials,
    build_oauth_client_config,
    folder_chain_for,
    guess_upload_mimetype,
    sync_file,
)

# Synthetic OAuth token JSON shaped like Credentials.to_json(); not a real
# credential, contains no working secret.
FAKE_TOKEN_JSON = (
    '{"token": "fake-access-token", "refresh_token": "fake-refresh-token", '
    '"client_id": "fake-client-id.apps.googleusercontent.com", '
    '"client_secret": "fake-client-secret", '
    '"scopes": ["https://www.googleapis.com/auth/drive.file"], '
    '"token_uri": "https://oauth2.googleapis.com/token"}'
)


class _FakeExecutable:
    def __init__(self, result) -> None:
        self._result = result

    def execute(self):
        return self._result


class _FakeFilesResource:
    """Records calls; answers list/create/update from an in-memory fake Drive tree."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._folders: dict[str, dict] = {}  # id -> {"name", "parent"}
        self._files: dict[str, dict] = {}  # id -> {"name", "parent", "content"}
        self._next_id = 1

    def _new_id(self, prefix: str) -> str:
        value = f"{prefix}-{self._next_id}"
        self._next_id += 1
        return value

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        query = kwargs["q"]
        is_folder_query = "mimeType='application/vnd.google-apps.folder'" in query
        is_not_folder_query = "mimeType!='application/vnd.google-apps.folder'" in query
        pool = self._folders if is_folder_query else self._files if is_not_folder_query else {}
        matches = [
            {"id": file_id, "name": record["name"]}
            for file_id, record in pool.items()
            if self._matches(query, record)
        ]
        return _FakeExecutable({"files": matches})

    def _matches(self, query: str, record: dict) -> bool:
        name_marker = f"name='{record['name']}'"
        if name_marker not in query:
            return False
        parent = record.get("parent")
        if parent:
            return f"'{parent}' in parents" in query
        return "'root' in parents" in query

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        body = kwargs["body"]
        is_folder = body.get("mimeType") == "application/vnd.google-apps.folder"
        parent = (body.get("parents") or [None])[0]
        if is_folder:
            folder_id = self._new_id("folder")
            self._folders[folder_id] = {"name": body["name"], "parent": parent}
            return _FakeExecutable({"id": folder_id})
        file_id = self._new_id("file")
        self._files[file_id] = {"name": body["name"], "parent": parent, "content": "created"}
        return _FakeExecutable({"id": file_id})

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        file_id = kwargs["fileId"]
        self._files[file_id]["content"] = "updated"
        return _FakeExecutable({"id": file_id})


class _FakeDriveService:
    def __init__(self) -> None:
        self._files_resource = _FakeFilesResource()

    def files(self):
        return self._files_resource


class DriveClientFolderTests(unittest.TestCase):
    def test_find_or_create_folder_creates_when_absent(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        folder_id = client.find_or_create_folder("University", None)
        self.assertTrue(folder_id.startswith("folder-"))

    def test_find_or_create_folder_is_idempotent(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        first_id = client.find_or_create_folder("University", None)
        second_id = client.find_or_create_folder("University", None)
        self.assertEqual(first_id, second_id)
        create_calls = [call for call in service.files().calls if call[0] == "create"]
        self.assertEqual(len(create_calls), 1)

    def test_folder_chain_for_module_and_week(self) -> None:
        self.assertEqual(folder_chain_for("syn101", 1), ["University", "SYN101", "Week 01"])
        self.assertEqual(folder_chain_for("SYN101", 12), ["University", "SYN101", "Week 12"])


class SyncFileTests(unittest.TestCase):
    def test_sync_file_creates_folder_chain_and_uploads_once(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "SAMPLE_Lecture1.pdf"
            local_path.write_bytes(b"%PDF-fake-drive-test")

            file_id = sync_file(client, local_path, "SYN200", 1)

            self.assertTrue(file_id.startswith("file-"))
            create_calls = [call for call in service.files().calls if call[0] == "create"]
            # University, SYN200, Week 01 folders + the file itself.
            self.assertEqual(len(create_calls), 4)

    def test_sync_file_is_idempotent_across_reruns(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "SAMPLE_Lecture1.pdf"
            local_path.write_bytes(b"%PDF-fake-drive-test")

            first_id = sync_file(client, local_path, "SYN200", 1)
            second_id = sync_file(client, local_path, "SYN200", 1)

            self.assertEqual(first_id, second_id)
            create_calls = [call for call in service.files().calls if call[0] == "create"]
            update_calls = [call for call in service.files().calls if call[0] == "update"]
            # No new folders or files created on the second run; content updated in place.
            self.assertEqual(len(create_calls), 4)
            self.assertEqual(len(update_calls), 1)

    def test_ambiguous_existing_folder_raises(self) -> None:
        service = _FakeDriveService()
        # Simulate two folders of the same name already existing under root.
        service.files()._folders["folder-a"] = {"name": "University", "parent": None}
        service.files()._folders["folder-b"] = {"name": "University", "parent": None}
        client = DriveClient(service)
        with self.assertRaises(DriveError):
            client.find_or_create_folder("University", None)


class GuessUploadMimetypeTests(unittest.TestCase):
    def test_pdf_extension(self) -> None:
        self.assertEqual(guess_upload_mimetype(Path("Lecture1.pdf")), "application/pdf")

    def test_pptx_extension(self) -> None:
        self.assertEqual(
            guess_upload_mimetype(Path("Slides.pptx")),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

    def test_docx_extension(self) -> None:
        self.assertEqual(
            guess_upload_mimetype(Path("Handout.docx")),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_unknown_extension_falls_back_to_octet_stream(self) -> None:
        self.assertEqual(guess_upload_mimetype(Path("mystery.unknownext")), DEFAULT_UPLOAD_MIMETYPE)
        self.assertEqual(DEFAULT_UPLOAD_MIMETYPE, "application/octet-stream")


class UploadMimetypeEndToEndTests(unittest.TestCase):
    """Proves sync_file's real upload call carries the derived MIME type."""

    def _uploaded_mimetype(self, service: _FakeDriveService, file_name: str) -> str:
        create_calls = [
            call
            for call in service.files().calls
            if call[0] == "create" and call[1]["body"].get("name") == file_name
        ]
        self.assertEqual(len(create_calls), 1)
        media = create_calls[0][1]["media_body"]
        return media.mimetype()

    def test_pdf_uploaded_with_application_pdf(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "SAMPLE_Lecture1.pdf"
            local_path.write_bytes(b"%PDF-fake-drive-test")
            sync_file(client, local_path, "SYN200", 1)
        self.assertEqual(self._uploaded_mimetype(service, "SAMPLE_Lecture1.pdf"), "application/pdf")

    def test_pptx_uploaded_with_presentation_mimetype(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "SAMPLE_Slides.pptx"
            local_path.write_bytes(b"fake-pptx-bytes")
            sync_file(client, local_path, "SYN200", 1)
        self.assertEqual(
            self._uploaded_mimetype(service, "SAMPLE_Slides.pptx"),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

    def test_unknown_extension_uploaded_with_octet_stream_fallback(self) -> None:
        service = _FakeDriveService()
        client = DriveClient(service)
        with tempfile.TemporaryDirectory() as tmp:
            local_path = Path(tmp) / "SAMPLE_Notes.unknownext"
            local_path.write_bytes(b"fake-unknown-bytes")
            sync_file(client, local_path, "SYN200", 1)
        self.assertEqual(self._uploaded_mimetype(service, "SAMPLE_Notes.unknownext"), DEFAULT_UPLOAD_MIMETYPE)


class BuildDriveCredentialsTests(unittest.TestCase):
    def test_parses_authorized_user_json_without_live_network(self) -> None:
        credentials = build_drive_credentials(FAKE_TOKEN_JSON)
        self.assertEqual(credentials.client_id, "fake-client-id.apps.googleusercontent.com")
        self.assertEqual(list(credentials.scopes), [DRIVE_FILE_SCOPE])
        # Never expose the refresh token in repr/str.
        self.assertNotIn("fake-refresh-token", repr(credentials))


class BuildOAuthClientConfigTests(unittest.TestCase):
    def test_wraps_client_id_and_secret_into_installed_config(self) -> None:
        client_json = '{"client_id": "fake-id.apps.googleusercontent.com", "client_secret": "fake-secret"}'
        config = build_oauth_client_config(client_json)
        installed = config["installed"]
        self.assertEqual(installed["client_id"], "fake-id.apps.googleusercontent.com")
        self.assertEqual(installed["client_secret"], "fake-secret")
        self.assertEqual(installed["auth_uri"], "https://accounts.google.com/o/oauth2/auth")
        self.assertEqual(installed["token_uri"], "https://oauth2.googleapis.com/token")
        self.assertEqual(installed["redirect_uris"], ["http://localhost"])

    def test_missing_client_secret_raises(self) -> None:
        with self.assertRaises(KeyError):
            build_oauth_client_config('{"client_id": "fake-id"}')


if __name__ == "__main__":
    unittest.main()
