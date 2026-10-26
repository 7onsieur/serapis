"""Phase 1 safety/reliability regressions: Hub request guards, uploads,
concurrent record writes and export regeneration. Synthetic, offline."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient

from university_jarvis import hub_security, hub_web
from university_jarvis.hub_web import create_app
from university_jarvis.locking import record_lock
from university_jarvis.state import StateError, load_state
from university_jarvis.student_setup import add_module, initialize_personal_state
from university_jarvis.workspace import (
    capture_after_lecture,
    materialize_week_workspace,
    record_learning_attempt,
    save_learning_evaluation,
    teach_week,
)

from tests.test_teach import (  # noqa: E402
    PrepareProvider,
    TeachProvider,
    week_context,
)
from university_jarvis.reasoning import generate_prepare_brief  # noqa: E402


def _pptx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
        package.writestr("ppt/presentation.xml", "<p/>")
    return buffer.getvalue()


PDF_BYTES = b"%PDF-1.4\n% synthetic\n"


class HubHome(unittest.TestCase):
    """A throwaway SERAPIS_HOME so no real student data is touched."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        patcher = patch.dict(os.environ, {"SERAPIS_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        initialize_personal_state()
        add_module("BIO101", "Biology")

    def client(self, **kwargs) -> TestClient:
        def no_ai(*_a, **_k):
            raise AssertionError("AI must not be invoked")

        return TestClient(create_app(reasoning_provider=no_ai, **kwargs))


class HostValidationTests(HubHome):
    def test_loopback_hosts_are_accepted(self) -> None:
        client = self.client()
        for host in ("localhost", "localhost:8765", "127.0.0.1:8765", "[::1]:8765"):
            with self.subTest(host=host):
                self.assertEqual(client.get("/", headers={"host": host}).status_code, 200)

    def test_foreign_host_is_rejected_for_reads_too(self) -> None:
        client = self.client()
        for host in ("evil.example", "evil.example:8765", "127.0.0.1.evil.example", "localhost.evil.example"):
            with self.subTest(host=host):
                response = client.get("/", headers={"host": host})
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("Biology", response.text)

    def test_explicitly_allowed_host_is_accepted(self) -> None:
        client = self.client(allowed_hosts=("study-laptop.local",))
        self.assertEqual(client.get("/", headers={"host": "study-laptop.local:8765"}).status_code, 200)
        self.assertEqual(client.get("/", headers={"host": "other.local"}).status_code, 403)


def _asgi(headers: list[tuple[bytes, bytes]], method: str = "POST", path: str = "/modules"):
    """Run one request through the guard alone; returns (status or None if passed through)."""
    sent: list[dict] = []
    passed: list[bool] = []

    async def app(scope, receive, send):
        passed.append(True)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    asyncio.run(hub_security.HubSecurityMiddleware(app, allowed_hosts=("192.168.1.5", "fe80::1", "Study.Local"))(scope, None, send))
    return None if passed else sent[0]["status"]


