"""Business Tutoring Evaluation V1 -- offline runner.

    python3 evals/business_tutoring_v1/run_eval.py [--out results]

Exercises the REAL production tutoring paths (tutoring.create_session / submit_response / next_question,
tutor_policy.*, retrieval) over original synthetic source packs, with SCRIPTED providers. No network, no model,
no real student data. Production code is imported, never modified.

WHAT THIS PROVES: that the deterministic safety and behaviour layers act as intended when a scripted provider
returns a known reply. WHAT IT DOES NOT PROVE: that Serapis explains accurately, diagnoses real student answers,
or sets good questions. The provider here is scripted, so every "diagnosis" is the gold label fed back in.
Teaching quality is reported as NOT YET EVALUATED (see rubrics.py).

Expected outcomes are in tasks.py, frozen before the first run (results/frozen.sha256).
"""

from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))


def _no_network(*_a, **_k):
    raise AssertionError("network access attempted during offline evaluation")


ORIGINAL_CONNECT = socket.socket.connect  # restored only by pilot_runner.py --live, after owner approval
socket.socket.connect = _no_network  # type: ignore[assignment]

import packs as P  # noqa: E402
import rubrics as RB  # noqa: E402
import tasks as T  # noqa: E402
from university_jarvis import tutor_policy as tp, tutoring  # noqa: E402
from university_jarvis.reasoning import ReasoningError  # noqa: E402
from university_jarvis.retrieval import build_passages, select_passages  # noqa: E402

MODULE = "BUS101"
FINGERPRINT = {"algorithm": "sha256", "value": "bt-eval-fixture"}
LABEL = "OFFLINE SCRIPTED-PROVIDER RUN -- tests production safeguards and behaviour, NOT teaching quality"
CASES: list[dict] = []


# ------------------------------------------------------------------ fixtures
def _context_factory(pack: dict):
    sid = pack["source_id"]

    def build(_state, module_code, week_number, workflow, query="", source_ids=None, pinned=(), **_kw):
        passages = build_passages(sid, 0, pack["pages"])
        selected, report = select_passages(passages, query or "", pinned=list(pinned or ()))
        return {"module": {"code": module_code}, "week": {"number": week_number},
                "sources": [{"id": sid, "extraction": {"fingerprint": FINGERPRINT}}],
                "source_contexts": [{"source_id": sid, "retrieval": report,
                                     "excerpts": [{"pdf_page": p.unit, "text": p.text} for p in selected]}]}
    return build


def _make_record(root: Path, pack: dict, task: dict) -> None:
    sid = pack["source_id"]
    prov = [{"source_id": sid, "pdf_page": p, "fingerprint": FINGERPRINT} for p in task["cite_pages"]]
    record = {
        "workspace_schema_version": 4, "module": {"code": MODULE, "title": "Business evaluation"},
        "week": {"number": 1, "topic": pack["concept"]},
        "sources": [{"source_id": sid, "title": "Synthetic business pack", "type": "pdf",
                     "extraction": {"character_count": 999, "method": "pdf", "fingerprint": FINGERPRINT}}],
        "workflows": {"prepare_me": {"result": {}}, "teach": {"interactions": []}, "after_lecture": {"captures": []}},
        "learning": {"evidence": [], "quiz_history": {"status": "recorded", "attempts": [{
            "quiz_id": "quiz-1",
            "questions": [{"question_id": "r1", "question_type": "recall", "question": task["root_task"], "provenance": prov}],
            "answers": [{"question_id": "r1", "answer": task["reference"]}]}]}},
    }
    path = root / MODULE / "week-01" / "academic-record.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))


