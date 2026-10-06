from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.blackboard import (
    AMBIGUOUS_WEEK_STRUCTURE,
    Attachment,
    BlackboardAuthError,
    BlackboardClient,
    BlackboardError,
    BlackboardSession,
    HttpResponse,
    REASON_COURSE_RESOLVE_FAILED,
    REASON_DUPLICATE_MODULE_CODE,
    REASON_MISSING_MODULE_CODE,
    SKIPPED_EXTERNAL,
    SKIPPED_TOOL_LINK,
    WEEK_AMBIGUOUS_DUPLICATE,
    WEEK_DISCOVERED,
    WEEK_NOT_YET_PUBLISHED,
    discover_teaching_scope,
    discover_week_content,
    extract_attachments,
    find_content_by_title,
    resolve_course,
    retrieve_attachment,
    sources_destination,
)

# Synthetic fixtures shaped like common Blackboard responses; no real
# course/content ids, student data, or academic material.
# Membership.courseId is Blackboard's internal system id, per the API shape;
# behaviour — the human-readable code only appears on the resolved course
# record from GET /courses/{system_id}.
MEMBERSHIPS = [
    {"courseId": "_222001_1"},
    {"courseId": "_222002_1"},
]

COURSE_DETAILS = {
    "_222001_1": {"id": "_222001_1", "courseId": "SYN100", "name": "Widgets"},
    "_222002_1": {"id": "_222002_1", "courseId": "SYN200", "name": "Introduction to Example Widgets"},
}

TOP_LEVEL_CONTENTS = [
    {"id": "_1000_1", "title": "Course Overview", "hasChildren": False},
    {"id": "_1001_1", "title": "Week 1", "hasChildren": True},
]

WEEK_1_CHILDREN = [
    {"id": "_1002_1", "title": "This Week", "hasChildren": False},
]

# Synthetic response: ultraDocumentBody.rawText is an
# HTML fragment whose anchor tag references the lecture PDF and its
# Blackboard resource/download path. No real ids/content.
THIS_WEEK_NODE_WITH_ATTACHMENT = {
    "id": "_1002_1",
    "title": "This Week",
    "hasChildren": False,
    "ultraDocumentBody": {
        "rawText": (
            "<p>Slides for this week:</p>"
            '<p><a href="/learn/api/public/v1/courses/_222002_1/contents/_1002_1/'
            'attachments/_9001_1/download">example-lecture.pdf</a></p>'
        )
    },
}

# Unconfirmed/legacy shape kept only as a secondary fallback path.
THIS_WEEK_NODE_WITH_STRUCTURED_ATTACHMENT_LIST = {
    "id": "_1003_1",
    "title": "Legacy Shape Week",
    "hasChildren": False,
    "ultraDocumentBody": {
        "attachments": [
            {
                "fileName": "TEST_Legacy.pdf",
                "url": "/learn/api/public/v1/courses/_222002_1/contents/_1003_1/attachments/_9002_1/download",
                "mimeType": "application/pdf",
            }
        ]
    },
}