class GuardBypassMatrixTests(unittest.TestCase):
    def test_malformed_or_tricky_host_headers_are_rejected(self) -> None:
        for host in (b"", b"localhost@evil.example", b"evil.example#@localhost", b"evil.example\\@localhost",
                     b"localhost.", b"127.1", b"127.0.0.2", b"0.0.0.0", b"[::ffff:127.0.0.1]",
                     b"foo.localhost", b"localhost:80@evil.example", b" evil.example", b"evil.example,localhost"):
            with self.subTest(host=host):
                self.assertEqual(_asgi([(b"host", host)], method="GET"), 403)

    def test_missing_host_header_is_rejected(self) -> None:
        self.assertEqual(_asgi([], method="GET"), 403)

    def test_localhost_spellings_and_custom_bindings_pass(self) -> None:
        for host in (b"LOCALHOST", b"localhost:1", b"127.0.0.1", b"[::1]:8765", b"192.168.1.5:8765",
                     b"[fe80::1]:8765", b"study.local"):
            with self.subTest(host=host):
                self.assertIsNone(_asgi([(b"host", host)], method="GET"))

    def test_duplicate_security_headers_are_rejected(self) -> None:
        self.assertEqual(_asgi([(b"host", b"localhost"), (b"host", b"evil.example")], method="GET"), 400)
        self.assertEqual(_asgi([(b"host", b"localhost"), (b"origin", b"http://localhost"),
                                (b"origin", b"http://evil.example")]), 400)

    def test_origin_malformed_or_scheme_tricks_are_rejected(self) -> None:
        for origin in (b"", b"evil.example", b"//localhost", b"javascript://localhost", b"file://localhost",
                       b"http://localhost.evil.example", b"http://localhost@evil.example",
                       b"http://localhost:8765/../", b"http://[::1"):
            with self.subTest(origin=origin):
                self.assertEqual(_asgi([(b"host", b"localhost:8765"), (b"origin", origin)]), 403)

    def test_chunked_upload_cannot_bypass_the_size_cap(self) -> None:
        self.assertEqual(_asgi([(b"host", b"localhost"), (b"transfer-encoding", b"chunked"),
                                (b"content-length", b"10")], path="/modules/BIO101/materials"), 411)

    def test_custom_binding_still_enforces_origin(self) -> None:
        self.assertEqual(_asgi([(b"host", b"192.168.1.5:8765"), (b"origin", b"http://evil.example")]), 403)
        self.assertIsNone(_asgi([(b"host", b"192.168.1.5:8765"), (b"origin", b"http://192.168.1.5:8765")]))

    def test_get_routes_never_write_state_or_call_ai(self) -> None:
        """Safe methods skip the Origin check, so no GET route may change anything."""
        import re
        source = Path(hub_web.__file__).read_text()
        for match in re.finditer(r'@app\.get\("([^"]+)"', source):
            self.assertNotIn("student_setup", source[match.end(): match.end() + 400].split("@app.")[0],
                             f"GET {match.group(1)} reaches a state mutator")


class CrossSiteRequestTests(HubHome):
    def _module_count(self) -> int:
        return len(load_state()["modules"])

    def test_cross_origin_post_is_rejected_and_changes_nothing(self) -> None:
        client = self.client()
        before = self._module_count()
        for headers in (
            {"origin": "http://evil.example"},
            {"origin": "null"},
            {"origin": "http://localhost:9999", "host": "localhost:8765"},
            {"origin": "http://127.0.0.1:8765", "host": "localhost:8765"},
            {"referer": "http://evil.example/page"},
            {"sec-fetch-site": "cross-site"},
            {"sec-fetch-site": "same-site"},
        ):
            with self.subTest(headers=headers):
                response = client.post("/modules", data={"code": "EVIL1", "title": "x"},
                                       headers=headers, follow_redirects=False)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self._module_count(), before)

    def test_destructive_and_ai_routes_are_also_guarded(self) -> None:
        client = self.client()
        evil = {"origin": "http://evil.example"}
        for path in ("/modules/BIO101/remove", "/modules/BIO101/weeks/1/quiz",
                     "/modules/BIO101/weeks/1/teach", "/check", "/modules/BIO101/assignment"):
            with self.subTest(path=path):
                self.assertEqual(client.post(path, headers=evil).status_code, 403)
        self.assertEqual(self._module_count(), 1)

    def test_same_origin_post_is_accepted(self) -> None:
        client = self.client()
        for index, headers in enumerate((
            {"origin": "http://localhost", "host": "localhost"},
            {"origin": "http://127.0.0.1:8765", "host": "127.0.0.1:8765"},
            {"referer": "http://localhost/modules", "host": "localhost"},
            {"sec-fetch-site": "same-origin"},
            {},  # non-browser client: no Origin/Referer/Sec-Fetch-Site
        )):
            with self.subTest(headers=headers):
                response = client.post("/modules", data={"code": f"OK{index}", "title": "t"},
                                       headers=headers, follow_redirects=False)
                self.assertEqual(response.status_code, 303)

    def test_safe_methods_are_not_subject_to_origin_checks(self) -> None:
        client = self.client()
        self.assertEqual(client.get("/modules", headers={"origin": "http://evil.example"}).status_code, 200)


