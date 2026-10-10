"""Request guards for the local Hub: DNS-rebinding, CSRF and upload-size limits.

The Hub is a local web application that can spend a student's provider key and
rewrite their academic records, so any web page open in the same browser could
otherwise drive it. Three layers apply, implemented as pure ASGI middleware:

1. Host validation (all methods). The ``Host`` header must name a loopback
   host (or a host explicitly allowed with ``--host``). This defeats DNS
   rebinding, where a hostile domain re-resolves to 127.0.0.1: the browser
   then sends ``Host: hostile.example``.
2. Cross-site request validation (state-changing methods). ``Sec-Fetch-Site``
   must not report a cross-site/same-site request; ``Origin`` (or, if absent,
   ``Referer``) must be same-origin with the ``Host`` header, including port.
3. Upload size (material upload/replace routes). ``Content-Length`` is
   required and capped before the body is read.

Limitation: requests carrying none of ``Origin``, ``Referer`` and
``Sec-Fetch-Site`` are treated as non-browser clients (curl, scripts, tests)
and allowed. Any browser sends at least one of them on a cross-site POST, but
a malicious local *process* can always call a local HTTP port; this guard does
not defend against that.
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Iterable
from urllib.parse import urlsplit

#: Largest accepted material file. Lecture decks are typically a few MiB; this
#: leaves ample room while keeping a runaway upload from filling the disk.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
#: Allowance for multipart framing and the small form fields around the file.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SINGLE_VALUE_HEADERS = frozenset({"host", "origin", "referer", "sec-fetch-site", "content-length"})

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


_HOST_RE = re.compile(r"^(?P<name>\[[0-9a-f:.]+\]|[a-z0-9._-]+)(?::[0-9]{1,5})?$", re.IGNORECASE)


def _host_name(netloc: str) -> str:
    """Hostname (lowercase, no port, no brackets) of a strict ``host[:port]``.

    Anything that is not plain ``host[:port]`` (userinfo, backslashes, spaces,
    commas, paths) yields "" and is therefore rejected, avoiding parser
    differentials between this check and the browser/server.
    """
    match = _HOST_RE.fullmatch(netloc)
    if match is None:
        return ""
    return match.group("name").strip("[]").lower()


def is_upload_path(path: str) -> bool:
    return path.endswith("/materials") or (
        path.startswith("/materials/") and path.endswith("/replace")
    )


class HubSecurityMiddleware:
    def __init__(self, app: Callable[..., Awaitable[None]], *, allowed_hosts: Iterable[str] = ()) -> None:
        self.app = app
        self.allowed_hosts = LOOPBACK_HOSTS | {h.lower() for h in allowed_hosts}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        for raw_key, raw_value in scope["headers"]:
            key = raw_key.decode("latin-1").lower()
            if key in headers and key in _SINGLE_VALUE_HEADERS:
                # Ambiguous: components could disagree about which value applies.
                await self._reject(send, 400, f"Duplicate {key} header rejected.")
                return
            headers[key] = raw_value.decode("latin-1")
        problem = self._check(scope["method"], scope["path"], headers)
        if problem is not None:
            status, message = problem
            await self._reject(send, status, message)
            return
        await self.app(scope, receive, send)

    def _check(self, method: str, path: str, headers: dict[str, str]) -> tuple[int, str] | None:
        host = headers.get("host", "")
        if _host_name(host) not in self.allowed_hosts:
            return 403, "Invalid Host header. The Serapis Hub only answers to localhost."
        if method.upper() not in _SAFE_METHODS:
            fetch_site = headers.get("sec-fetch-site")
            if fetch_site is not None and fetch_site not in {"same-origin", "none"}:
                return 403, "Cross-site request rejected."
            origin = headers.get("origin")
            if origin is not None:
                if not self._same_origin(origin, host, strict=True):
                    return 403, "Cross-site request rejected (Origin does not match)."
            else:
                referer = headers.get("referer")
                if referer is not None and not self._same_origin(referer, host):
                    return 403, "Cross-site request rejected (Referer does not match)."
            if method.upper() == "POST" and is_upload_path(path):
                if "transfer-encoding" in headers:
                    # Chunked bodies would bypass the declared-length cap.
                    return 411, "Uploads must declare their size (Content-Length), not use chunked encoding."
                declared = headers.get("content-length")
                if declared is None or not declared.isdigit():
                    return 411, "Uploads must declare their size (Content-Length)."
                if int(declared) > MAX_REQUEST_BYTES:
                    return 413, (
                        f"Upload too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB per file."
                    )
        return None

    @staticmethod
    def _same_origin(value: str, host: str, *, strict: bool = False) -> bool:
        if value == "null":
            return False
        try:
            parts = urlsplit(value)
        except ValueError:
            return False
        if strict and (parts.path not in {"", "/"} or parts.query or parts.fragment):
            return False  # an Origin is only ever scheme://host[:port]
        return parts.scheme in {"http", "https"} and parts.netloc.lower() == host.lower()

    @staticmethod
    async def _reject(send: Send, status: int, message: str) -> None:
        body = message.encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
