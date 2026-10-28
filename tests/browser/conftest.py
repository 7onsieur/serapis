"""Real-browser (Playwright/Chromium) fixtures for the Hub.

Each test gets its own disposable SERAPIS_HOME and a loopback-only uvicorn
server with a provider that fails if any AI call is attempted. The suite-wide
socket guard is relaxed here for 127.0.0.1/localhost only.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

# Strict mode (release/A3 verification): set SERAPIS_REQUIRE_BROWSER_TESTS=1 and a browser that
# cannot launch, a missing Playwright, or any skipped browser test FAILS the run instead of
# being skipped, and all EXPECTED_BROWSER_TESTS must execute and pass. Without it, the browser
# tests skip quietly when browser tooling is absent.
#
# Chromium: Playwright 1.64 expects Chromium build 1248; only build 1243 may be cached. Without
# downloading anything, point SERAPIS_BROWSER_EXECUTABLE at an installed binary, e.g.
#   ~/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell
STRICT = os.environ.get("SERAPIS_REQUIRE_BROWSER_TESTS") == "1"
EXPECTED_BROWSER_TESTS = 6

try:
    import uvicorn  # noqa: E402
    from playwright.sync_api import sync_playwright  # noqa: E402
except ImportError as exc:
    if STRICT:
        raise RuntimeError(f"Strict browser verification requested but Playwright/uvicorn is unavailable: {exc}") from exc
    pytest.skip(f"Playwright unavailable: {exc}", allow_module_level=True)

_results: dict[str, str] = {}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if "browser" not in item.nodeid.split("/")[:2]:
        return
    if STRICT and report.skipped:
        report.outcome = "failed"
        report.longrepr = f"Strict browser verification: test was skipped instead of executed ({report.longrepr})"
    if report.when == "call" or report.outcome == "failed" or (report.when == "setup" and report.outcome != "passed"):
        _results[item.nodeid] = report.outcome


def pytest_sessionfinish(session, exitstatus):
    if not STRICT or not _results and not any("tests/browser" in i.nodeid for i in session.items):
        return
    passed = sum(1 for outcome in _results.values() if outcome == "passed")
    if passed != EXPECTED_BROWSER_TESTS and session.exitstatus == 0:
        session.exitstatus = 1
        print(f"\nStrict browser verification FAILED: {passed} of {EXPECTED_BROWSER_TESTS} browser tests passed.")

_REAL_CONNECT = socket.socket.connect


def _loopback_only_connect(self, address, *args, **kwargs):
    if isinstance(address, tuple) and address[0] in ("127.0.0.1", "localhost", "::1"):
        return _REAL_CONNECT(self, address, *args, **kwargs)
    raise AssertionError(f"Browser test attempted a non-loopback connection: {address!r}")


@pytest.fixture(autouse=True)
def _allow_loopback(monkeypatch, _block_real_network_calls):
    monkeypatch.setattr(socket.socket, "connect", _loopback_only_connect)


def _no_ai(*_args, **_kwargs):
    raise AssertionError("Browser tests must never call an AI provider")


@pytest.fixture
def hub(tmp_path, monkeypatch, _allow_loopback):
    monkeypatch.setenv("SERAPIS_HOME", str(tmp_path / "home"))
    from university_jarvis.hub_web import create_app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(reasoning_provider=_no_ai), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("Hub test server did not start")
        time.sleep(0.05)
    yield {"url": f"http://127.0.0.1:{port}", "home": tmp_path / "home"}
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture
def page(hub):
    with sync_playwright() as p:
        try:
            # SERAPIS_BROWSER_EXECUTABLE reuses an already-installed Chromium when the
            # bundled build for this Playwright version is not downloaded.
            browser = p.chromium.launch(executable_path=os.environ.get("SERAPIS_BROWSER_EXECUTABLE") or None)
        except Exception as exc:  # browser binary missing
            if STRICT:
                pytest.fail(f"Strict browser verification: Chromium could not launch: {exc}")
            pytest.skip(f"Chromium unavailable: {exc}")
        context = browser.new_context(base_url=hub["url"])
        page = context.new_page()
        yield page
        browser.close()