class Tutor:
    """Scripted provider. ``feedback`` / ``explain`` are callables(context)->raw reply; ``question`` is one raw dict."""

    def __init__(self, task, *, feedback=None, explain=None, question=None):
        self.task, self.feedback, self.explain, self.question, self.calls = task, feedback, explain, question, []
        self.cites = [{"source_id": P.PACKS[task["pack"]]["source_id"], "pdf_page": task["cite_pages"][0]}]

    def cache_identity(self):
        return {"provider": "scripted", "model": "bt-eval-fake"}

    def _default(self, action, diagnosis="none"):
        return {"message": f"{action} reply (scripted)", "citations": self.cites, "diagnosis": diagnosis}

    def generate_structured_output(self, context, instructions, output_format):
        action = context.get("action")
        if action is None:
            raise ReasoningError("scripted provider generates no tasks")
        self.calls.append(context)
        if action == "NEXT_QUESTION":
            return json.loads(json.dumps(self.question))
        if action == "EXPLAIN":
            return self.explain(context) if self.explain else self._default("EXPLAIN")
        if action == "FEEDBACK":
            return self.feedback(context) if self.feedback else self._default("FEEDBACK", "correct")
        return self._default(action)


class Bench:
    """One synthetic workspace + one task, patched to use the pack text through the REAL retrieval code."""

    def __init__(self, task):
        self.task, self.pack = task, P.PACKS[task["pack"]]
        self.n = 0

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        ctx = _context_factory(self.pack)
        self._patches = [patch("university_jarvis.hub_service.build_week_context", side_effect=ctx),
                         patch("university_jarvis.tutoring.build_week_context", side_effect=ctx)]
        for p in self._patches:
            p.start()
        self.root = Path(self._tmp.name) / "ws"
        _make_record(self.root, self.pack, self.task)
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _call(self, fn, *args, provider, **kw):
        self.n += 1
        try:
            fn({}, MODULE, 1, *args, client_turn_id=f"t{self.n}", provider=provider, workspace_root=self.root, **kw)
            return None
        except Exception as exc:  # noqa: BLE001 - rejection is an observed outcome, recorded not hidden
            return f"{type(exc).__name__}: {exc}"

    def create(self, intention, provider):
        try:
            s = tutoring.create_session({}, MODULE, 1, intention=intention, client_request_id="bt-1",
                                        provider=provider, workspace_root=self.root)
            self.sid = s["session_id"]
            return None
        except Exception as exc:  # noqa: BLE001
            self.sid = None
            return f"{type(exc).__name__}: {exc}"

    def answer(self, text, provider):
        return self._call(tutoring.submit_response, self.sid, provider=provider, text=text)

    def next_question(self, provider):
        return self._call(tutoring.next_question, self.sid, provider=provider)

    def view(self):
        return tutoring.load_session(MODULE, 1, self.sid, workspace_root=self.root)

    def tutor_text(self):
        return " ".join(t.get("text") or "" for t in self.view()["turns"] if t.get("role") == "tutor")

    def last_student_turn(self):
        return [t for t in self.view()["turns"] if t.get("role") == "student"][-1]


# ------------------------------------------------------------------ recording
def record(case_id, task, probe, expected, observed, *, failure_class=None, note="", detail=None, known_gap=False):
    ok = expected == observed
    CASES.append({"case_id": case_id, "task": task["id"], "subject": P.PACKS[task["pack"]]["subject"],
                  "capability": task["capability"], "probe": probe, "expected": expected, "observed": observed,
                  "outcome": "PASS" if ok else "FAIL", "failure_class": None if ok else failure_class,
                  "known_structural_gap": bool(known_gap and not ok), "note": note, "detail": detail or {}})


def _norm(text):
    return tp.normalise(text)


def _leaked(task, text):
    """True when any 6-word run of the reference appears in text not supplied by the student/question."""
    return tp.reveals_reference(text, task["reference"], allowed_text=[task["root_task"]])


def _fb(diagnosis, message, citations, misconception=None):
    def make(_ctx):
        raw = {"message": message, "citations": citations, "diagnosis": diagnosis}
        if misconception is not None:
            raw["misconception"] = misconception
        return raw
    return make


def _grounded_misconception(label, quote, cites):
    return {"label": label, "quote": quote, "confidence": "high", "citations": cites}


