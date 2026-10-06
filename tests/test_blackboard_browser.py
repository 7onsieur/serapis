from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from university_jarvis.blackboard_browser import (
    AuthRequiredError,
    _bootstrap_session,
    _looks_like_login_redirect,
    browser_profile_exists,
    open_browser_client,
)


class FakePage:
    def __init__(self, final_url: str) -> None:
        self.url = final_url
        self.goto_called_with: str | None = None
        self.waited_for_load_state: str | None = None
        self.closed = False

    def goto(self, url: str) -> None:
        self.goto_called_with = url

    def wait_for_load_state(self, state: str) -> None:
        self.waited_for_load_state = state

    def close(self) -> None:
        self.closed = True


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self._page = page

    def new_page(self) -> FakePage:
        return self._page


class LoginRedirectDetectionTests(unittest.TestCase):
    def test_authenticated_dashboard_url_is_not_a_login_redirect(self) -> None:
        self.assertFalse(_looks_like_login_redirect("https://blackboard.example.test/ultra/course"))

    def test_login_path_is_detected(self) -> None:
        self.assertTrue(_looks_like_login_redirect("https://blackboard.example.test/webapps/login/"))

    def test_sso_path_is_detected(self) -> None:
        self.assertTrue(_looks_like_login_redirect("https://sso.example.test/idp/profile/SAML2"))


class BootstrapSessionTests(unittest.TestCase):
    def test_authenticated_page_bootstraps_without_error_and_closes_page(self) -> None:
        page = FakePage("https://blackboard.example.test/ultra/course")
        context = FakeContext(page)
        _bootstrap_session(context, "https://blackboard.example.test")
        self.assertEqual(page.goto_called_with, "https://blackboard.example.test")
        self.assertEqual(page.waited_for_load_state, "networkidle")
        self.assertTrue(page.closed)

    def test_login_redirect_raises_auth_required_and_still_closes_page(self) -> None:
        page = FakePage("https://blackboard.example.test/webapps/login/")
        context = FakeContext(page)
        with self.assertRaises(AuthRequiredError):
            _bootstrap_session(context, "https://blackboard.example.test")
        self.assertTrue(page.closed)


class BrowserProfileExistsTests(unittest.TestCase):
    def test_false_when_profile_directory_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / ".jarvis-browser"
            self.assertFalse(browser_profile_exists(missing))

    def test_true_when_profile_directory_present(self) -> None:
        with TemporaryDirectory() as tmp:
            present = Path(tmp) / ".jarvis-browser"
            present.mkdir()
            self.assertTrue(browser_profile_exists(present))


class FakePersistentContext:
    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.closed = False

    def new_page(self) -> FakePage:
        return self._page

    def close(self) -> None:
        self.closed = True


class FakePlaywrightHandle:
    def __init__(self, context: FakePersistentContext) -> None:
        self._context = context
        self.stopped = False

        class _Chromium:
            def launch_persistent_context(_self, *args: object, **kwargs: object) -> FakePersistentContext:
                return context

        self.chromium = _Chromium()

    def stop(self) -> None:
        self.stopped = True


class FakeSyncPlaywrightCM:
    def __init__(self, handle: FakePlaywrightHandle) -> None:
        self._handle = handle

    def start(self) -> FakePlaywrightHandle:
        return self._handle


class BrowserTransportCleanupTests(unittest.TestCase):
    """Bootstrap failure must not leak the browser process/context."""

    def test_expired_session_during_bootstrap_closes_context_and_stops_playwright(self) -> None:
        from unittest.mock import patch

        from university_jarvis.blackboard_browser import _BrowserTransport

        page = FakePage("https://blackboard.example.test/webapps/login/")
        context = FakePersistentContext(page)
        handle = FakePlaywrightHandle(context)

        with TemporaryDirectory() as tmp:
            profile_dir = Path(tmp) / ".jarvis-browser"
            profile_dir.mkdir()
            with patch(
                "playwright.sync_api.sync_playwright",
                return_value=FakeSyncPlaywrightCM(handle),
            ):
                transport = _BrowserTransport(profile_dir, "https://blackboard.example.test")
                with self.assertRaises(AuthRequiredError):
                    transport.__enter__()

        self.assertTrue(page.closed)
        self.assertTrue(context.closed)
        self.assertTrue(handle.stopped)


class OpenBrowserClientAuthRequiredTests(unittest.TestCase):
    def test_raises_auth_required_without_launching_a_browser_when_profile_missing(self) -> None:
        # No Playwright/browser process should ever be touched here -- the
        # missing-profile check must short-circuit before any launch attempt.
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / ".jarvis-browser"
            with self.assertRaises(AuthRequiredError):
                with open_browser_client("https://blackboard.example.test", profile_dir=missing):
                    self.fail("open_browser_client should not yield when the profile is missing")


if __name__ == "__main__":
    unittest.main()
