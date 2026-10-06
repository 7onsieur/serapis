"""Global regression guard: no test in this suite may open a real network socket.

Hub Slice 3 once had a test fall through to the real Blackboard Auth V2
browser resolver because it omitted a fake ``blackboard_client_factory``
override -- this silently launched a real headless browser and navigated to
the live Blackboard host. Every test that exercises an external-capable
route must inject a fake client/provider/transport; this autouse fixture
makes any test that fails to do so fail loudly and immediately instead of
reaching a real network endpoint.

No test anywhere in this repo legitimately needs a real socket: Blackboard
tests already inject a fake ``http_get`` transport, FastAPI's ``TestClient``
uses an in-process ASGI transport (no socket at all), and Drive/OpenAI tests
already inject fakes too.
"""

from __future__ import annotations

import socket

import pytest


def _blocked_connect(*_args, **_kwargs):
    raise AssertionError(
        "Test attempted a real network connection. Inject a fake "
        "client/provider/transport (e.g. blackboard_client_factory, "
        "reasoning_provider) instead of falling through to a real resolver."
    )


@pytest.fixture(autouse=True)
def _block_real_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