# ------------------------------------------------------------------ probes
def probe_responses(task):
    for i, resp in enumerate(task["responses"], 1):
        rid = f"{task['id']}/r{i}-{resp['kind']}"
        diag, hedged, non_answer, nxt, step, reason, model_called = T.EXPECTED_BY_KIND[resp["kind"]]
        h = tp.detect_hedge(resp["text"])
        record(f"{rid}/hedge_detect", task, "hedge_detect", {"hedged": hedged, "non_answer": non_answer},
               h, failure_class="HEDGE_MISMATCH")

        with Bench(task) as b:
            cites = Tutor(task).cites
            mis = (_grounded_misconception(resp["label"], resp["quote"], cites) if resp["kind"] == "misconception" else None)
            provider = Tutor(task, feedback=_fb(diag if diag != "unclear" else "unclear", "Feedback (scripted): see the cited passage.", cites, mis))
            err = b.create("TEST_ME", provider)
            err = err or b.answer(resp["text"], provider)
            if b.sid is None:
                record(f"{rid}/pipeline", task, "pipeline", "SESSION_OPENS", f"NO_SESSION: {err}", failure_class="UNNECESSARY_REFUSAL")
                continue
            turn, view = b.last_student_turn(), b.view()
            plan = view["sequence"]["plan"]
            called = any(c["action"] == "FEEDBACK" for c in provider.calls)
            got = {"diagnosis": turn.get("diagnosis"), "hedged": turn.get("hedged"), "non_answer": turn.get("non_answer"),
                   "next_action": turn.get("next_action"), "plan_step": plan["step"], "plan_reason": plan["reason"],
                   "model_called": called,
                   "misconception_kept": bool(turn.get("misconception")) if resp["kind"] == "misconception" else None}
            want = {"diagnosis": diag, "hedged": hedged, "non_answer": non_answer, "next_action": nxt, "plan_step": step,
                    "plan_reason": reason, "model_called": model_called,
                    "misconception_kept": True if resp["kind"] == "misconception" else None}
            record(f"{rid}/pipeline", task, "pipeline", want, got, failure_class="POLICY_OR_PIPELINE_MISMATCH",
                   note="diagnosis is the scripted gold label returned by the provider: this checks routing, not diagnostic skill",
                   detail={"mismatched": sorted(k for k in want if want[k] != got[k])})

        if resp["kind"] == "correct":  # no unnecessary refusal when feedback quotes the student's own correct words
            with Bench(task) as b:
                msg = f"You wrote: \"{resp['text']}\" That is consistent with the passage; try applying it to a new case."
                provider = Tutor(task, feedback=_fb("correct", msg, Tutor(task).cites))
                b.create("TEST_ME", provider)
                b.answer(resp["text"], provider)
                shown = msg in b.tutor_text() or any(t.get("text") == msg for t in b.view()["turns"])
                record(f"{rid}/student_echo_not_blocked", task, "legit_feedback_shown", "SHOWN", "SHOWN" if shown else "BLOCKED",
                       failure_class="UNNECESSARY_REFUSAL")


def probe_guidance(task):
    mis = [r for r in task["responses"] if r["kind"] == "misconception"]
    if not mis or not task.get("guidance"):
        return
    r = mis[0]
    with Bench(task) as b:
        cites = Tutor(task).cites
        provider = Tutor(task, feedback=_fb("misconception", task["guidance"], cites,
                                            _grounded_misconception(r["label"], r["quote"], cites)))
        b.create("TEST_ME", provider)
        b.answer(r["text"], provider)
        shown = any(t.get("text") == task["guidance"] for t in b.view()["turns"])
        record(f"{task['id']}/corrective_guidance_not_blocked", task, "legit_feedback_shown", "SHOWN",
               "SHOWN" if shown else "BLOCKED", failure_class="UNNECESSARY_REFUSAL",
               note="authored non-leaking corrective guidance should pass the leak check; whether it is GOOD guidance is not evaluated")


