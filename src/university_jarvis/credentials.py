"""Small, non-persisting credential lookup boundary."""

from __future__ import annotations

import getpass
import os
import subprocess
import sys


OPENAI_KEYCHAIN_SERVICE = "Serapis-OpenAI"
BLACKBOARD_KEYCHAIN_SERVICE = "Serapis-Blackboard"
GOOGLE_DRIVE_KEYCHAIN_SERVICE = "Serapis-GoogleDrive"
GOOGLE_OAUTH_CLIENT_KEYCHAIN_SERVICE = "Serapis-GoogleOAuthClient"


def _keychain_password(service: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        completed = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                getpass.getuser(),
                "-s",
                service,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0:
        return None
    value = completed.stdout.rstrip("\r\n")
    return value or None


def get_openai_api_key() -> str | None:
    """Return the environment credential, then macOS Keychain fallback, if available."""
    environment_key = os.environ.get("OPENAI_API_KEY")
    if environment_key:
        return environment_key
    return _keychain_password(OPENAI_KEYCHAIN_SERVICE)


def get_blackboard_session_cookie() -> str | None:
    """Return the Blackboard session ``Cookie`` header value, never persisted by this code.

    Checked in order: ``BLACKBOARD_SESSION_COOKIE`` environment variable, then a
    macOS Keychain generic password stored under service
    ``Serapis-Blackboard``. Callers must not log, print, or write the
    returned value anywhere other than an in-memory request header.
    """
    environment_cookie = os.environ.get("BLACKBOARD_SESSION_COOKIE")
    if environment_cookie:
        return environment_cookie
    return _keychain_password(BLACKBOARD_KEYCHAIN_SERVICE)


def get_google_drive_token_json() -> str | None:
    """Return the stored Google Drive OAuth token, as the JSON Credentials.to_json() produces.

    Checked in order: ``GOOGLE_DRIVE_TOKEN_JSON`` environment variable, then a
    macOS Keychain generic password stored under service
    ``Serapis-GoogleDrive``. This JSON carries the refresh token and
    client id/secret needed to mint access tokens — callers must not log,
    print, or persist it anywhere beyond building in-memory credentials.
    """
    environment_token = os.environ.get("GOOGLE_DRIVE_TOKEN_JSON")
    if environment_token:
        return environment_token
    return _keychain_password(GOOGLE_DRIVE_KEYCHAIN_SERVICE)


def get_google_oauth_client_json() -> str | None:
    """Return the Desktop OAuth client id/secret, as ``{"client_id": ..., "client_secret": ...}``.

    Checked in order: ``GOOGLE_OAUTH_CLIENT_JSON`` environment variable, then a
    macOS Keychain generic password stored under service
    ``Serapis-GoogleOAuthClient``. Store it yourself with, e.g.:

        security add-generic-password -a "$(whoami)" \\
            -s Serapis-GoogleOAuthClient -w -U

    which prompts interactively (masked, not in shell history) for the JSON
    value. Callers must not log, print, or persist the returned value beyond
    building an in-memory OAuth client config.
    """
    environment_client = os.environ.get("GOOGLE_OAUTH_CLIENT_JSON")
    if environment_client:
        return environment_client
    return _keychain_password(GOOGLE_OAUTH_CLIENT_KEYCHAIN_SERVICE)


def store_google_drive_token(token_json: str) -> bool:
    """Store a freshly-minted Google Drive OAuth token JSON in the macOS Keychain.

    Never logs, prints, or writes the value anywhere else. The ``security``
    CLI requires the value as a process argument (there is no stdin-based
    write path for ``add-generic-password``), so it is briefly visible to
    other processes on this machine via the process table for the duration
    of this one call — an inherent limitation of this tool, not of how this
    function handles the value otherwise.
    """
    if sys.platform != "darwin":
        return False
    try:
        completed = subprocess.run(
            [
                "/usr/bin/security",
                "add-generic-password",
                "-a",
                getpass.getuser(),
                "-s",
                GOOGLE_DRIVE_KEYCHAIN_SERVICE,
                "-w",
                token_json,
                "-U",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0