class UploadTests(HubHome):
    def _upload(self, client, name: str, data: bytes, **kwargs):
        return client.post("/modules/BIO101/materials", data={"week": "1"},
                           files={"file": (name, data)}, follow_redirects=False, **kwargs)

    def _stored(self) -> list[Path]:
        return [p for p in (self.home / "materials").rglob("*") if p.is_file()]

    def test_valid_pdf_and_pptx_are_accepted_with_original_names(self) -> None:
        client = self.client()
        self.assertEqual(self._upload(client, "Lecture 1.pdf", PDF_BYTES).status_code, 303)
        self.assertEqual(self._upload(client, "deck.pptx", _pptx_bytes()).status_code, 303)
        self.assertEqual({p.name for p in self._stored()}, {"Lecture 1.pdf", "deck.pptx"})
        titles = {s["title"] for s in load_state()["sources"]}
        self.assertEqual(titles, {"Lecture 1.pdf", "deck.pptx"})

    def test_content_must_match_extension(self) -> None:
        client = self.client()
        cases = {
            "notes.pdf": b"this is plain text, not a PDF",
            "deck.pptx": b"PK\x03\x04 not really a package",
            "zip.pptx": (lambda b=io.BytesIO(): (zipfile.ZipFile(b, "w").writestr("a.txt", "x"), b.getvalue())[1])(),
            "empty.pdf": b"",
            "tool.exe": b"MZ\x90\x00",
            "page.html.pdf.exe": PDF_BYTES,
            "noext": PDF_BYTES,
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                response = self._upload(client, name, data)
                self.assertEqual(response.status_code, 400)  # rendered as the module page with an error banner
        self.assertEqual(self._stored(), [])
        self.assertEqual(load_state()["sources"], [])

    def test_hostile_filename_cannot_escape_storage(self) -> None:
        client = self.client()
        self.assertEqual(self._upload(client, "../../../evil\\..\\x.pdf", PDF_BYTES).status_code, 303)
        stored = self._stored()
        self.assertEqual(len(stored), 1)
        stored[0].resolve().relative_to((self.home / "materials" / "BIO101").resolve())
        self.assertFalse((self.home.parent / "evil.pdf").exists())

    def test_streamed_size_limit_is_enforced_and_nothing_is_kept(self) -> None:
        client = self.client()
        with patch.object(hub_web, "MAX_UPLOAD_BYTES", 1024):
            response = self._upload(client, "big.pdf", PDF_BYTES + b"x" * 4096)
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.text)
        self.assertEqual(self._stored(), [])

    def test_declared_content_length_over_limit_is_rejected_before_reading(self) -> None:
        sent: list[dict] = []
        reached = []

        async def downstream(scope, receive, send):
            reached.append(True)

        middleware = hub_security.HubSecurityMiddleware(downstream)
        scope = {"type": "http", "method": "POST", "path": "/modules/BIO101/materials",
                 "headers": [(b"host", b"localhost"),
                             (b"content-length", str(hub_security.MAX_REQUEST_BYTES + 1).encode())]}

        async def send(message):
            sent.append(message)

        async def receive():
            raise AssertionError("body must not be read")

        asyncio.run(middleware(scope, receive, send))
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(reached, [])

    def test_upload_without_declared_length_is_rejected(self) -> None:
        sent: list[dict] = []

        async def downstream(scope, receive, send):
            raise AssertionError("must not reach the app")

        scope = {"type": "http", "method": "POST", "path": "/materials/x/replace",
                 "headers": [(b"host", b"localhost")]}

        async def send(message):
            sent.append(message)

        asyncio.run(hub_security.HubSecurityMiddleware(downstream)(scope, None, send))
        self.assertEqual(sent[0]["status"], 411)

    def test_scratch_directories_are_private_and_removed(self) -> None:
        scratch_root = Path(self.temp.name) / "tmp"
        scratch_root.mkdir()
        modes: list[int] = []
        real_mkdtemp = tempfile.mkdtemp

        def spying_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            modes.append(os.stat(path).st_mode & 0o777)
            return path

        client = self.client()
        with patch.object(tempfile, "tempdir", str(scratch_root)), \
                patch.object(tempfile, "mkdtemp", spying_mkdtemp):
            self._upload(client, "ok.pdf", PDF_BYTES)
            self._upload(client, "bad.pdf", b"nope")
        self.assertEqual(modes, [0o700, 0o700])
        self.assertEqual(list(scratch_root.iterdir()), [])

    def test_duplicate_and_collision_storage_still_safe(self) -> None:
        client = self.client()
        self._upload(client, "same.pdf", PDF_BYTES)
        self._upload(client, "same.pdf", PDF_BYTES)  # identical -> deduplicated
        self.assertEqual(len(self._stored()), 1)
        self._upload(client, "same.pdf", PDF_BYTES + b"different")  # collision -> new name
        self.assertEqual(len(self._stored()), 2)

    def test_failed_state_write_still_rolls_back_the_copied_file(self) -> None:
        client = self.client()
        with patch("university_jarvis.student_setup._save", side_effect=OSError("disk full")):
            response = self._upload(client, "deck.pdf", PDF_BYTES)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self._stored(), [])

    def test_replace_route_validates_content(self) -> None:
        client = self.client()
        self._upload(client, "a.pdf", PDF_BYTES)
        source_id = load_state()["sources"][0]["id"]
        bad = client.post(f"/materials/{source_id}/replace", files={"file": ("b.pdf", b"junk")},
                          follow_redirects=False)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual({p.name for p in self._stored()}, {"a.pdf"})
        good = client.post(f"/materials/{source_id}/replace", files={"file": ("b.pdf", PDF_BYTES + b"2")},
                           follow_redirects=False)
        self.assertEqual(good.status_code, 303)


class RecordFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.record_path = self.root / "BIO101" / "week-01" / "academic-record.json"
        self.record_path.parent.mkdir(parents=True)
        self.record_path.write_text(json.dumps({
            "workspace_schema_version": 3,
            "module": {"code": "BIO101", "title": "Biology"}, "week": {"number": 1, "topic": "Cells"},
            "sources": [], "workflows": {}, "learning": {"evidence": []},
        }))

    def evidence(self) -> list[dict]:
        return json.loads(self.record_path.read_text())["learning"]["evidence"]


class ConcurrentWriteTests(RecordFixture):
    def test_parallel_attempts_are_all_kept_with_unique_ids(self) -> None:
        errors: list[BaseException] = []

        def worker(n: int) -> None:
            try:
                for i in range(6):
                    record_learning_attempt("BIO101", 1, capability="RECALL", task="t", origin=f"o{n}-{i}",
                                            response=f"r{n}-{i}", root=self.root)
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        rows = self.evidence()
        self.assertEqual(len(rows), 48)
        self.assertEqual(len({r["attempt_id"] for r in rows}), 48)
        self.assertEqual({r["student_response"] for r in rows}, {f"r{n}-{i}" for n in range(8) for i in range(6)})

    def test_writer_waits_for_the_lock_and_then_preserves_both_changes(self) -> None:
        started = threading.Event()
        done = threading.Event()

        def late_writer() -> None:
            started.set()
            record_learning_attempt("BIO101", 1, capability="RECALL", task="t", origin="late",
                                    response="late", root=self.root)
            done.set()

        with record_lock(self.record_path):
            thread = threading.Thread(target=late_writer)
            thread.start()
            started.wait(5)
            self.assertFalse(done.wait(0.4), "writer must block while the lock is held")
            record = json.loads(self.record_path.read_text())
            record["learning"]["evidence"].append({"attempt_id": "attempt-000001", "capability": "RECALL",
                                                   "student_response": "held", "evaluation": None})
            self.record_path.write_text(json.dumps(record))
        thread.join(5)
        self.assertTrue(done.is_set())
        responses = [r["student_response"] for r in self.evidence()]
        self.assertEqual(responses, ["held", "late"])  # nothing overwritten
        self.assertEqual([r["attempt_id"] for r in self.evidence()], ["attempt-000001", "attempt-000002"])

    def test_evaluation_does_not_clobber_a_concurrent_attempt(self) -> None:
        first = record_learning_attempt("BIO101", 1, capability="RECALL", task="t", origin="a",
                                        response="a", root=self.root)
        results: list[str] = []

        def attempt() -> None:
            results.append(record_learning_attempt("BIO101", 1, capability="RECALL", task="t", origin="b",
                                                   response="b", root=self.root)["attempt_id"])

        threads = [threading.Thread(target=attempt) for _ in range(4)]
        for t in threads:
            t.start()
        save_learning_evaluation("BIO101", 1, first["attempt_id"], {"outcome": "SUPPORTED"}, root=self.root)
        for t in threads:
            t.join()
        rows = self.evidence()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["evaluation"], {"outcome": "SUPPORTED"})

    def test_lock_timeout_is_a_clear_error_not_a_hang(self) -> None:
        outcome: list[BaseException | None] = []

        def contender() -> None:
            try:
                with record_lock(self.record_path, timeout=0.2):
                    outcome.append(None)
            except StateError as exc:
                outcome.append(exc)

        with record_lock(self.record_path):
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(5)
        self.assertEqual(len(outcome), 1)
        self.assertIn("Another Serapis operation", str(outcome[0]))

    def test_lock_is_reentrant_within_one_thread(self) -> None:
        with record_lock(self.record_path, timeout=0.2):
            with record_lock(self.record_path, timeout=0.2):
                pass
        with record_lock(self.record_path, timeout=0.2):  # fully released afterwards
            pass

    def test_lock_is_released_after_an_error(self) -> None:
        with self.assertRaises(RuntimeError):
            with record_lock(self.record_path):
                raise RuntimeError("boom")
        with record_lock(self.record_path, timeout=0.2):
            pass

    def test_missing_record_still_fails_without_creating_directories(self) -> None:
        with self.assertRaisesRegex(StateError, "Academic record not found"):
            record_learning_attempt("NOPE1", 3, capability="RECALL", task="t", origin="o",
                                    response="r", root=self.root)
        self.assertFalse((self.root / "NOPE1").exists())

    def test_record_write_is_atomic_and_leaves_no_temp_files(self) -> None:
        record_learning_attempt("BIO101", 1, capability="RECALL", task="t", origin="o",
                                response="r", root=self.root)
        names = {p.name for p in self.record_path.parent.iterdir()}
        self.assertEqual(names, {"academic-record.json", "academic-record.json.lock"})


