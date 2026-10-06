"""Idempotent, narrowly-scoped Google Drive sync for retrieved course material.

Uses Google's official client libraries (``google-auth``,
``google-api-python-client``) rather than a hand-rolled OAuth/upload
implementation — this is credential-handling code, where using the
maintained, standard library reduces risk versus reimplementing token
refresh and multipart upload.

Scope is deliberately the narrowest that works: ``drive.file``, which only
grants access to files/folders this app itself creates. That means Serapis
must own the ``University/<MODULE>/Week NN`` folder tree from scratch — it
cannot see a folder of that name you created by hand outside this app.

No OAuth consent flow and no live Drive request happen anywhere in this
module by import alone; both only occur if the caller supplies valid
credentials (see ``credentials.get_google_drive_token_json``) and explicitly
invokes a ``DriveClient`` method.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Protocol

from .state import StateError

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DRIVE_ROOT_FOLDER_NAME = "University"

DEFAULT_UPLOAD_MIMETYPE = "application/octet-stream"


def guess_upload_mimetype(local_path: Path) -> str:
    """Derive an upload MIME type from the file's extension via the stdlib.

    Deterministic (``mimetypes`` is a fixed extension table, not content
    sniffing or model classification). Falls back to
    ``application/octet-stream`` for an extension it doesn't recognise.
    """
    mimetype, _ = mimetypes.guess_type(local_path.name)
    return mimetype or DEFAULT_UPLOAD_MIMETYPE


class DriveError(StateError):
    """Raised for Google Drive client failures."""


def _missing_drive_extra(exc: ImportError) -> DriveError:
    return DriveError("This Google Drive action needs the optional Drive integration. Install `pip install -e '.[drive]'`.")


class FilesResource(Protocol):
    def list(self, **kwargs: Any) -> Any: ...
    def create(self, **kwargs: Any) -> Any: ...
    def update(self, **kwargs: Any) -> Any: ...


class DriveService(Protocol):
    """The subset of a googleapiclient Drive v3 Resource this module uses."""

    def files(self) -> FilesResource: ...


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    """Minimal wrapper over a Drive v3 service resource: find-or-create only."""

    def __init__(self, service: DriveService) -> None:
        self._service = service

    def find_folder(self, name: str, parent_id: str | None) -> str | None:
        query = (
            f"name='{_escape_query_value(name)}' "
            "and mimeType='application/vnd.google-apps.folder' and trashed=false"
        )
        query += f" and '{parent_id}' in parents" if parent_id else " and 'root' in parents"
        response = self._service.files().list(q=query, fields="files(id,name)", spaces="drive").execute()
        matches = response.get("files", [])
        if not matches:
            return None
        if len(matches) > 1:
            raise DriveError(f"Multiple folders named {name!r} found under the same parent")
        return matches[0]["id"]

    def create_folder(self, name: str, parent_id: str | None) -> str:
        body: dict[str, Any] = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            body["parents"] = [parent_id]
        created = self._service.files().create(body=body, fields="id").execute()
        return created["id"]

    def find_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """Idempotent: returns the existing folder's id if one already exists."""
        existing = self.find_folder(name, parent_id)
        if existing is not None:
            return existing
        return self.create_folder(name, parent_id)

    def find_file(self, name: str, parent_id: str) -> str | None:
        query = (
            f"name='{_escape_query_value(name)}' and mimeType!='application/vnd.google-apps.folder' "
            f"and trashed=false and '{parent_id}' in parents"
        )
        response = self._service.files().list(q=query, fields="files(id,name)", spaces="drive").execute()
        matches = response.get("files", [])
        if not matches:
            return None
        if len(matches) > 1:
            raise DriveError(f"Multiple files named {name!r} found under the same folder")
        return matches[0]["id"]

    def upload_or_update_file(self, local_path: Path, name: str, parent_id: str) -> str:
        """Idempotent: updates the existing file's content in place if one already exists."""
        try:
            from googleapiclient.http import MediaFileUpload  # imported only for a real upload
        except ImportError as exc:
            raise _missing_drive_extra(exc) from exc

        media = MediaFileUpload(str(local_path), mimetype=guess_upload_mimetype(local_path), resumable=False)
        existing_id = self.find_file(name, parent_id)
        if existing_id is not None:
            updated = self._service.files().update(fileId=existing_id, media_body=media, fields="id").execute()
            return updated["id"]
        created = (
            self._service.files()
            .create(body={"name": name, "parents": [parent_id]}, media_body=media, fields="id")
            .execute()
        )
        return created["id"]


