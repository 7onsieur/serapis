"""Blackboard Auth V2: Serapis-owned persistent browser-backed transport.

A dedicated, gitignored Playwright Chromium profile at ``PROFILE_DIR`` -- kept
entirely separate from the user's normal Chrome. You complete your institution's
sign-in/SSO once, by hand, in a headed window (``run_interactive_authentication``);
the persistent profile then carries that session across process restarts, and
the browser context itself owns cookie/session rotation. Normal
``blackboard-fetch`` runs never read, copy, print, or log a cookie -- they
just ask the browser context to make the request.

Playwright is imported lazily inside the functions that need it, so nothing
in the rest of the Blackboard layer (or its tests) needs it installed.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from .blackboard import (
    BlackboardAuthError,
    BlackboardClient,
    BlackboardError,
    BlackboardSession,
    DEFAULT_BASE_URL,
    HttpResponse,
)
from .sources import PROJECT_ROOT

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Playwright

PROFILE_DIR = PROJECT_ROOT / ".jarvis-browser"


class AuthRequiredError(BlackboardAuthError):
    """The Serapis browser profile has no session to use.

    Run ``serapis blackboard-auth`` to complete your institution's sign-in/SSO by hand once;
    the persistent profile then carries the session into future runs.
    """


def browser_profile_exists(profile_dir: Path = PROFILE_DIR) -> bool:
    """Whether the dedicated Serapis browser profile has been set up at all.

    This is a cheap existence check, not proof the saved session is still
    valid -- an expired/rotated-out session is only discovered when a real
    request comes back 401 (see ``BlackboardClient.get_json``).
    """
    return profile_dir.exists()


def run_interactive_authentication(
    base_url: str | None = DEFAULT_BASE_URL, profile_dir: Path = PROFILE_DIR
) -> None:
    """Headed, manual institutional sign-in/SSO setup for the dedicated profile.

    User-invoked only -- never call this automatically. Opens a visible
    Chromium window on ``base_url`` and blocks on terminal input (never on a
    browser "window closed" event, which does not reliably fire) so this
    always exits cleanly and never leaves an orphan browser process.
    """
    if not base_url:
        raise BlackboardError(
            "Blackboard host is required. Set JARVIS_BLACKBOARD_BASE_URL or pass --base-url."
        )
    from playwright.sync_api import sync_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), headless=False)
        try:
            page = context.new_page()
            page.goto(base_url)
            input(
                "Complete your institution's sign-in/SSO in the opened browser window if prompted.\n"
                "Once your Blackboard dashboard has loaded, press Enter here to finish... "
            )
        finally:
            context.close()


_LOGIN_URL_MARKERS = ("login", "sso")


def _looks_like_login_redirect(url: str) -> bool:
    """Whether a post-navigation URL looks like a login/SSO page, not Blackboard itself."""
    lowered = url.lower()
    return any(marker in lowered for marker in _LOGIN_URL_MARKERS)


def _bootstrap_session(context: Any, base_url: str) -> None:
    """Navigate once in ``context`` so Blackboard completes its session handshake.

    Live A/B-tested and proven necessary: a bare ``APIRequestContext`` call on
    a freshly launched persistent context 401s, but the identical call
    succeeds once a page in that *same* context has loaded Blackboard first.
    Uses ``networkidle`` as the completion signal -- no arbitrary sleep.

    Raises ``AuthRequiredError`` if navigation lands on a login/SSO page
    (the saved session has expired) rather than letting later REST calls
    fail with an unexplained 401. The temporary page is always closed,
    success or failure.
    """
    page = context.new_page()
    try:
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        if _looks_like_login_redirect(page.url):
            raise AuthRequiredError(
                "Serapis browser profile session has expired (landed on a login/SSO page). "
                "Run `serapis blackboard-auth` again."
            )
    finally:
        page.close()


class _BrowserTransport:
    """Owns one persistent-context Chromium process for the life of a `with` block."""

    def __init__(self, profile_dir: Path, base_url: str | None = DEFAULT_BASE_URL) -> None:
        if not base_url:
            raise BlackboardError(
                "Blackboard host is required. Set JARVIS_BLACKBOARD_BASE_URL or pass --base-url."
            )
        self._profile_dir = profile_dir
        self._base_url = base_url
        self._playwright: "Playwright | None" = None
        self._context: "BrowserContext | None" = None

    def __enter__(self) -> "_BrowserTransport":
        if not self._profile_dir.exists():
            raise AuthRequiredError(
                "No Serapis browser profile found. Run `serapis blackboard-auth` first."
            )
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self._profile_dir), headless=True
            )
            _bootstrap_session(self._context, self._base_url)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def http_get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        assert self._context is not None
        response = self._context.request.get(url, headers=headers)
        return HttpResponse(status=response.status, body=response.body())


@contextmanager
def open_browser_client(
    base_url: str | None = DEFAULT_BASE_URL, profile_dir: Path = PROFILE_DIR
) -> Iterator[BlackboardClient]:
    """Yield a ``BlackboardClient`` backed by the persistent authenticated browser profile.

    The browser context owns cookie/session rotation entirely; no cookie is
    ever read into this process. A page bootstrap navigation runs once in
    this same context before the client is handed back (see
    ``_bootstrap_session``). Raises ``AuthRequiredError`` immediately if the
    profile has never been set up, or if the saved session has expired. The
    underlying browser process is always closed on exit, including on error.
    """
    if not base_url:
        raise BlackboardError(
            "Blackboard host is required. Set JARVIS_BLACKBOARD_BASE_URL or pass --base-url."
        )
    with _BrowserTransport(profile_dir, base_url) as transport:
        session = BlackboardSession(base_url=base_url)
        yield BlackboardClient(session, http_get=transport.http_get)