class TeachKeepsConcurrentWritesTests(unittest.TestCase):
    def test_attempt_recorded_during_the_model_call_survives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir, workspace_root = root / "cache", root / "workspace"
            context = week_context("PREPARE_ME")
            generate_prepare_brief(context, PrepareProvider(), cache_dir)
            with patch("university_jarvis.workspace.build_prepare_context", return_value=context):
                materialize_week_workspace({}, "SYN101", 1, provider=PrepareProvider(),
                                           cache_dir=cache_dir, workspace_root=workspace_root)
            capture_after_lecture("SYN101", 1, questions=["What is question framing?"],
                                  workspace_root=workspace_root)

            class RacingProvider(TeachProvider):
                def generate_structured_output(self, *args):
                    # Another Hub tab saves an attempt while the model is "thinking".
                    record_learning_attempt("SYN101", 1, capability="RECALL", task="t", origin="race",
                                            response="saved during model call", root=workspace_root)
                    return super().generate_structured_output(*args)

            with patch("university_jarvis.workspace.build_week_context", return_value=week_context("TEACH")):
                teach_week({}, "SYN101", 1, topic="question framing", provider=RacingProvider(),
                           cache_dir=cache_dir, workspace_root=workspace_root)
            record = json.loads((workspace_root / "SYN101" / "week-01" / "academic-record.json").read_text())
            self.assertEqual([a["student_response"] for a in record["learning"]["evidence"]],
                             ["saved during model call"])
            self.assertEqual(len(record["workflows"]["teach"]["interactions"]), 1)