def folder_chain_for(module_code: str, week: int) -> list[str]:
    return [DRIVE_ROOT_FOLDER_NAME, module_code.upper(), f"Week {week:02d}"]


def sync_file(client: DriveClient, local_path: Path, module_code: str, week: int) -> str:
    """Idempotently upload/update ``local_path`` into University/<MODULE>/Week NN/.

    Rerunning with the same module/week/filename returns the same Drive file
    id and updates its content in place — it never creates a duplicate
    folder or file.
    """
    parent_id: str | None = None
    for folder_name in folder_chain_for(module_code, week):
        parent_id = client.find_or_create_folder(folder_name, parent_id)
    assert parent_id is not None
    return client.upload_or_update_file(local_path, local_path.name, parent_id)


def build_drive_credentials(token_json: str) -> Any:
    """Parse a stored authorized-user token JSON into Drive-scoped credentials.

    Only ever called with a value already retrieved via
    ``credentials.get_google_drive_token_json`` (env var or Keychain) — never
    with a literal token in source, logs, or output.
    """
    import json

    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise _missing_drive_extra(exc) from exc

    return Credentials.from_authorized_user_info(json.loads(token_json), [DRIVE_FILE_SCOPE])


def refresh_if_needed(credentials: Any) -> Any:
    """Refresh expired credentials in place. This is the one call that hits the network."""
    if credentials.expired and credentials.refresh_token:
        try:
            from google.auth.transport.requests import Request
        except ImportError as exc:
            raise _missing_drive_extra(exc) from exc

        credentials.refresh(Request())
    return credentials


def build_drive_service(credentials: Any) -> DriveService:
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise _missing_drive_extra(exc) from exc

    return build("drive", "v3", credentials=credentials, cache_discovery=False)


# Standard Google OAuth endpoints for a "Desktop app" client, exactly what
# Google's own downloaded client_secret.json for that client type contains.
_GOOGLE_OAUTH_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_GOOGLE_OAUTH_TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_oauth_client_config(client_json: str) -> dict[str, Any]:
    """Wrap a stored ``{"client_id": ..., "client_secret": ...}`` into a full client config.

    Only ever called with a value already retrieved via
    ``credentials.get_google_oauth_client_json`` — never with a literal
    secret in source, logs, or output. Pure/offline: no network, no browser.
    """
    import json

    parsed = json.loads(client_json)
    client_id = parsed["client_id"]
    client_secret = parsed["client_secret"]
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": _GOOGLE_OAUTH_AUTH_URI,
            "token_uri": _GOOGLE_OAUTH_TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }


def run_oauth_consent_flow(client_config: dict[str, Any]) -> Any:
    """Run the one-time interactive browser OAuth consent flow. LIVE: opens a browser.

    Talks to Google's real OAuth servers and starts a local HTTP server to
    receive the redirect. Requests only ``drive.file`` — never broader Drive
    access. Returns Credentials whose ``.to_json()`` must go straight into
    Keychain (``credentials.store_google_drive_token``) and never be printed.
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise _missing_drive_extra(exc) from exc

    flow = InstalledAppFlow.from_client_config(client_config, scopes=[DRIVE_FILE_SCOPE])
    return flow.run_local_server(port=0)