def probe_leaks(task):
    first = next((r for r in task["responses"] if r["kind"] == "partial"), task["responses"][0])
    variants = [("leak_verbatim", "Here is the idea in full: " + task["reference"])]
    if task.get("leak_paraphrase"):
        variants.append(("leak_paraphrase", task["leak_paraphrase"]))
    for name, message in variants:
        with Bench(task) as b:
            cites = Tutor(task).cites
            provider = Tutor(task, feedback=_fb("partial", message, cites))
            b.create("TEST_ME", provider)
            b.answer(first["text"], provider)
            shown = message in " ".join(t.get("text") or "" for t in b.view()["turns"])
            record(f"{task['id']}/{name}_feedback", task, name, "BLOCKED", "LEAKED" if shown else "BLOCKED",
                   failure_class="ANSWER_LEAK", known_gap=(name == "leak_paraphrase"),
                   note="paraphrase leaks in different vocabulary are a documented limit of lexical screening" if name == "leak_paraphrase" else "")
    # explanation (TEACH_ME) must also not reproduce the reference
    with Bench(task) as b:
        cites = Tutor(task).cites
        provider = Tutor(task, explain=lambda _c: {"message": "Explanation: " + task["reference"], "citations": cites, "diagnosis": "none"})
        err = b.create("TEACH_ME", provider)
        shown = b.sid is not None and any(t.get("kind") == "EXPLANATION" for t in b.view()["turns"])
        record(f"{task['id']}/leak_verbatim_explanation", task, "leak_verbatim_explanation", "BLOCKED", "LEAKED" if shown else "BLOCKED",
               failure_class="ANSWER_LEAK", note=err or "")


def probe_teach_me(task):
    with Bench(task) as b:
        provider = Tutor(task)
        err = b.create("TEACH_ME", provider)
        opened = b.sid is not None
        explained = opened and any(t.get("kind") == "EXPLANATION" for t in b.view()["turns"])
        explain_called = any(c["action"] == "EXPLAIN" for c in provider.calls)
        cites_ok = explained and all(c["pdf_page"] in {1, 2, 3} for t in b.view()["turns"] if t.get("kind") == "EXPLANATION" for c in t["citations"])
        record(f"{task['id']}/teach_me_opens", task, "teach_me_opens",
               {"session": True, "explanation_turn": True, "explain_called": True, "cited_supplied_pages": True},
               {"session": opened, "explanation_turn": explained, "explain_called": explain_called, "cited_supplied_pages": bool(cites_ok)},
               failure_class="UNNECESSARY_REFUSAL", note=err or "explanation text is scripted: its accuracy and level are NOT evaluated")


def probe_false_accusation(task):
    correct = next(r for r in task["responses"] if r["kind"] == "correct")
    words = correct["text"].split()
    cases = [("fabricated_quote", "this answer is confused about everything", False),
             ("real_quote", " ".join(words[:5]), True)]
    for name, quote, gap in cases:
        with Bench(task) as b:
            cites = Tutor(task).cites
            provider = Tutor(task, feedback=_fb("misconception", "Feedback (scripted).", cites,
                                                _grounded_misconception("Scripted false accusation", quote, cites)))
            b.create("TEST_ME", provider)
            b.answer(correct["text"], provider)
            turn = b.last_student_turn()
            accused = bool(turn.get("misconception"))
            record(f"{task['id']}/false_accusation_{name}", task, f"false_accusation_{name}", "NOT_ACCUSED",
                   "ACCUSED" if accused else "NOT_ACCUSED", failure_class="FALSE_ACCUSATION", known_gap=gap,
                   detail={"stored_diagnosis": turn.get("diagnosis")},
                   note=("a quote that really is in the student's words passes every deterministic check; only a better model or "
                         "human review can tell the model's claim is wrong") if gap else "quote not in the student's words")


def probe_unsupported_citation(task):
    resp = next(r for r in task["responses"] if r["kind"] == "partial")
    bad = [{"source_id": P.PACKS[task["pack"]]["source_id"], "pdf_page": 9}]
    msg = "Feedback (scripted) citing material that was never supplied."
    with Bench(task) as b:
        provider = Tutor(task, feedback=_fb("partial", msg, bad))
        b.create("TEST_ME", provider)
        b.answer(resp["text"], provider)
        shown = any(t.get("text") == msg for t in b.view()["turns"])
        record(f"{task['id']}/citation_to_unsupplied_page", task, "citation_to_unsupplied_page", "BLOCKED",
               "SHOWN" if shown else "BLOCKED", failure_class="UNSUPPORTED_CLAIM_SHOWN",
               note="checks that citations point at supplied pages; does NOT check that a claim is true of the cited page")


