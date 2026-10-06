from __future__ import annotations

import io
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
from university_jarvis.cli import _resolve_blackboard_client, main

# Synthetic fixtures only; no real course/content ids or academic material.
# membership.courseId is the internal system id; the human-readable code
# ("CLISYN200") only appears on the resolved /courses/{id} record.
MEMBERSHIPS = [{"courseId": "_222002_1"}]
COURSE_DETAILS = {"id": "_222002_1", "courseId": "CLISYN200", "name": "Sample Module"}
TOP_LEVEL_CONTENTS = [{"id": "_1001_1", "title": "Week 1", "hasChildren": True}]
WEEK_1_CHILDREN = [
    {
        "id": "_1002_1",
        "title": "This Week",
        "hasChildren": False,
        "ultraDocumentBody": {
            "rawText": (
                '<a href="/learn/api/public/v1/courses/_222002_1/contents/_1002_1/'
                'attachments/_9001_1/download">CLIexample-lecture.pdf</a>'
            )
        },
    }
]


class FakeTransport:
    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.requested_urls.append(url)
        assert "Cookie" in headers  # session auth must be attached, never printed
        if url not in self._responses:
            raise AssertionError(f"Unexpected URL requested: {url}")
        return self._responses[url]


def _json_response(payload: dict) -> HttpResponse:
    import json

    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


class BlackboardFetchCliTests(unittest.TestCase):
    def _fake_client(self) -> tuple[BlackboardClient, FakeTransport]:
        base = "https://blackboard.example.test"
        download_url = f"{base}/learn/api/public/v1/courses/_222002_1/contents/_1002_1/attachments/_9001_1/download"
        transport = FakeTransport(
            {
                f"{base}/learn/api/public/v1/users/me/courses": _json_response({"results": MEMBERSHIPS}),
                f"{base}/learn/api/public/v1/courses/_222002_1": _json_response(COURSE_DETAILS),
                f"{base}/learn/api/public/v1/courses/_222002_1/contents": _json_response(
                    {"results": TOP_LEVEL_CONTENTS}
                ),
                f"{base}/learn/api/public/v1/courses/_222002_1/contents/_1001_1/children": _json_response(
                    {"results": WEEK_1_CHILDREN}
                ),
                download_url: HttpResponse(status=200, body=b"%PDF-fake-cli-bytes"),
            }
        )
        session = BlackboardSession(base_url=base, cookie_header="test-session-cookie=1")
        return BlackboardClient(session, http_get=transport), transport

    def test_blackboard_fetch_command_retrieves_attachment(self) -> None:
        client, transport = self._fake_client()
        dest = sources_destination("CLISYN200", 1, "CLIexample-lecture.pdf")
        try:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = main(
                    [
                        "blackboard-fetch",
                        "CLISYN200",
                        "--week",
                        "1",
                        "--title",
                        "This Week",
                    ],
                    blackboard_client=client,
                )
            self.assertEqual(rc, 0)
            self.assertIn(str(dest), stdout.getvalue())
            self.assertEqual(dest.read_bytes(), b"%PDF-fake-cli-bytes")
            # Nothing beyond the five expected, scoped requests was made.
            self.assertEqual(len(transport.requested_urls), 5)
        finally:
            if dest.exists():
                dest.unlink()
            if dest.parent.exists() and not any(dest.parent.iterdir()):
                dest.parent.rmdir()
            if dest.parent.parent.exists() and not any(dest.parent.parent.iterdir()):
                dest.parent.parent.rmdir()

    def test_blackboard_fetch_without_cookie_makes_no_request_and_fails_clearly(self) -> None:
        # Force "no cookie available" deterministically, never reading the
        # real environment or macOS Keychain during a test run.
        from contextlib import redirect_stderr
        from unittest.mock import patch

        stderr = io.StringIO()
        with patch("university_jarvis.cli.get_blackboard_session_cookie", return_value=None), patch(
            "university_jarvis.cli.browser_profile_exists", return_value=False
        ):
            with redirect_stderr(stderr):
                rc = main(["blackboard-fetch", "SYN101", "--week", "1", "--title", "This Week", "--base-url", "https://blackboard.example.test"])
        self.assertEqual(rc, 2)
        self.assertIn("No Blackboard session found", stderr.getvalue())

    def test_module_code_is_matched_against_resolved_course_not_internal_id(self) -> None:
        # Regression: the human-readable module code must be matched against
        # the resolved /courses/{id} record, never against the membership's
        # internal system id.
        import io as io_module
        from contextlib import redirect_stderr

        client, _ = self._fake_client()
        stderr = io_module.StringIO()
        with redirect_stderr(stderr):
            rc = main(
                ["blackboard-fetch", "_222002_1", "--week", "1", "--title", "This Week"],
                blackboard_client=client,
            )
        self.assertEqual(rc, 2)
        self.assertIn("No enrolled course matched", stderr.getvalue())


class ResolveBlackboardClientPriorityTests(unittest.TestCase):
    """Auth V2 browser profile must always win over a stale legacy cookie."""

    def test_browser_profile_present_and_cookie_present_selects_browser_transport(self) -> None:
        from unittest.mock import patch

        with patch("university_jarvis.cli.browser_profile_exists", return_value=True), patch(
            "university_jarvis.cli.get_blackboard_session_cookie", return_value="stale-cookie=1"
        ), patch("university_jarvis.cli.open_browser_client") as fake_open_browser_client:
            fake_open_browser_client.return_value = "browser-context-manager-sentinel"
            result = _resolve_blackboard_client("https://blackboard.example.test")
        self.assertEqual(result, "browser-context-manager-sentinel")
        fake_open_browser_client.assert_called_once_with(base_url="https://blackboard.example.test")

    def test_browser_profile_absent_and_cookie_present_selects_legacy_fallback(self) -> None:
        from unittest.mock import patch

        with patch("university_jarvis.cli.browser_profile_exists", return_value=False), patch(
            "university_jarvis.cli.get_blackboard_session_cookie", return_value="legacy-cookie=1"
        ):
            with _resolve_blackboard_client("https://blackboard.example.test") as client:
                self.assertIsInstance(client, BlackboardClient)

    def test_neither_present_raises_auth_required(self) -> None:
        from unittest.mock import patch

        from university_jarvis.blackboard import BlackboardError

        with patch("university_jarvis.cli.browser_profile_exists", return_value=False), patch(
            "university_jarvis.cli.get_blackboard_session_cookie", return_value=None
        ):
            with self.assertRaises(BlackboardError):
                _resolve_blackboard_client("https://blackboard.example.test")


if __name__ == "__main__":
    unittest.main()