class FakeTransport:
    """Maps exact URLs to canned HttpResponse objects; records calls made."""

    def __init__(self, responses: dict[str, HttpResponse]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        if url not in self._responses:
            raise AssertionError(f"Unexpected URL requested: {url}")
        return self._responses[url]


def _json_response(payload: dict) -> HttpResponse:
    import json

    return HttpResponse(status=200, body=json.dumps(payload).encode("utf-8"))


# A membership whose course-detail lookup the caller's role cannot view.
INACCESSIBLE_COURSE_SYSTEM_ID = "_222999_1"


class _CourseDetailTransport:
    """Fake transport serving GET /courses/{system_id} from COURSE_DETAILS.

    ``INACCESSIBLE_COURSE_SYSTEM_ID`` returns 403, simulating a membership
    the caller's role can't view course details for.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        if url.endswith(f"/courses/{INACCESSIBLE_COURSE_SYSTEM_ID}"):
            return HttpResponse(status=403, body=b"")
        for system_id, record in COURSE_DETAILS.items():
            if url.endswith(f"/courses/{system_id}"):
                return _json_response(record)
        raise AssertionError(f"Unexpected URL requested: {url}")


class ResolveCourseTests(unittest.TestCase):
    def _client(self) -> tuple[BlackboardClient, _CourseDetailTransport]:
        transport = _CourseDetailTransport()
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        return BlackboardClient(session, http_get=transport), transport

    def test_resolves_by_human_readable_course_code(self) -> None:
        client, _ = self._client()
        course = resolve_course(client, MEMBERSHIPS, "SYN200")
        self.assertEqual(course["id"], "_222002_1")

    def test_resolves_by_course_name_substring(self) -> None:
        client, _ = self._client()
        course = resolve_course(client, MEMBERSHIPS, "example widgets")
        self.assertEqual(course["id"], "_222002_1")

    def test_raises_when_no_match(self) -> None:
        client, _ = self._client()
        with self.assertRaises(BlackboardError):
            resolve_course(client, MEMBERSHIPS, "nonexistent module")

    def test_raises_when_ambiguous(self) -> None:
        client, _ = self._client()
        with self.assertRaises(BlackboardError):
            resolve_course(client, MEMBERSHIPS, "widget")

    def test_does_not_resolve_by_internal_system_id_alone(self) -> None:
        # The internal system id must not be mistaken for the human-readable
        # course code — this is exactly the bug being fixed.
        client, _ = self._client()
        with self.assertRaises(BlackboardError):
            resolve_course(client, MEMBERSHIPS, "_222002_1")

    def test_skips_inaccessible_membership_and_matches_the_next_one(self) -> None:
        # One membership's course-detail lookup 403s (e.g. a course/org the
        # caller's role can't view); resolution must skip it and still find
        # the real match among the remaining memberships.
        client, transport = self._client()
        memberships = [{"courseId": INACCESSIBLE_COURSE_SYSTEM_ID}, *MEMBERSHIPS]
        course = resolve_course(client, memberships, "SYN200")
        self.assertEqual(course["id"], "_222002_1")
        self.assertTrue(
            any(url.endswith(f"/courses/{INACCESSIBLE_COURSE_SYSTEM_ID}") for url in transport.calls)
        )

    def test_401_during_resolution_aborts_immediately_rather_than_skipping(self) -> None:
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")

        def transport(url: str, headers: dict[str, str]) -> HttpResponse:
            return HttpResponse(status=401, body=b"")

        client = BlackboardClient(session, http_get=transport)
        with self.assertRaises(BlackboardAuthError):
            resolve_course(client, MEMBERSHIPS, "SYN200")


class ExtractAttachmentsTests(unittest.TestCase):
    def test_extracts_file_name_and_url(self) -> None:
        attachments = extract_attachments(THIS_WEEK_NODE_WITH_ATTACHMENT)
        self.assertEqual(
            attachments,
            [
                Attachment(
                    file_name="example-lecture.pdf",
                    url="/learn/api/public/v1/courses/_222002_1/contents/_1002_1/attachments/_9001_1/download",
                )
            ],
        )

    def test_no_ultra_document_body_returns_empty(self) -> None:
        self.assertEqual(extract_attachments({"id": "_1000_1", "title": "Overview"}), [])

    def test_malformed_structured_attachment_entries_are_skipped(self) -> None:
        node = {"ultraDocumentBody": {"attachments": [{"fileName": "no-url.pdf"}, "not-a-dict"]}}
        self.assertEqual(extract_attachments(node), [])

    def test_structured_attachments_list_is_supported_as_fallback(self) -> None:
        attachments = extract_attachments(THIS_WEEK_NODE_WITH_STRUCTURED_ATTACHMENT_LIST)
        self.assertEqual(
            attachments,
            [
                Attachment(
                    file_name="TEST_Legacy.pdf",
                    url="/learn/api/public/v1/courses/_222002_1/contents/_1003_1/attachments/_9002_1/download",
                    mimetype="application/pdf",
                )
            ],
        )

    def test_extracts_from_top_level_body_field(self) -> None:
        # Proven real shape: a resource/x-bb-document child node's plain
        # top-level `body` string, not ultraDocumentBody.
        node = {
            "id": "_1004_1",
            "contentHandler": {"id": "resource/x-bb-document"},
            "body": (
                '<p><a href="/learn/api/public/v1/courses/_222002_1/contents/_1004_1/'
                'attachments/_9003_1/download">TEST_Document_Lecture1.pdf</a></p>'
            ),
        }
        attachments = extract_attachments(node)
        self.assertEqual(
            attachments,
            [
                Attachment(
                    file_name="TEST_Document_Lecture1.pdf",
                    url="/learn/api/public/v1/courses/_222002_1/contents/_1004_1/attachments/_9003_1/download",
                )
            ],
        )

    def test_html_body_with_non_file_links_is_ignored(self) -> None:
        node = {
            "ultraDocumentBody": {
                "rawText": '<p>See <a href="https://example.test/info">course info</a> for details.</p>'
            }
        }
        self.assertEqual(extract_attachments(node), [])

    def test_html_body_link_text_without_extension_still_matches_by_href_extension(self) -> None:
        node = {
            "ultraDocumentBody": {
                "rawText": (
                    '<a href="/learn/api/public/v1/courses/_222002_1/contents/_1002_1/'
                    'attachments/_9001_1/download/SBM_Lecture1.pdf">Lecture slides</a>'
                )
            }
        }
        attachments = extract_attachments(node)
        self.assertEqual(len(attachments), 1)
        # Link text has no extension; the href's real filename is preferred.
        self.assertEqual(attachments[0].file_name, "SBM_Lecture1.pdf")

    def test_generic_resource_path_without_file_extension_is_not_matched(self) -> None:
        # Regression: a generic Blackboard attachment/resource path is not
        # enough signal on its own — decorative images use the same kind of
        # path (a non-document asset should not be matched before this
        # fix). Only an explicit document-file extension counts.
        node = {
            "body": (
                '<a href="/learn/api/public/v1/courses/_222002_1/contents/_1002_1/'
                'attachments/_9005_1/download">Information Banner</a>'
            )
        }
        self.assertEqual(extract_attachments(node), [])


class ClientTraversalTests(unittest.TestCase):
    def _client(self, transport: FakeTransport) -> BlackboardClient:
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        return BlackboardClient(session, http_get=transport)

    def test_list_courses_parses_results(self) -> None:
        transport = FakeTransport(
            {
                "https://blackboard.example.test/learn/api/public/v1/users/me/courses": _json_response(
                    {"results": MEMBERSHIPS}
                )
            }
        )
        client = self._client(transport)
        self.assertEqual(client.list_courses(), MEMBERSHIPS)

    def test_401_raises_auth_error(self) -> None:
        transport = FakeTransport(
            {
                "https://blackboard.example.test/learn/api/public/v1/users/me/courses": HttpResponse(
                    status=401, body=b""
                )
            }
        )
        client = self._client(transport)
        with self.assertRaises(BlackboardAuthError):
            client.list_courses()

    def test_find_content_by_title_recurses_into_children(self) -> None:
        base = "https://blackboard.example.test/learn/api/public/v1/courses/_222002_1"
        transport = FakeTransport(
            {
                f"{base}/contents": _json_response({"results": TOP_LEVEL_CONTENTS}),
                f"{base}/contents/_1001_1/children": _json_response({"results": WEEK_1_CHILDREN}),
            }
        )
        client = self._client(transport)
        node = find_content_by_title(client, "_222002_1", "this week")
        self.assertEqual(node["id"], "_1002_1")

    def test_find_content_by_title_raises_when_absent(self) -> None:
        base = "https://blackboard.example.test/learn/api/public/v1/courses/_222002_1"
        transport = FakeTransport({f"{base}/contents": _json_response({"results": TOP_LEVEL_CONTENTS})})
        client = self._client(transport)
        with self.assertRaises(BlackboardError):
            find_content_by_title(client, "_222002_1", "nonexistent title", max_depth=0)


class RetrieveAttachmentTests(unittest.TestCase):
    def test_downloads_first_attachment_into_sources(self) -> None:
        base = "https://blackboard.example.test/learn/api/public/v1/courses/_222002_1"
        download_url = "https://blackboard.example.test/learn/api/public/v1/courses/_222002_1/contents/_1002_1/attachments/_9001_1/download"
        transport = FakeTransport(
            {
                f"{base}/contents": _json_response({"results": [WEEK_1_CHILDREN[0]]}),
                download_url: HttpResponse(status=200, body=b"%PDF-fake-bytes"),
            }
        )
        # Override the extracted node to carry the attachment payload for this test.
        node_with_attachment = {**WEEK_1_CHILDREN[0], **THIS_WEEK_NODE_WITH_ATTACHMENT}
        transport._responses[f"{base}/contents"] = _json_response({"results": [node_with_attachment]})
        transport._responses[download_url] = HttpResponse(status=200, body=b"%PDF-fake-bytes")

        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        client = BlackboardClient(session, http_get=transport)

        dest = sources_destination("SYN200", 1, "example-lecture.pdf")
        try:
            result = retrieve_attachment(client, "_222002_1", "this week", "SYN200", 1)
            self.assertEqual(result, dest)
            self.assertEqual(dest.read_bytes(), b"%PDF-fake-bytes")
        finally:
            if dest.exists():
                dest.unlink()
            if dest.parent.exists():
                dest.parent.rmdir()
            if dest.parent.parent.exists() and not any(dest.parent.parent.iterdir()):
                dest.parent.parent.rmdir()

    def test_raises_when_content_has_no_attachments(self) -> None:
        base = "https://blackboard.example.test/learn/api/public/v1/courses/_222002_1"
        transport = FakeTransport({f"{base}/contents": _json_response({"results": [WEEK_1_CHILDREN[0]]})})
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        client = BlackboardClient(session, http_get=transport)
        with self.assertRaises(BlackboardError):
            retrieve_attachment(client, "_222002_1", "this week", "SYN200", 1)

    def test_descends_into_child_when_matched_node_has_no_attachments(self) -> None:
        # Proven real shape: "This Week" itself carries no attachment; its
        # single resource/x-bb-document child does, via a top-level body field.
        base = "https://blackboard.example.test/learn/api/public/v1/courses/_222002_1"
        download_url = (
            "https://blackboard.example.test/learn/api/public/v1/courses/_222002_1/"
            "contents/_1005_1/attachments/_9004_1/download"
        )
        parent_node = {"id": "_1002_1", "title": "This Week", "hasChildren": True}
        child_node = {
            "id": "_1005_1",
            "contentHandler": {"id": "resource/x-bb-document"},
            "body": f'<a href="/learn/api/public/v1/courses/_222002_1/contents/_1005_1/attachments/_9004_1/download">TEST_Child_Lecture1.pdf</a>',
        }
        transport = FakeTransport(
            {
                f"{base}/contents": _json_response({"results": [parent_node]}),
                f"{base}/contents/_1002_1/children": _json_response({"results": [child_node]}),
                download_url: HttpResponse(status=200, body=b"%PDF-fake-child-bytes"),
            }
        )
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        client = BlackboardClient(session, http_get=transport)

        dest = sources_destination("SYN200", 1, "TEST_Child_Lecture1.pdf")
        try:
            result = retrieve_attachment(client, "_222002_1", "this week", "SYN200", 1)
            self.assertEqual(result, dest)
            self.assertEqual(dest.read_bytes(), b"%PDF-fake-child-bytes")
        finally:
            if dest.exists():
                dest.unlink()
            if dest.parent.exists() and not any(dest.parent.iterdir()):
                dest.parent.rmdir()
            if dest.parent.parent.exists() and not any(dest.parent.parent.iterdir()):
                dest.parent.parent.rmdir()


class DiscoverWeekContentTests(unittest.TestCase):
    """Synthetic fixtures shaped like the two real, structurally different
    synthetic modules, plus an
    empty future-week shell. No real course/content ids or material.
    """

    def _client(self, contents_by_url: dict[str, list[dict]]) -> BlackboardClient:
        base = "https://blackboard.example.test/learn/api/public/v1/courses/_333_1"
        responses = {
            f"{base}{path}": _json_response({"results": results})
            for path, results in contents_by_url.items()
        }
        transport = FakeTransport(responses)
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        return BlackboardClient(session, http_get=transport)

    def test_syn101_shape_this_week_only(self) -> None:
        # One folder ("This Week") wrapping a single document that itself
        # carries the attachment link — no separate lecture-recordings
        # folder observed for this module's shape.
        client = self._client(
            {
                "/contents": [
                    {
                        "id": "_wk1",
                        "title": "Week 1 w/c 01/09/2025 - Introduction to brands",
                        "contentHandler": {"id": "resource/x-bb-lesson"},
                        "hasChildren": True,
                    }
                ],
                "/contents/_wk1/children": [
                    {"id": "_thisweek", "title": "This Week", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                ],
                "/contents/_thisweek/children": [
                    {
                        "id": "_doc1",
                        "title": "ultraDocumentBody",
                        "contentHandler": {"id": "resource/x-bb-document"},
                        "body": '<a href="/download/_doc1/SBM_Lecture1.pdf">SBM_Lecture1.pdf</a>',
                    }
                ],
            }
        )
        weeks = discover_week_content(client, "_333_1")
        self.assertEqual(len(weeks), 1)
        week = weeks[0]
        self.assertEqual(week.week_number, 1)
        self.assertEqual(week.status, WEEK_DISCOVERED)
        self.assertEqual(len(week.attachments), 1)
        self.assertEqual(week.attachments[0].attachment.file_name, "SBM_Lecture1.pdf")
        self.assertEqual(
            [ref.content_id for ref in week.attachments[0].source_path],
            ["_wk1", "_thisweek", "_doc1"],
        )
        self.assertEqual(week.skipped, [])

    def test_syn102_shape_separate_lecture_folder_with_decoy_and_tool_links(self) -> None:
        # A sibling "Week N Lecture Recordings and Slides" folder holds the
        # real attachment; "This Week" here has no attachment of its own.
        # The lecture document also links a decorative banner image (no
        # matching extension -> dropped, not an error) alongside the real
        # .pptx. A BLTI tool-launch and an external link sit directly under
        # the week lesson and must be skipped, not misclassified.
        client = self._client(
            {
                "/contents": [
                    {
                        "id": "_wk1",
                        "title": "Week 1 (Sep 28- Oct 2)",
                        "contentHandler": {"id": "resource/x-bb-lesson"},
                        "hasChildren": True,
                    }
                ],
                "/contents/_wk1/children": [
                    {"id": "_thisweek", "title": "This Week", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                    {"id": "_examplefolder", "title": "Week 1 Lecture Recordings and Slides", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                    {"id": "_reflect", "title": "'Reflect' recordings", "contentHandler": {"id": "resource/x-bb-bltiplacement-PanoptoApplication-DZZj0X9BeUKq"}},
                    {"id": "_libsearch", "title": "Library Search", "contentHandler": {"id": "resource/x-bb-externallink"}},
                ],
                "/contents/_thisweek/children": [
                    {"id": "_overview", "title": "ultraDocumentBody", "contentHandler": {"id": "resource/x-bb-document"}, "body": "<p>Welcome to week 1.</p>"},
                ],
                "/contents/_examplefolder/children": [
                    {
                        "id": "_lecdoc",
                        "title": "Lecture X Recordings and Slides",
                        "contentHandler": {"id": "resource/x-bb-document"},
                        "body": (
                            '<a href="https://blackboard.example.test/bbcswebdav/banner.png?x=1">Watch Banner.png</a>'
                            '<a href="https://blackboard.example.test/bbcswebdav/slides?x=2">SYN102_L01 (26-27).pptx</a>'
                        ),
                    }
                ],
            }
        )
        weeks = discover_week_content(client, "_333_1")
        self.assertEqual(len(weeks), 1)
        week = weeks[0]
        self.assertEqual(week.status, WEEK_DISCOVERED)
        self.assertEqual(len(week.attachments), 1)
        self.assertEqual(week.attachments[0].attachment.file_name, "SYN102_L01 (26-27).pptx")
        self.assertEqual(
            [ref.content_id for ref in week.attachments[0].source_path],
            ["_wk1", "_examplefolder", "_lecdoc"],
        )
        skip_reasons = {(s.reason, s.source_path[-1].content_id) for s in week.skipped}
        self.assertIn((SKIPPED_TOOL_LINK, "_reflect"), skip_reasons)
        self.assertIn((SKIPPED_EXTERNAL, "_libsearch"), skip_reasons)

    def test_empty_future_week_shell_is_not_yet_published(self) -> None:
        # hasChildren=True but the child listing itself comes back empty —
        # a future week whose shell exists but has no
        # content yet.
        client = self._client(
            {
                "/contents": [
                    {
                        "id": "_wk2",
                        "title": "Week 2 (Oct 5-9)",
                        "contentHandler": {"id": "resource/x-bb-lesson"},
                        "hasChildren": True,
                    }
                ],
                "/contents/_wk2/children": [],
            }
        )
        weeks = discover_week_content(client, "_333_1")
        self.assertEqual(len(weeks), 1)
        self.assertEqual(weeks[0].status, WEEK_NOT_YET_PUBLISHED)
        self.assertEqual(weeks[0].attachments, [])
        self.assertEqual(weeks[0].skipped, [])

    def test_hasChildren_false_is_also_not_yet_published(self) -> None:
        client = self._client(
            {
                "/contents": [
                    {
                        "id": "_wk3",
                        "title": "Week 3",
                        "contentHandler": {"id": "resource/x-bb-lesson"},
                        "hasChildren": False,
                    }
                ],
            }
        )
        weeks = discover_week_content(client, "_333_1")
        self.assertEqual(weeks[0].status, WEEK_NOT_YET_PUBLISHED)

    def test_non_lesson_and_non_week_titled_nodes_are_not_treated_as_weeks(self) -> None:
        client = self._client(
            {
                "/contents": [
                    {"id": "_about", "title": "About this module", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                    {"id": "_reading", "title": "Reading and resources", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
            }
        )
        self.assertEqual(discover_week_content(client, "_333_1"), [])

    def test_unrecognised_content_handler_is_ambiguous_not_guessed(self) -> None:
        client = self._client(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_mystery", "title": "Some New Thing", "contentHandler": {"id": "resource/x-bb-asmt-test-link"}},
                ],
            }
        )
        week = discover_week_content(client, "_333_1")[0]
        self.assertEqual(week.attachments, [])
        self.assertEqual(len(week.skipped), 1)
        self.assertEqual(week.skipped[0].reason, AMBIGUOUS_WEEK_STRUCTURE)

    def test_folder_depth_exhausted_is_ambiguous_not_guessed(self) -> None:
        client = self._client(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_f1", "title": "Folder 1", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                ],
                "/contents/_f1/children": [
                    {"id": "_f2", "title": "Folder 2", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                ],
                "/contents/_f2/children": [
                    {"id": "_f3", "title": "Folder 3 (too deep)", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                ],
            }
        )
        week = discover_week_content(client, "_333_1", max_folder_depth=2)[0]
        self.assertEqual(week.attachments, [])
        self.assertEqual(len(week.skipped), 1)
        self.assertEqual(week.skipped[0].reason, AMBIGUOUS_WEEK_STRUCTURE)
        self.assertEqual(week.skipped[0].source_path[-1].content_id, "_f3")

    def test_empty_folder_under_published_week_is_ambiguous_not_not_yet_published(self) -> None:
        # Distinguish from the week-level empty-children case: the week
        # itself is live (non-empty children), one branch just resolves to
        # nothing known.
        client = self._client(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_empty", "title": "Empty Folder", "contentHandler": {"id": "resource/x-bb-folder"}, "hasChildren": True},
                ],
                "/contents/_empty/children": [],
            }
        )
        week = discover_week_content(client, "_333_1")[0]
        self.assertEqual(week.status, WEEK_DISCOVERED)
        self.assertEqual(len(week.skipped), 1)
        self.assertEqual(week.skipped[0].reason, AMBIGUOUS_WEEK_STRUCTURE)

    def test_duplicate_week_number_is_ambiguous_neither_auto_selected(self) -> None:
        # Two distinct root lessons both matching "Week 1" -- never observed
        # live, but the discovery layer must not silently pick or merge one.
        client = self._client(
            {
                "/contents": [
                    {"id": "_wk1a", "title": "Week 1 (original)", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                    {"id": "_wk1b", "title": "Week 1 (duplicate)", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1a/children": [
                    {"id": "_doc1", "title": "doc", "contentHandler": {"id": "resource/x-bb-document"}, "body": '<a href="/download/a.pdf">a.pdf</a>'},
                ],
                "/contents/_wk1b/children": [
                    {"id": "_doc2", "title": "doc", "contentHandler": {"id": "resource/x-bb-document"}, "body": '<a href="/download/b.pdf">b.pdf</a>'},
                ],
            }
        )
        weeks = discover_week_content(client, "_333_1")
        self.assertEqual(len(weeks), 1)
        week = weeks[0]
        self.assertEqual(week.week_number, 1)
        self.assertEqual(week.status, WEEK_AMBIGUOUS_DUPLICATE)
        self.assertEqual(week.attachments, [])
        self.assertEqual(week.skipped, [])

    def test_non_duplicate_multiple_weeks_are_all_discovered(self) -> None:
        client = self._client(
            {
                "/contents": [
                    {"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                    {"id": "_wk2", "title": "Week 2", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "/contents/_wk1/children": [
                    {"id": "_doc1", "title": "doc", "contentHandler": {"id": "resource/x-bb-document"}, "body": '<a href="/download/a.pdf">a.pdf</a>'},
                ],
                "/contents/_wk2/children": [],
            }
        )
        weeks = discover_week_content(client, "_333_1")
        self.assertEqual([w.week_number for w in weeks], [1, 2])
        self.assertEqual(weeks[0].status, WEEK_DISCOVERED)
        self.assertEqual(weeks[1].status, WEEK_NOT_YET_PUBLISHED)


class DiscoverTeachingScopeTests(unittest.TestCase):
    """Synthetic fixtures shaped like the real 24-membership account probed
    live (2025-01-02): a mix of 403-inaccessible historical courses,
    accessible support/mandatory-training shells with zero week-lessons,
    and genuine teaching modules with week-lesson content. No real ids.
    """

    def _client(self, transport: "_ScopeTransport") -> BlackboardClient:
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="test=1")
        return BlackboardClient(session, http_get=transport)

    def test_only_courses_with_week_lessons_enter_scope(self) -> None:
        transport = _ScopeTransport(
            memberships=[{"courseId": "_teach_1"}, {"courseId": "_support_1"}],
            courses={
                "_teach_1": {"id": "_teach_1", "courseId": "SYN101_2025-26_SEM1", "name": "Introduction to Example Studies"},
                "_support_1": {"id": "_support_1", "courseId": "ESU010", "name": "Succeed at Example University"},
            },
            contents={
                "_teach_1": [{"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}],
                "_support_1": [{"id": "_welcome", "title": "Getting Started", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}],
            },
            week_children={"_wk1": []},
        )
        scope = discover_teaching_scope(self._client(transport))
        self.assertEqual([m.module_code for m in scope.modules], ["SYN101"])
        self.assertEqual(scope.issues, [])

    def test_403_membership_is_skipped_silently(self) -> None:
        transport = _ScopeTransport(
            memberships=[{"courseId": "_teach_1"}, {"courseId": "_inaccessible_1"}],
            courses={"_teach_1": {"id": "_teach_1", "courseId": "SYN102", "name": "Example topic module"}},
            contents={"_teach_1": [{"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}]},
            week_children={"_wk1": []},
            course_status={"_inaccessible_1": 403},
        )
        scope = discover_teaching_scope(self._client(transport))
        self.assertEqual([m.module_code for m in scope.modules], ["SYN102"])
        self.assertEqual(scope.issues, [])

    def test_unexpected_course_resolution_failure_is_surfaced(self) -> None:
        transport = _ScopeTransport(
            memberships=[{"courseId": "_teach_1"}, {"courseId": "_broken_1"}],
            courses={"_teach_1": {"id": "_teach_1", "courseId": "SYN102", "name": "Example topic module"}},
            contents={"_teach_1": [{"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}]},
            week_children={"_wk1": []},
            course_status={"_broken_1": 500},
        )
        scope = discover_teaching_scope(self._client(transport))
        self.assertEqual([m.module_code for m in scope.modules], ["SYN102"])
        self.assertEqual(len(scope.issues), 1)
        self.assertEqual(scope.issues[0].reason, REASON_COURSE_RESOLVE_FAILED)
        self.assertEqual(scope.issues[0].course_system_id, "_broken_1")

    def test_multiple_teaching_modules_discovered_automatically(self) -> None:
        transport = _ScopeTransport(
            memberships=[{"courseId": "_teach_1"}, {"courseId": "_teach_2"}, {"courseId": "_support_1"}],
            courses={
                "_teach_1": {"id": "_teach_1", "courseId": "SYN101_2025-26_SEM1", "name": "Introduction to Example Studies"},
                "_teach_2": {"id": "_teach_2", "courseId": "SYN102_2025-26_SEM1", "name": "Example topic module"},
                "_support_1": {"id": "_support_1", "courseId": "ADX178", "name": "Academic integrity"},
            },
            contents={
                "_teach_1": [{"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}],
                "_teach_2": [
                    {"id": "_wk1b", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                    {"id": "_wk2b", "title": "Week 2", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True},
                ],
                "_support_1": [{"id": "_quiz", "title": "Final quiz", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}],
            },
            week_children={"_wk1": [], "_wk1b": [], "_wk2b": []},
        )
        scope = discover_teaching_scope(self._client(transport))
        codes = sorted(m.module_code for m in scope.modules)
        self.assertEqual(codes, ["SYN101", "SYN102"])
        syn102 = next(m for m in scope.modules if m.module_code == "SYN102")
        self.assertEqual([w.week_number for w in syn102.weeks], [1, 2])
        self.assertEqual(scope.issues, [])

    def test_missing_course_code_is_surfaced_not_invented(self) -> None:
        transport = _ScopeTransport(
            memberships=[{"courseId": "_teach_1"}],
            courses={"_teach_1": {"id": "_teach_1", "name": "No Code Course"}},
            contents={"_teach_1": [{"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}]},
            week_children={"_wk1": []},
        )
        scope = discover_teaching_scope(self._client(transport))
        self.assertEqual(scope.modules, [])
        self.assertEqual(len(scope.issues), 1)
        self.assertEqual(scope.issues[0].reason, REASON_MISSING_MODULE_CODE)

    def test_colliding_derived_module_codes_are_surfaced_not_auto_merged(self) -> None:
        transport = _ScopeTransport(
            memberships=[{"courseId": "_teach_1"}, {"courseId": "_teach_2"}],
            courses={
                "_teach_1": {"id": "_teach_1", "courseId": "SYN101_2025-26_SEM1", "name": "A"},
                "_teach_2": {"id": "_teach_2", "courseId": "SYN101_RESIT", "name": "B"},
            },
            contents={
                "_teach_1": [{"id": "_wk1", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}],
                "_teach_2": [{"id": "_wk1c", "title": "Week 1", "contentHandler": {"id": "resource/x-bb-lesson"}, "hasChildren": True}],
            },
            week_children={"_wk1": [], "_wk1c": []},
        )
        scope = discover_teaching_scope(self._client(transport))
        self.assertEqual(scope.modules, [])
        reasons = {(i.reason, i.course_system_id) for i in scope.issues}
        self.assertIn((REASON_DUPLICATE_MODULE_CODE, "_teach_1"), reasons)
        self.assertIn((REASON_DUPLICATE_MODULE_CODE, "_teach_2"), reasons)


class _ScopeTransport:
    """Fake transport for university-wide scope discovery: memberships,
    per-course detail (with optional non-200 status), root contents, and
    week-lesson children."""

    def __init__(
        self,
        *,
        memberships: list[dict],
        courses: dict[str, dict],
        contents: dict[str, list[dict]],
        week_children: dict[str, list[dict]],
        course_status: dict[str, int] | None = None,
    ) -> None:
        self._memberships = memberships
        self._courses = courses
        self._contents = contents
        self._week_children = week_children
        self._course_status = course_status or {}
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        base = "https://blackboard.example.test/learn/api/public/v1"
        if url == f"{base}/users/me/courses":
            return _json_response({"results": self._memberships})
        for system_id, status in self._course_status.items():
            if url == f"{base}/courses/{system_id}":
                return HttpResponse(status=status, body=b"error")
        for system_id, course in self._courses.items():
            if url == f"{base}/courses/{system_id}":
                return _json_response(course)
            if url == f"{base}/courses/{system_id}/contents":
                return _json_response({"results": self._contents.get(system_id, [])})
        for system_id in self._courses:
            for node in self._contents.get(system_id, []):
                lesson_id = node.get("id")
                if lesson_id and url == f"{base}/courses/{system_id}/contents/{lesson_id}/children":
                    return _json_response({"results": self._week_children.get(lesson_id, [])})
        raise AssertionError(f"Unexpected URL requested: {url}")


class SessionReprTests(unittest.TestCase):
    def test_repr_never_includes_cookie(self) -> None:
        session = BlackboardSession(base_url="https://blackboard.example.test", cookie_header="secret=do-not-leak")
        self.assertNotIn("secret", repr(session))
        self.assertNotIn("do-not-leak", repr(session))


if __name__ == "__main__":
    unittest.main()