def probe_questions(task):
    sid = P.PACKS[task["pack"]]["source_id"]
    for q in task["questions"]:
        resp = next(r for r in task["responses"] if r["kind"] == q["after"])
        diag, _h, _n, _nx, step, reason, _m = T.EXPECTED_BY_KIND[resp["kind"]]
        cid = f"{task['id']}/question-{q['kind']}"
        with Bench(task) as b:
            cites = Tutor(task).cites
            qraw = {"question": q["question"], "expected_answer": q["expected_answer"],
                    "citations": [{"source_id": sid, "pdf_page": p} for p in q["pages"]]}
            provider = Tutor(task, feedback=_fb(diag, "Feedback (scripted).", cites), question=qraw)
            b.create("TEST_ME", provider)
            b.answer(resp["text"], provider)
            err = b.next_question(provider)
            view = b.view()
            accepted = len(view["questions"]) == 2
            layer = None if accepted else ("RETRIEVAL" if "not a supplied source passage" in (err or "") else "VALIDATION")
            checks = (view["questions"][1].get("generated") or {}).get("checks") if accepted else None
            record(cid, task, f"question_{q['kind']}", q["gold"], "ACCEPT" if accepted else "REJECT",
                   failure_class="BAD_QUESTION_SHOWN" if q["gold"] == "REJECT" else "GOOD_QUESTION_REJECTED",
                   note=err or "", detail={"rejected_by_layer": layer, "lexical_diagnostics_not_quality_scores": checks})
            asked = [c for c in provider.calls if c["action"] == "NEXT_QUESTION"]
            if q["kind"] in ("good_transfer", "good_followup"):
                got = ({"step": asked[0]["step"], "reason": asked[0]["reason"], "diagnosis": asked[0]["diagnosis"],
                        "student_response_passed": asked[0]["student_response"] == resp["text"]} if asked else None)
                want = {"step": step, "reason": reason, "diagnosis": diag, "student_response_passed": True}
                record(f"{task['id']}/adaptive_request-{q['after']}", task, "adaptive_request", want, got,
                       failure_class="POLICY_OR_PIPELINE_MISMATCH",
                       note="checks the follow-up REQUEST is shaped by the student's last answer; whether the model's question targets the gap is NOT evaluated")


# ------------------------------------------------------------------ reporting
def not_yet_evaluated():
    per_cap = defaultdict(lambda: {"tasks": 0, "dimensions": []})
    for t in T.TASKS:
        per_cap[t["capability"]]["tasks"] += 1
        per_cap[t["capability"]]["dimensions"] = sorted(RB.RUBRICS[t["capability"]]["dimensions"])
    return {cap: {"status": RB.STATUS, "tasks": v["tasks"], "dimensions": v["dimensions"],
                  "dimension_judgements_pending": v["tasks"] * len(v["dimensions"]),
                  "needs": RB.RUBRICS[cap]["assessor"], "hard_fails": RB.RUBRICS[cap]["hard_fails"]}
            for cap, v in sorted(per_cap.items())}


def fingerprints():
    h = hashlib.sha256()
    for name in ("tutoring.py", "tutor_policy.py", "retrieval.py", "relations.py", "calculation.py"):
        h.update(name.encode())
        h.update((REPO / "src" / "university_jarvis" / name).read_bytes())
    frozen = hashlib.sha256()
    for name in ("packs.py", "tasks.py", "rubrics.py"):
        frozen.update(name.encode())
        frozen.update((HERE / name).read_bytes())
    recorded = (HERE / "results" / "frozen.sha256").read_text().strip()
    return {"production_code_sha256": h.hexdigest(), "frozen_inputs_sha256": frozen.hexdigest(),
            "frozen_inputs_unchanged_since_freeze": frozen.hexdigest() == recorded}


def tallies():
    by = defaultdict(Counter)
    for c in CASES:
        by[("probe", c["probe"])][c["outcome"]] += 1
        by[("subject", c["subject"])][c["outcome"]] += 1
        by[("capability", c["capability"])][c["outcome"]] += 1
    return {f"{k[0]}:{k[1]}": dict(v) for k, v in sorted(by.items())}


def coverage():
    cov = defaultdict(lambda: defaultdict(int))
    for t in T.TASKS:
        cov[P.PACKS[t["pack"]]["subject"]][t["capability"]] += 1
    resp = Counter(r["kind"] for t in T.TASKS for r in t["responses"])
    return {"tasks_by_subject_and_capability": {s: dict(sorted(c.items())) for s, c in sorted(cov.items())},
            "tasks": len(T.TASKS), "packs": len(P.PACKS), "scripted_student_responses": sum(resp.values()),
            "responses_by_kind": dict(sorted(resp.items())),
            "scripted_generated_questions": sum(len(t.get("questions", [])) for t in T.TASKS)}