class ExportRegenerationTests(unittest.TestCase):
    def test_learning_writes_do_not_rebuild_exports_but_explicit_paths_do(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir, workspace_root = root / "cache", root / "workspace"
            context = week_context("PREPARE_ME")
            generate_prepare_brief(context, PrepareProvider(), cache_dir)
            with patch("university_jarvis.workspace.build_prepare_context", return_value=context):
                built = materialize_week_workspace({}, "SYN101", 1, provider=PrepareProvider(),
                                                   cache_dir=cache_dir, workspace_root=workspace_root)
            docx, md = built.study_pack_path, built.notebooklm_path
            self.assertTrue(docx.is_file() and md.is_file())
            docx_before, md_before = docx.read_bytes(), md.read_bytes()

            with patch("university_jarvis.workspace._docx_bytes", side_effect=AssertionError("docx rebuilt")), \
                    patch("university_jarvis.workspace._notebooklm_markdown", side_effect=AssertionError("md rebuilt")):
                attempt = record_learning_attempt("SYN101", 1, capability="RECALL", task="t", origin="o",
                                                  response="r", root=workspace_root)
                save_learning_evaluation("SYN101", 1, attempt["attempt_id"], {"outcome": "SUPPORTED"},
                                         root=workspace_root)
            self.assertEqual((docx.read_bytes(), md.read_bytes()), (docx_before, md_before))

            # On-disk exports are snapshots refreshed by reflection, TEACH and prepare writes; Hub downloads are built fresh:
            rebuilt = capture_after_lecture("SYN101", 1, questions=["Why?"], workspace_root=workspace_root)
            self.assertTrue(rebuilt.study_pack_path.is_file())
            record = json.loads(rebuilt.record_path.read_text())
            self.assertEqual(len(record["learning"]["evidence"]), 1)  # evidence kept by explicit rebuild
            self.assertIn("Why?", rebuilt.notebooklm_path.read_text())

    def test_export_shows_evidence_standing_but_never_the_answer_text(self) -> None:
        from university_jarvis.workspace import _notebooklm_markdown
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_dir, workspace_root = root / "cache", root / "workspace"
            context = week_context("PREPARE_ME")
            generate_prepare_brief(context, PrepareProvider(), cache_dir)
            with patch("university_jarvis.workspace.build_prepare_context", return_value=context):
                built = materialize_week_workspace({}, "SYN101", 1, provider=PrepareProvider(),
                                                   cache_dir=cache_dir, workspace_root=workspace_root)
            before = json.loads(built.record_path.read_text())
            record_learning_attempt("SYN101", 1, capability="RECALL", task="Define framing?", origin="o",
                                    response="my private answer text", root=workspace_root)
            after = json.loads(built.record_path.read_text())
            self.assertNotEqual(before, after)
            self.assertNotEqual(_notebooklm_markdown(before), _notebooklm_markdown(after))
            self.assertIn("Define framing?", _notebooklm_markdown(after))
            self.assertNotIn("my private answer text", _notebooklm_markdown(after))
            # Deterministic: the same record always renders the same text.
            self.assertEqual(_notebooklm_markdown(after), _notebooklm_markdown(json.loads(json.dumps(after))))


if __name__ == "__main__":
    unittest.main()


class AcademicStateConcurrencyTests(HubHome):
    """Module/assessment/material edits are one locked load-modify-save."""

    def test_parallel_module_adds_all_survive(self) -> None:
        from university_jarvis.student_setup import add_module as add

        errors: list[BaseException] = []

        def worker(n: int) -> None:
            try:
                add(f"MOD{n}", f"Module {n}")
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        codes = {m["code"] for m in load_state()["modules"]}
        self.assertEqual(codes, {"BIO101"} | {f"MOD{n}" for n in range(12)})

    def test_edit_waits_for_a_held_transaction_and_sees_its_result(self) -> None:
        from university_jarvis.student_setup import add_module as add, personal_state_path

        done = threading.Event()
        thread = threading.Thread(target=lambda: (add("LATE1", "Late"), done.set()))
        with record_lock(personal_state_path(), create_dir=True):
            thread.start()
            self.assertFalse(done.wait(0.4), "mutator must wait while another transaction holds the lock")
            # Simulate another process finishing its own edit meanwhile.
            state = load_state()
            state["student"]["university"] = "Edited elsewhere"
            from university_jarvis.state import save_state
            save_state(state, personal_state_path())
        thread.join(5)
        final = load_state()
        self.assertEqual(final["student"]["university"], "Edited elsewhere")
        self.assertIn("LATE1", {m["code"] for m in final["modules"]})

    def test_parallel_assessments_and_material_imports_all_survive(self) -> None:
        from university_jarvis.student_setup import import_material, save_assessment

        scratch = Path(self.temp.name) / "src"
        scratch.mkdir()
        files = []
        for n in range(6):
            f = scratch / f"m{n}.pdf"
            f.write_bytes(PDF_BYTES + bytes([n]))
            files.append(f)
        errors: list[BaseException] = []

        def assess(n: int) -> None:
            try:
                save_assessment("BIO101", title=f"Essay {n}")
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        def material(n: int) -> None:
            try:
                import_material("BIO101", files[n], week=1)
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=assess, args=(n,)) for n in range(6)]
        threads += [threading.Thread(target=material, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        state = load_state()
        module = state["modules"][0]
        self.assertEqual(len(module["assessments"]), 6)
        self.assertEqual(len(state["sources"]), 6)
        self.assertEqual(len(module["weeks"][0]["source_ids"]), 6)
        stored = {p.name for p in (self.home / "materials" / "BIO101").iterdir()}
        self.assertEqual(stored, {f"m{n}.pdf" for n in range(6)})

    def test_failed_transaction_releases_lock_and_rolls_back(self) -> None:
        from university_jarvis.student_setup import import_material, personal_state_path

        src = Path(self.temp.name) / "x.pdf"
        src.write_bytes(PDF_BYTES)
        with patch("university_jarvis.student_setup._save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                import_material("BIO101", src)
        self.assertEqual(list((self.home / "materials" / "BIO101").glob("*")), [])
        with record_lock(personal_state_path(), timeout=0.2):  # not left locked
            pass

    def test_nested_reassign_inside_duplicate_import_does_not_deadlock(self) -> None:
        from university_jarvis.student_setup import import_material

        src = Path(self.temp.name) / "dup.pdf"
        src.write_bytes(PDF_BYTES)
        import_material("BIO101", src, week=1)
        again = import_material("BIO101", src, week=2)  # duplicate -> reassign inside the transaction
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["source"]["week"], 2)

    def test_concurrent_first_run_initialisation_creates_one_state(self) -> None:
        from university_jarvis.student_setup import initialize_personal_state as init, personal_state_path

        personal_state_path().unlink()
        paths: list[Path] = []
        threads = [threading.Thread(target=lambda: paths.append(init())) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual(load_state()["modules"], [])
