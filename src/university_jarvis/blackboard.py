"""Read-only Blackboard Learn client for user-invoked retrieval workflows.

Requests use Blackboard Learn REST API paths. Response shapes can vary by
institution and deployment; the code handles known documented representations.
No autonomous crawling, writes, or persistence of raw API responses.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from .sources import PROJECT_ROOT
from .state import StateError

HttpGet = Callable[[str, dict[str, str]], "HttpResponse"]


DEFAULT_BASE_URL: str | None = None


class BlackboardError(StateError):
    """Raised for Blackboard client failures that are not auth failures."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BlackboardAuthError(BlackboardError):
    """Raised when Blackboard rejects the supplied session (401)."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


@dataclass(frozen=True)
class Attachment:
    file_name: str
    url: str
    mimetype: str | None = None


def _default_http_get(url: str, headers: dict[str, str]) -> HttpResponse:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return HttpResponse(status=response.status, body=response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(status=exc.code, body=exc.read())


@dataclass(frozen=True)
class BlackboardSession:
    """An authenticated Blackboard browser session.

    ``cookie_header`` is the raw ``Cookie`` header value copied from an
    authenticated browser session (Blackboard Learn's public REST API here
    is being driven by browser session auth, not an OAuth app registration).
    It is held only in memory for the lifetime of this object and is never
    logged, printed, or written to disk.

    ``cookie_header`` is ``None`` for the Auth V2 persistent-browser transport
    (see ``blackboard_browser``), where the browser context itself owns the
    cookie jar and no cookie is ever read into this process.
    """

    base_url: str
    cookie_header: str | None = None

    def __repr__(self) -> str:  # never leak the cookie into logs/tracebacks
        return f"BlackboardSession(base_url={self.base_url!r}, cookie_header=<redacted>)"


class BlackboardClient:
    """Minimal read-only client over the proven Blackboard REST endpoints."""

    def __init__(self, session: BlackboardSession, http_get: HttpGet = _default_http_get) -> None:
        self._session = session
        self._http_get = http_get

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._session.cookie_header:
            headers["Cookie"] = self._session.cookie_header
        return headers

    def get_json(self, path: str) -> dict[str, Any]:
        """GET a Blackboard REST path (relative to base_url) and parse JSON."""
        url = f"{self._session.base_url.rstrip('/')}{path}"
        response = self._http_get(url, self._headers())
        if response.status == 401:
            raise BlackboardAuthError(
                "Blackboard session was rejected (401). If using the Auth V2 persistent "
                "browser, run `serapis blackboard-auth` again; if using the legacy cookie "
                "path, supply a fresh session cookie."
            )
        if response.status != 200:
            raise BlackboardError(
                f"Blackboard request failed ({response.status}): {path}", status=response.status
            )
        try:
            return json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise BlackboardError(f"Blackboard returned invalid JSON for {path}") from exc

    def list_courses(self) -> list[dict[str, Any]]:
        """List the authenticated user's course memberships.

        Each membership's ``courseId`` field is Blackboard's *internal* system
        id (e.g. ``_123456_1``), not the human-readable course code — use
        ``get_course`` to resolve it to the actual course record.
        """
        return self.get_json("/learn/api/public/v1/users/me/courses").get("results", [])

    def get_course(self, course_system_id: str) -> dict[str, Any]:
        """Fetch one course record by its internal system id.

        The returned record's ``courseId`` field is the human-readable course
        code; ``id`` echoes the internal system id used in
        content-tree paths.
        """
        return self.get_json(f"/learn/api/public/v1/courses/{course_system_id}")

    def list_contents(self, course_id: str, parent_content_id: str | None = None) -> list[dict[str, Any]]:
        """List top-level contents, or the children of one content node."""
        if parent_content_id is None:
            path = f"/learn/api/public/v1/courses/{course_id}/contents"
        else:
            path = f"/learn/api/public/v1/courses/{course_id}/contents/{parent_content_id}/children"
        return self.get_json(path).get("results", [])

    def download_attachment(self, url: str, dest: Path) -> Path:
        """Stream one attachment to ``dest``. ``dest``'s parent must already exist.

        ``url`` may be absolute or relative to ``base_url`` (Blackboard's
        embedded attachment metadata has returned relative resource paths).
        """
        absolute_url = url if "://" in url else f"{self._session.base_url.rstrip('/')}{url}"
        response = self._http_get(absolute_url, self._headers())
        if response.status == 401:
            raise BlackboardAuthError("Blackboard session was rejected (401) during download.")
        if response.status != 200:
            raise BlackboardError(f"Attachment download failed ({response.status}): {absolute_url}")
        dest.write_bytes(response.body)
        return dest


def resolve_course(client: BlackboardClient, memberships: list[dict[str, Any]], needle: str) -> dict[str, Any]:
    """Resolve one enrolled course whose human-readable code/name matches ``needle``.

    Membership records only carry Blackboard's internal system id, so each
    membership's course record is fetched (bounded by the caller's own
    enrollment count — not a crawl) and matched against its real
    ``courseId``/``name``/``displayName`` fields.

    A membership whose own course-detail lookup is inaccessible (403/404 —
    e.g. a course/org your role can't view via this API) is skipped rather
    than aborting the whole resolution. Any other failure, including a 401
    (session-wide auth rejection), still stops resolution immediately.
    """
    lowered = needle.lower()
    candidates: list[dict[str, Any]] = []
    for membership in memberships:
        system_id = membership.get("courseId")
        if not isinstance(system_id, str):
            continue
        try:
            course = client.get_course(system_id)
        except BlackboardAuthError:
            raise
        except BlackboardError as exc:
            if exc.status in (403, 404):
                continue
            raise
        if _course_matches(course, lowered):
            candidates.append(course)

    if not candidates:
        raise BlackboardError(f"No enrolled course matched: {needle}")
    if len(candidates) > 1:
        raise BlackboardError(f"Multiple enrolled courses matched: {needle}")
    return candidates[0]


def _course_matches(course: dict[str, Any], lowered_needle: str) -> bool:
    fields = (
        course.get("courseId"),
        course.get("name"),
        course.get("displayName"),
    )
    return any(isinstance(field, str) and lowered_needle in field.lower() for field in fields)


def find_content_by_title(
    client: BlackboardClient,
    course_id: str,
    title_needle: str,
    *,
    max_depth: int = 4,
) -> dict[str, Any]:
    """Depth-first search course contents for one node whose title contains ``title_needle``.

    Explicit, bounded (``max_depth``) traversal invoked once per user request —
    not background/autonomous crawling.
    """
    lowered = title_needle.lower()
    root_contents = client.list_contents(course_id)
    match = _search_contents(client, course_id, root_contents, lowered, max_depth)
    if match is None:
        raise BlackboardError(f"No content matched title: {title_needle}")
    return match


def _search_contents(
    client: BlackboardClient,
    course_id: str,
    contents: list[dict[str, Any]],
    lowered_needle: str,
    remaining_depth: int,
) -> dict[str, Any] | None:
    for node in contents:
        title = node.get("title")
        if isinstance(title, str) and lowered_needle in title.lower():
            return node
    if remaining_depth <= 0:
        return None
    for node in contents:
        content_id = node.get("id")
        if not content_id or not node.get("hasChildren"):
            continue
        children = client.list_contents(course_id, content_id)
        found = _search_contents(client, course_id, children, lowered_needle, remaining_depth - 1)
        if found is not None:
            return found
    return None


_FILE_LIKE_HINTS = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx")


class _AnchorHrefExtractor(HTMLParser):
    """Pulls (href, link-text) pairs out of an ultraDocumentBody HTML fragment."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = next((value for name, value in attrs if name == "href" and value), None)
        self._current_href = href
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href is not None:
            self.links.append((self._current_href, "".join(self._current_text).strip()))
            self._current_href = None
            self._current_text = []


def _looks_like_a_file_link(href: str, text: str) -> bool:
    # Require an explicit document-file extension. A generic Blackboard
    # resource/attachment path alone is not enough signal — the same kind of
    # path may also serve non-document assets, so file extensions are required.
    lowered_href = href.lower()
    lowered_text = text.lower()
    return any(hint in lowered_href for hint in _FILE_LIKE_HINTS) or any(
        hint in lowered_text for hint in _FILE_LIKE_HINTS
    )


def _file_name_from_link(href: str, text: str) -> str:
    for candidate in (text, href):
        for hint in _FILE_LIKE_HINTS:
            if hint in candidate.lower():
                # Take the trailing path/text segment so a full URL still yields a bare file name.
                return candidate.rsplit("/", 1)[-1].strip()
    return text.strip() or href.rsplit("/", 1)[-1]


def _attachments_from_html(html_text: str) -> list[Attachment]:
    parser = _AnchorHrefExtractor()
    parser.feed(html_text)
    attachments: list[Attachment] = []
    for href, text in parser.links:
        if not _looks_like_a_file_link(href, text):
            continue
        attachments.append(Attachment(file_name=_file_name_from_link(href, text), url=href))
    return attachments


def _attachments_from_structured_list(raw_attachments: list[Any]) -> list[Attachment]:
    """Unconfirmed fallback shape: a structured ``attachments`` list on ultraDocumentBody.

    Not observed in the proven Example University response; kept only in case a
    different Blackboard tenant or content type exposes it this way.
    """
    attachments: list[Attachment] = []
    for entry in raw_attachments:
        if not isinstance(entry, dict):
            continue
        file_name = entry.get("fileName") or entry.get("name")
        url = entry.get("url") or entry.get("href")
        if not isinstance(file_name, str) or not isinstance(url, str):
            continue
        mimetype = entry.get("mimeType") if isinstance(entry.get("mimeType"), str) else None
        attachments.append(Attachment(file_name=file_name, url=url, mimetype=mimetype))
    return attachments


def extract_attachments(content_node: dict[str, Any]) -> list[Attachment]:
    """Extract attachment metadata embedded in a content node.

    Proven (observed against the real Example University response, on a
    ``resource/x-bb-document`` content item): the node's top-level ``body``
    field is a plain HTML string whose anchor tags reference the lecture PDF
    and its Blackboard resource/download path. Parsing that HTML is the
    primary path here.

    Assumed/unconfirmed, kept only as fallbacks since never observed directly:
    an ``ultraDocumentBody`` dict carrying the same kind of HTML
    (``rawText``/``text``/``html``), or a structured
    ``ultraDocumentBody.attachments`` list.
    """
    attachments: list[Attachment] = []

    top_level_body = content_node.get("body")
    if isinstance(top_level_body, str):
        attachments.extend(_attachments_from_html(top_level_body))

    ultra_body = content_node.get("ultraDocumentBody")
    if isinstance(ultra_body, dict):
        html_text = ultra_body.get("rawText") or ultra_body.get("text") or ultra_body.get("html")
        if isinstance(html_text, str):
            attachments.extend(_attachments_from_html(html_text))

        raw_attachments = ultra_body.get("attachments")
        if isinstance(raw_attachments, list):
            attachments.extend(_attachments_from_structured_list(raw_attachments))

    deduped: list[Attachment] = []
    seen_urls: set[str] = set()
    for attachment in attachments:
        if attachment.url in seen_urls:
            continue
        seen_urls.add(attachment.url)
        deduped.append(attachment)
    return deduped


def sources_destination(module_code: str, week: int, file_name: str) -> Path:
    """The gitignored sources/<module>/week-<NN>/<file> path for a retrieved attachment."""
    return PROJECT_ROOT / "sources" / module_code.upper() / f"week-{week:02d}" / file_name


def retrieve_attachment(
    client: BlackboardClient,
    course_id: str,
    title_needle: str,
    module_code: str,
    week: int,
) -> Path:
    """Find one content node by title, download its first attachment into ``sources/``.

    User-invoked, single-target retrieval only. Does not touch
    ``data/academic-state.json`` or write any raw Blackboard response to disk;
    only the attachment bytes are persisted.
    """
    content_node = find_content_by_title(client, course_id, title_needle)
    attachments = extract_attachments(content_node)

    if not attachments and content_node.get("hasChildren"):
        # Proven case: the attachment-bearing document is one level below the
        # title match (e.g. a single resource/x-bb-document child of "This
        # Week"), not on the matched node itself.
        for child in client.list_contents(course_id, content_node["id"]):
            attachments = extract_attachments(child)
            if attachments:
                break

    if not attachments:
        raise BlackboardError(f"Content matched '{title_needle}' but has no attachments")

    attachment = attachments[0]
    dest = sources_destination(module_code, week, attachment.file_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return client.download_attachment(attachment.url, dest)


# --- Intake V1: multi-module/week discovery + classification -------------
#
# Content structures vary by institution; discovery is bounded by folder depth.

_WEEK_TITLE_RE = re.compile(r"\bweek\s*(\d+)\b", re.IGNORECASE)

_TOOL_LINK_HANDLER_PREFIXES = ("resource/x-bb-blti-link", "resource/x-bb-bltiplacement")
_EXTERNAL_LINK_HANDLER = "resource/x-bb-externallink"
_FOLDER_HANDLER = "resource/x-bb-folder"
_DOCUMENT_HANDLER = "resource/x-bb-document"

WEEK_NOT_YET_PUBLISHED = "WEEK_NOT_YET_PUBLISHED"
WEEK_DISCOVERED = "DISCOVERED"
WEEK_AMBIGUOUS_DUPLICATE = "AMBIGUOUS_DUPLICATE_WEEK"

SKIPPED_TOOL_LINK = "SKIPPED_TOOL_LINK"
SKIPPED_EXTERNAL = "SKIPPED_EXTERNAL"
AMBIGUOUS_WEEK_STRUCTURE = "AMBIGUOUS_WEEK_STRUCTURE"


@dataclass(frozen=True)
class ContentRef:
    """One node's identity/lineage breadcrumb — never the filename.

    ``modified``/``created`` are Blackboard's own opaque node-level metadata
    strings (live-proven present and stable across repeated unchanged reads
    against both SYN101 and SYN102, and not guaranteed to change under
    a real content edit). Treated as opaque values only — never parsed as
    dates, never treated as a cryptographic or guaranteed change signal.
    """

    content_id: str | None
    title: str | None
    content_handler: str | None
    modified: str | None = None
    created: str | None = None


@dataclass(frozen=True)
class DiscoveredAttachment:
    """One retrievable attachment plus the content-id lineage it came from."""

    attachment: Attachment
    source_path: tuple[ContentRef, ...]


@dataclass(frozen=True)
class SkippedItem:
    """A node deliberately not treated as retrievable, and why."""

    reason: str
    source_path: tuple[ContentRef, ...]


@dataclass(frozen=True)
class WeekContent:
    """Discovery+classification result for one teaching week of one course."""

    course_id: str
    week_number: int
    lesson_title: str
    lesson_content_id: str
    status: str
    attachments: list[DiscoveredAttachment] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)


def _content_handler_id(node: dict[str, Any]) -> str | None:
    handler = node.get("contentHandler")
    return handler.get("id") if isinstance(handler, dict) else None


def _content_ref(node: dict[str, Any]) -> ContentRef:
    modified = node.get("modified")
    created = node.get("created")
    return ContentRef(
        content_id=node.get("id"),
        title=node.get("title"),
        content_handler=_content_handler_id(node),
        modified=modified if isinstance(modified, str) else None,
        created=created if isinstance(created, str) else None,
    )


def _classify_node(
    client: BlackboardClient,
    course_id: str,
    node: dict[str, Any],
    path: tuple[ContentRef, ...],
    remaining_depth: int,
    attachments: list[DiscoveredAttachment],
    skipped: list[SkippedItem],
) -> None:
    ref = _content_ref(node)
    full_path = path + (ref,)
    handler_id = ref.content_handler

    if handler_id is None:
        skipped.append(SkippedItem(AMBIGUOUS_WEEK_STRUCTURE, full_path))
        return

    if handler_id.startswith(_TOOL_LINK_HANDLER_PREFIXES):
        skipped.append(SkippedItem(SKIPPED_TOOL_LINK, full_path))
        return

    if handler_id == _EXTERNAL_LINK_HANDLER:
        skipped.append(SkippedItem(SKIPPED_EXTERNAL, full_path))
        return

    if handler_id == _DOCUMENT_HANDLER:
        # A document with no extractable attachment (e.g. plain overview
        # text) is not ambiguous — it is simply nothing to retrieve.
        for attachment in extract_attachments(node):
            attachments.append(DiscoveredAttachment(attachment, full_path))
        return

    if handler_id == _FOLDER_HANDLER:
        content_id = ref.content_id
        if remaining_depth <= 0 or not content_id:
            skipped.append(SkippedItem(AMBIGUOUS_WEEK_STRUCTURE, full_path))
            return
        children = client.list_contents(course_id, content_id)
        if not children:
            # An empty folder under a published week is not the same
            # evidence as an empty week lesson (WEEK_NOT_YET_PUBLISHED) —
            # the week itself is live, this one branch just doesn't resolve
            # to anything known. Surfaced rather than silently dropped.
            skipped.append(SkippedItem(AMBIGUOUS_WEEK_STRUCTURE, full_path))
            return
        for child in children:
            _classify_node(client, course_id, child, full_path, remaining_depth - 1, attachments, skipped)
        return

    # Any other/unrecognised contentHandler: never guess.
    skipped.append(SkippedItem(AMBIGUOUS_WEEK_STRUCTURE, full_path))


def _root_week_lesson_nodes(root_contents: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """Group root-level ``resource/x-bb-lesson`` nodes by their ``Week <number>`` title token.

    Grouped (rather than flattened) so a genuine duplicate week number --
    two distinct root lessons both matching the same week -- is visible to
    the caller instead of silently picked between.
    """
    by_week: dict[int, list[dict[str, Any]]] = {}
    for node in root_contents:
        title = node.get("title")
        if not isinstance(title, str) or _content_handler_id(node) != "resource/x-bb-lesson":
            continue
        match = _WEEK_TITLE_RE.search(title)
        if not match or not node.get("id"):
            continue
        by_week.setdefault(int(match.group(1)), []).append(node)
    return by_week


def discover_week_content(
    client: BlackboardClient,
    course_id: str,
    *,
    max_folder_depth: int = 2,
) -> list[WeekContent]:
    """Discover and classify this course's teaching-week content, read-only.

    Only root-level nodes whose title contains ``Week <number>`` are treated
    as teaching weeks (the only title token proven stable across differently
    structured modules). Each week's subtree is traversed up to
    ``max_folder_depth`` folder levels below the week lesson — the deepest
    level needed for bounded discovery. Nothing is downloaded or written; this only
    classifies what is there.

    Two distinct root lessons resolving to the same week number is never
    auto-resolved -- that week is reported once, with status
    ``WEEK_AMBIGUOUS_DUPLICATE`` and no attachments/skipped items, rather
    than silently picking (or merging) one of the candidates.
    """
    weeks: list[WeekContent] = []
    for week_number, nodes in sorted(_root_week_lesson_nodes(client.list_contents(course_id)).items()):
        if len(nodes) > 1:
            first = nodes[0]
            weeks.append(
                WeekContent(course_id, week_number, first.get("title"), first["id"], WEEK_AMBIGUOUS_DUPLICATE)
            )
            continue

        node = nodes[0]
        title = node.get("title")
        lesson_id = node["id"]

        if not node.get("hasChildren"):
            weeks.append(WeekContent(course_id, week_number, title, lesson_id, WEEK_NOT_YET_PUBLISHED))
            continue

        children = client.list_contents(course_id, lesson_id)
        if not children:
            weeks.append(WeekContent(course_id, week_number, title, lesson_id, WEEK_NOT_YET_PUBLISHED))
            continue

        root_ref = ContentRef(lesson_id, title, "resource/x-bb-lesson")
        attachments: list[DiscoveredAttachment] = []
        skipped: list[SkippedItem] = []
        for child in children:
            _classify_node(client, course_id, child, (root_ref,), max_folder_depth, attachments, skipped)

        weeks.append(
            WeekContent(course_id, week_number, title, lesson_id, WEEK_DISCOVERED, attachments, skipped)
        )

    return weeks


# --- Milestone 5C: university-wide teaching-module scope discovery --------
#
# Scope discovery reuses the same week-title classification.

REASON_COURSE_RESOLVE_FAILED = "COURSE_RESOLVE_FAILED"
REASON_MISSING_MODULE_CODE = "MISSING_MODULE_CODE"
REASON_DUPLICATE_MODULE_CODE = "DUPLICATE_MODULE_CODE"


@dataclass(frozen=True)
class ScopeIssue:
    """One membership/course that automatic scope discovery could not safely resolve."""

    reason: str
    course_system_id: str | None
    detail: str | None = None


@dataclass(frozen=True)
class TeachingModule:
    """One automatically-scoped teaching module and its discovered weeks."""

    course_system_id: str
    module_code: str
    weeks: list[WeekContent]


@dataclass(frozen=True)
class TeachingScope:
    """Result of one automatic university-wide scope-discovery pass."""

    modules: list[TeachingModule] = field(default_factory=list)
    issues: list[ScopeIssue] = field(default_factory=list)


def _derive_module_code(course: dict[str, Any]) -> str | None:
    """Derive a short ledger-grouping code from Blackboard's own ``courseId`` field.

    The ``courseId`` may contain a term suffix. The leading underscore-
    delimited segment is used as the grouping identifier. It is not derived
    from ``name`` or ``displayName`` title text.
    """
    course_id = course.get("courseId")
    if not isinstance(course_id, str) or not course_id.strip():
        return None
    code = course_id.split("_", 1)[0].strip().upper()
    return code or None


def _has_teaching_week(root_contents: list[dict[str, Any]]) -> bool:
    return bool(_root_week_lesson_nodes(root_contents))


def discover_teaching_scope(client: BlackboardClient) -> TeachingScope:
    """Discover, read-only, which of this account's course memberships are teaching modules.

    Re-derived fresh on every call -- nothing about "is a teaching module"
    is ever cached or assumed stable across runs. A membership whose course
    detail 403/404s is skipped silently (identical to ``resolve_course``'s
    proven behavior for a course the caller's role can't view). Any other
    resolve/listing failure is surfaced as a ``ScopeIssue`` rather than
    silently dropping that membership from the run. A resolved course with
    zero root week-shaped lessons is excluded as a normal, expected outcome
    is excluded as a normal outcome, not an issue.

    A course whose derived module code collides with another distinct
    course's derived code in the same pass is excluded from ``modules`` and
    reported as a ``ScopeIssue`` (``REASON_DUPLICATE_MODULE_CODE``) for
    both -- ledger grouping by module code must never conflate two
    genuinely different courses.
    """
    resolved: list[tuple[str, dict[str, Any]]] = []
    issues: list[ScopeIssue] = []

    for membership in client.list_courses():
        system_id = membership.get("courseId")
        if not isinstance(system_id, str):
            continue
        try:
            course = client.get_course(system_id)
        except BlackboardAuthError:
            raise
        except BlackboardError as exc:
            if exc.status in (403, 404):
                continue
            issues.append(ScopeIssue(REASON_COURSE_RESOLVE_FAILED, system_id, str(exc)))
            continue
        resolved.append((system_id, course))

    candidates: list[tuple[str, str]] = []  # (course_system_id, module_code)
    for system_id, course in resolved:
        try:
            root_contents = client.list_contents(system_id)
        except BlackboardAuthError:
            raise
        except BlackboardError as exc:
            issues.append(ScopeIssue(REASON_COURSE_RESOLVE_FAILED, system_id, str(exc)))
            continue

        if not _has_teaching_week(root_contents):
            continue

        module_code = _derive_module_code(course)
        if module_code is None:
            issues.append(ScopeIssue(REASON_MISSING_MODULE_CODE, system_id, None))
            continue
        candidates.append((system_id, module_code))

    code_owners: dict[str, list[str]] = {}
    for system_id, module_code in candidates:
        code_owners.setdefault(module_code, []).append(system_id)

    modules: list[TeachingModule] = []
    for system_id, module_code in candidates:
        if len(code_owners[module_code]) > 1:
            issues.append(ScopeIssue(REASON_DUPLICATE_MODULE_CODE, system_id, module_code))
            continue
        weeks = discover_week_content(client, system_id)
        modules.append(TeachingModule(system_id, module_code, weeks))

    return TeachingScope(modules, issues)