def main():
    out = HERE / "results"
    if "--out" in sys.argv:
        out = HERE / sys.argv[sys.argv.index("--out") + 1]
    variant = "1.0"
    if "--variant" in sys.argv and sys.argv[sys.argv.index("--variant") + 1] == "v1_1":
        from corrections import v1_1  # noqa: E402  (V1.0 files are never edited; the correction is applied in memory)
        T.TASKS[:] = v1_1.apply(T.TASKS)
        variant = "1.1 (AP-ACC2 good_transfer corrected; historical V1.0 labels and results are unchanged)"
    for task in T.TASKS:
        probe_responses(task)
        probe_guidance(task)
        probe_leaks(task)
        probe_teach_me(task)
        if task["capability"] == "CASE_STUDY_APPLICATION":
            probe_unsupported_citation(task)
        if task["id"] in T.PROBE_TASKS_FOR_FALSE_ACCUSATION:
            probe_false_accusation(task)
        if task.get("questions"):
            probe_questions(task)
    CASES.sort(key=lambda c: c["case_id"])
    fails = [c for c in CASES if c["outcome"] == "FAIL"]
    by_class = Counter(c["failure_class"] for c in fails)
    result = {
        "label": LABEL, "variant": variant, "fingerprints": fingerprints(), "coverage": coverage(),
        "totals": {"cases": len(CASES), "pass": len(CASES) - len(fails), "fail": len(fails),
                   "fail_known_structural_gap": sum(c["known_structural_gap"] for c in fails)},
        "failures_by_class": dict(sorted(by_class.items())), "tallies": tallies(),
        "not_yet_evaluated": not_yet_evaluated(), "cases": CASES}
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (out / "summary.md").write_text(render(result, fails))
    print(render(result, fails))
    return result


def render(r, fails):
    L = [f"# Business Tutoring Evaluation V1 -- generated summary", "", f"**{r['label']}**", "",
         f"Frozen inputs unchanged since freeze: {r['fingerprints']['frozen_inputs_unchanged_since_freeze']}",
         f"Production code fingerprint: `{r['fingerprints']['production_code_sha256'][:16]}`", "",
         f"## Coverage ({r['coverage']['tasks']} tasks, {r['coverage']['packs']} packs, "
         f"{r['coverage']['scripted_student_responses']} scripted responses, {r['coverage']['scripted_generated_questions']} scripted generated questions)", ""]
    for s, caps in r["coverage"]["tasks_by_subject_and_capability"].items():
        L.append(f"- {s}: " + ", ".join(f"{k}={v}" for k, v in caps.items()))
    L += ["", f"## Offline deterministic checks: {r['totals']['pass']} pass / {r['totals']['fail']} fail of {r['totals']['cases']} "
              f"({r['totals']['fail_known_structural_gap']} of the failures are documented structural gaps)", ""]
    for k, v in sorted(r["tallies"].items()):
        if k.startswith("probe:"):
            L.append(f"- {k[6:]}: " + ", ".join(f"{a}={b}" for a, b in sorted(v.items())))
    L += ["", "## Failures by class", ""] + [f"- {k}: {v}" for k, v in r["failures_by_class"].items()]
    L += ["", "## Failed cases", ""]
    for c in fails:
        L.append(f"- {c['case_id']} [{c['failure_class']}{' / known gap' if c['known_structural_gap'] else ''}] "
                 f"expected={json.dumps(c['expected'])[:80]} observed={json.dumps(c['observed'])[:80]}")
    L += ["", "## NOT YET EVALUATED (needs a live model and/or human reviewer; no score is given or implied)", ""]
    for cap, v in r["not_yet_evaluated"].items():
        L.append(f"- {cap}: {v['status']} -- {v['tasks']} tasks x {len(v['dimensions'])} dimensions = "
                 f"{v['dimension_judgements_pending']} judgements pending ({', '.join(v['dimensions'])})")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
