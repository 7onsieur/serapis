"""Offline Diagnostic Slice 0 runner. Reads corpus.py, runs the REAL Serapis validators/tutoring paths
against synthetic material with scripted fake providers, writes results/results.json + results/summary.md.

No network, no model, no real data. Production code is imported, never modified; retrieval is the real
BM25 code run over the synthetic pages (only the file-extraction layer is replaced by a stand-in).

    python3 evals/diagnostic_slice0/run_eval.py
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))

# Hard offline guard, same idea as tests/conftest.py.
def _no_network(*_a, **_k):
    raise AssertionError("network access attempted during offline evaluation")
socket.socket.connect = _no_network  # type: ignore[assignment]

import corpus as C  # noqa: E402
from university_jarvis import tutoring, tutor_policy as tp  # noqa: E402
from university_jarvis.reasoning import ReasoningError  # noqa: E402
from university_jarvis.retrieval import build_passages, select_passages  # noqa: E402

CODE_PATH = {
    "root_reference": "tutoring.py _execute (L927) <- hub_service.continue_learning_task/_learning_task_candidates "
                      "(no support check on a root expected_answer; only _generated_reference_unsupported L1063 for generated questions)",
    "citation": "tutor_policy.validate_question (L298)",
    "quantitative": "tutor_policy.validate_question (L298) + tutoring._generated_reference_unsupported (L1063)",
    "leakage": "tutor_policy.reveals_reference (L130) via tutoring._check_reply (L535)",
    "hedge": "tutor_policy.detect_hedge (L66) -> next_action (L183) / plan_next (L241)",
}


# ---------------------------------------------------------------- fixtures
def _context_factory(subject: dict):
    sid = subject["source_id"]

    def build(_state, module_code, week_number, workflow, query="", source_ids=None, pinned=(), **_kw):
        passages = build_passages(sid, 0, subject["pages"])
        selected, report = select_passages(passages, query or "", pinned=list(pinned or ()))
        excerpts = [{"pdf_page": p.unit, "text": p.text} for p in selected]
        return {"module": {"code": module_code}, "week": {"number": week_number},
                "sources": [{"id": sid, "extraction": {"fingerprint": C.FINGERPRINT}}],
                "source_contexts": [{"source_id": sid, "retrieval": report, "excerpts": excerpts}]}
    return build


class Scripted:
    """Scripted offline provider. Records every call; returns a fixed diagnosis, always cites a supplied page."""

    def __init__(self, diagnosis="correct", generated=None):
        self.diagnosis, self.generated, self.calls = diagnosis, generated, []

    def cache_identity(self):
        return {"provider": "scripted", "model": "eval-fake"}

    def generate_structured_output(self, context, instructions, output_format):
        if "action" not in context:  # root-task generation call (hub_service.continue_learning_task)
            if self.generated is None:
                raise ReasoningError("scripted provider has no generated task")
            return self.generated
        self.calls.append(context)
        sc = context["source_contexts"][0]
        page = sc["excerpts"][0]["pdf_page"] if sc.get("excerpts") else 1
        action = context["action"]
        return {"message": f"{action} reply", "citations": [{"source_id": sc["source_id"], "pdf_page": page}],
                "diagnosis": self.diagnosis if action == "FEEDBACK" else "none"}


def _make_record(root: Path, subject: dict, ref: str | None, cite_page: int | None) -> None:
    sid = subject["source_id"]
    prov = [] if cite_page is None else [{"source_id": sid, "pdf_page": cite_page, "fingerprint": C.FINGERPRINT}]
    record = {
        "workspace_schema_version": 4, "module": {"code": C.MODULE, "title": "Eval"},
        "week": {"number": 1, "topic": subject["concept"]},
        "sources": [{"source_id": sid, "title": "Synthetic lecture", "type": "pdf",
                     "extraction": {"character_count": 999, "method": "pdf", "fingerprint": C.FINGERPRINT}}],
        "workflows": {"prepare_me": {"result": {}}, "teach": {"interactions": []}, "after_lecture": {"captures": []}},
        "learning": {"evidence": [], "quiz_history": {"status": "recorded", "attempts": [{
            "quiz_id": "quiz-1",
            "questions": [{"question_id": "r1", "question_type": "recall", "question": subject["root_task"],
                           "provenance": prov}],
            "answers": [{"question_id": "r1", "answer": ref}]}]}},
    }
    path = root / C.MODULE / "week-01" / "academic-record.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))


def run_session(subject_key: str, *, ref: str | None, cite_page: int | None, student: str, model_diagnosis: str,
                generated: dict | None = None):
    """Real tutoring path: create_session -> submit_response. Returns observation dict."""
    subject = C.SUBJECTS[subject_key]
    ctx = _context_factory(subject)
    with tempfile.TemporaryDirectory() as tmp, \
            patch("university_jarvis.hub_service.build_week_context", side_effect=ctx), \
            patch("university_jarvis.tutoring.build_week_context", side_effect=ctx):
        root = Path(tmp) / "ws"
        _make_record(root, subject, ref, cite_page)
        provider = Scripted(model_diagnosis, generated)
        try:
            session = tutoring.create_session({}, C.MODULE, 1, intention="TEST_ME", client_request_id="eval-1",
                                              provider=provider, workspace_root=root)
        except (tutoring.TutorSessionError, ReasoningError) as exc:
            return {"session_created": False, "reason": str(exc)}
        result = tutoring.submit_response({}, C.MODULE, 1, session["session_id"], client_turn_id="a1", text=student,
                                          provider=provider, workspace_root=root)
        view = tutoring.load_session(C.MODULE, 1, session["session_id"], workspace_root=root)
        turn = [t for t in view["turns"] if t.get("role") == "student"][-1]
        feedback_calls = [c for c in provider.calls if c["action"] == "FEEDBACK"]
        return {"session_created": True, "model_judged": bool(feedback_calls),
                "reference_sent_to_model": feedback_calls[0]["expected_answer_or_rubric"] if feedback_calls else None,
                "diagnosis": turn.get("diagnosis"), "hedged": turn.get("hedged"), "non_answer": turn.get("non_answer"),
                "next_action": turn.get("next_action"),
                "plan_step": view["sequence"]["plan"]["step"], "plan_reason": view["sequence"]["plan"]["reason"],
                "result_status": result.get("status", None)}


def _lead_lower(text: str) -> str:
    return text[0].lower() + text[1:]


# ---------------------------------------------------------------- results
RESULTS: list[dict] = []


def record(case_id, category, subtype, subject, gold, observed, outcome, *, note="", detail=None):
    RESULTS.append({"case_id": case_id, "category": category, "subtype": subtype, "subject": subject,
                    "gold": gold, "observed": observed, "outcome": outcome, "note": note,
                    "detail": detail or {}, "code_path": CODE_PATH[category]})


def accept_outcome(gold, observed):
    if gold == observed:
        return "TRUE_ACCEPT" if gold == "ACCEPT" else "TRUE_REJECT"
    return "FALSE_ACCEPT" if observed == "ACCEPT" else "FALSE_REJECT"


# ---------------------------------------------------------------- 1. root reference validation
def eval_root():
    for key, s in C.SUBJECTS.items():
        variants = [
            ("supported", s["root_ref"], 1, "ACCEPT"),
            ("unsupported", s["root_unsupported"], 1, "REJECT"),
            ("contradicted", s["root_contradicted"], 1, "REJECT"),
            ("wrong_page_irrelevant", s["root_ref"], 3, "REJECT"),
            ("wrong_page_decoy", s["root_ref"], 2, "REJECT"),
            ("missing_citation", s["root_ref"], None, "REJECT"),
            # Same references arriving through the model task-generation path (hub_service L440-466).
            ("generated_supported", s["root_ref"], "gen1", "ACCEPT"),
            ("generated_unsupported", s["root_unsupported"], "gen1", "REJECT"),
            ("generated_contradicted", s["root_contradicted"], "gen1", "REJECT"),
            ("generated_wrong_page", s["root_ref"], "gen3", "REJECT"),
        ]
        for name, ref, page, gold in variants:
            gen = None
            if isinstance(page, str):
                gen = {"task": s["root_task"], "expected_answer_or_rubric": ref,
                       "source_references": [{"source_id": s["source_id"], "pdf_page": int(page[3:])}]}
                ref, page = None, None
            obs = run_session(key, ref=ref, cite_page=page, student=s["root_correct_student"],
                              model_diagnosis="correct", generated=gen)
            # Observed ACCEPT == the stored reference was used to judge the student's answer.
            observed = "ACCEPT" if obs.get("session_created") and obs.get("model_judged") else "REJECT"
            record(f"ROOT-{key[:3]}-{name}", "root_reference", name, key, gold, observed, accept_outcome(gold, observed),
                   note=obs.get("reason", ""), detail={k: v for k, v in obs.items() if k != "reference_sent_to_model"})


# ---------------------------------------------------------------- 2/4. generated questions (citation + quantitative)
def _validate(subject_key, question, expected, cites, *, prior_extra=()):
    s = C.SUBJECTS[subject_key]
    sid = s["source_id"]
    ctx = {"sources": [{"id": sid}], "source_contexts": [{"source_id": sid, "retrieval": {"status": "matched"},
           "excerpts": [{"pdf_page": i, "text": t} for i, t in enumerate(s["pages"], 1)]}]}
    source_ids, units = {sid}, tutoring.supplied_units(ctx["source_contexts"])

    def citations_ok(c):
        tutoring._validate_citation_ids({"provenance": c}, source_ids)
        tutoring._validate_citation_pages({"provenance": c}, units)

    raw = {"question": question, "expected_answer": expected, "citations": cites}
    clean, reason = tp.validate_question(
        raw, step="FOLLOW_UP", citations_ok=citations_ok, cited_text=lambda c: tutoring._passage_text(ctx, c),
        shown=[s["root_task"]], prior_questions=[s["root_task"]], prior_answers=[s["root_ref"]],
        unrevealed_answers=[s["root_ref"]], concept_text=" ".join([s["root_task"], s["root_ref"]]))
    cited = tutoring._passage_text(ctx, cites)
    return ("ACCEPT" if clean else "REJECT"), reason, round(tp.answer_support(expected, cited), 3)


def eval_citation():
    for key, s in C.SUBJECTS.items():
        sid = s["source_id"]
        cite = lambda *pages: [{"source_id": sid, "pdf_page": p} for p in pages]
        variants = [
            ("valid", s["fq_valid"], cite(1), "ACCEPT"),
            ("irrelevant_page", s["fq_valid"], cite(3), "REJECT"),
            ("decoy_page", s["fq_valid"], cite(2), "REJECT"),
            ("unsupported_claim", s["fq_valid"] + s["fq_unsupported_tail"], cite(1), "REJECT"),
            ("contradicted_claim", s["fq_contradicted"], cite(1), "REJECT"),
            ("decoy_concept_answer", s["fq_decoy_swap"], cite(2), "REJECT"),
            ("extra_decoy_page_cited", s["fq_valid"], cite(1, 2), "REJECT"),
        ]
        for name, expected, cites, gold in variants:
            observed, reason, support = _validate(key, s["fq"], expected, cites)
            record(f"CITE-{key[:3]}-{name}", "citation", name, key, gold, observed, accept_outcome(gold, observed),
                   note=reason or "", detail={"answer_support": support})


def eval_quant():
    for key, q in C.QUANT.items():
        s = C.SUBJECTS[key]
        cites = [{"source_id": s["source_id"], "pdf_page": 1}]
        for name, gold in (("valid", "ACCEPT"), ("wrong_arith", "REJECT"), ("wrong_formula", "REJECT")):
            observed, reason, support = _validate(key, q["question"], q[name], cites)
            record(f"QUANT-{key[:3]}-{name}", "quantitative", name, key, gold, observed,
                   accept_outcome(gold, observed), note=reason or "",
                   detail={"answer_support": support,
                           "blocked_at_judge_time": support < tp.SUPPORT_MIN})


# ---------------------------------------------------------------- 3. answer leakage
def _check(subject_key, task, ref, message, student):
    s = C.SUBJECTS[subject_key]
    sid = s["source_id"]
    ctx = {"sources": [{"id": sid}], "source_contexts": [{"source_id": sid, "retrieval": {"status": "matched"},
           "excerpts": [{"pdf_page": 1, "text": s["pages"][0]}]}]}
    raw = {"message": message, "diagnosis": "partial", "citations": [{"source_id": sid, "pdf_page": 1}]}
    try:
        tutoring._check_reply(raw, action="FEEDBACK", task={"task": task, "expected_answer": ref}, context=ctx,
                              response=student, revealed=False)
        return "PASSED", ""
    except ReasoningError as exc:
        return ("BLOCKED_LEAK" if "reveal the reference" in str(exc) else "BLOCKED_OTHER"), str(exc)


def eval_leak():
    for key, s in C.SUBJECTS.items():
        ref, task = s["root_ref"], s["root_task"]
        words = ref.split()
        half = len(words) // 2
        first, second = " ".join(words[:half]), " ".join(words[half:])
        long_cases = [
            ("verbatim", f"Good attempt. For reference: {ref}", "my answer", "LEAK"),
            ("paraphrase", f"Good attempt. {s['paraphrase']}", "my answer", "LEAK"),
            ("student_quote_full", f'You wrote: "{ref}" -- let us check that against the source.', ref, "CLEAN"),
            ("student_partial_plus_leak", f'You wrote "{first}". The rest is: {second}', first, "LEAK"),
            ("clean_hint", "Re-read the first paragraph of the cited page and compare your wording with it.",
             "my answer", "CLEAN"),
        ]
        sh = s["short"]
        short_cases = [("short_leak", sh["leak"], "LEAK"), ("short_clean", sh["clean"], "CLEAN")]
        if "numeric_para" in sh:
            short_cases.append(("short_numeric_paraphrase", sh["numeric_para"], "LEAK"))
        for name, msg, student, gold in long_cases:
            res, why = _check(key, task, ref, msg, student)
            _leak_record(key, name, gold, res, why)
        for name, msg, gold in short_cases:
            res, why = _check(key, sh["task"], sh["ref"], msg, "my answer")
            _leak_record(key, name, gold, res, why)


def _leak_record(key, name, gold, res, why):
    blocked = res == "BLOCKED_LEAK"
    outcome = {("LEAK", True): "TRUE_BLOCK", ("LEAK", False): "MISSED_LEAK",
               ("CLEAN", True): "FALSE_BLOCK", ("CLEAN", False): "TRUE_PASS"}[(gold, blocked)]
    record(f"LEAK-{key[:3]}-{name}", "leakage", name, key, gold, "BLOCKED" if blocked else "PASSED", outcome,
           note=why if res == "BLOCKED_OTHER" else "")


# ---------------------------------------------------------------- 5. hedge handling
def eval_hedge():
    for key, s in C.SUBJECTS.items():
        base = s["root_correct_student"]
        mid_head, _, mid_tail = base.partition(" ")
        cases = [
            # name, student text, gold hedged, gold non_answer, gold model_judged, model diagnosis, allowed plan steps
            ("confident_control", base, False, False, True, "correct", {"TRANSFER"}),
            ("i_think_correct", "I think " + _lead_lower(base), True, False, True, "correct", {"FOLLOW_UP", "TRANSFER"}),
            ("perhaps_mid_correct", f"{mid_head}, perhaps, {mid_tail}", True, False, True, "correct", {"FOLLOW_UP", "TRANSFER"}),
            ("i_believe_correct", "I believe " + _lead_lower(base), True, False, True, "correct", {"FOLLOW_UP", "TRANSFER"}),
            ("idk", "idk", True, True, False, "unclear", {"NONE"}),
            ("unsure_what_asked", "I'm not sure what this question is asking.", True, True, False, "unclear", {"NONE"}),
        ]
        if s["hedge_content"]:
            cases.append(("hedge_phrase_as_content", s["hedge_content"], False, False, True, "correct", {"TRANSFER"}))
        for name, text, g_hedged, g_non, g_judged, diag, steps in cases:
            obs = run_session(key, ref=s["root_ref"], cite_page=1, student=text, model_diagnosis=diag)
            checks = {
                "hedged": (g_hedged, obs["hedged"]), "non_answer": (g_non, obs["non_answer"]),
                "model_judged": (g_judged, obs["model_judged"]),
                "diagnosis_preserved": (diag, obs["diagnosis"]),
                "progression": (sorted(steps), obs["plan_step"]),
            }
            wrong = [k for k, (g, o) in checks.items() if (o not in g if k == "progression" else g != o)]
            friction = obs["plan_step"] == "FOLLOW_UP" and obs["plan_reason"] == "REASONING_CHECK" \
                and name in ("i_think_correct", "perhaps_mid_correct", "i_believe_correct", "hedge_phrase_as_content")
            record(f"HEDGE-{key[:3]}-{name}", "hedge", name, key, {k: v[0] for k, v in checks.items()},
                   {k: v[1] for k, v in checks.items()}, "PASS" if not wrong else "FAIL",
                   note=("failed checks: " + ", ".join(wrong)) if wrong else "",
                   detail={"failed_checks": wrong, "next_action": obs["next_action"], "plan_reason": obs["plan_reason"],
                           "reasoning_check_friction": friction})


# ---------------------------------------------------------------- reporting
SEVERITY = {
    ("root_reference", "FALSE_ACCEPT"): "CRITICAL",
    ("citation", "FALSE_ACCEPT"): "HIGH", ("citation", "FALSE_REJECT"): "MEDIUM",
    ("quantitative", "FALSE_ACCEPT"): "HIGH", ("quantitative", "FALSE_REJECT"): "MEDIUM",
    ("leakage", "MISSED_LEAK"): "HIGH", ("leakage", "FALSE_BLOCK"): "LOW",
}


def severity(r):
    if r["outcome"] in ("TRUE_ACCEPT", "TRUE_REJECT", "TRUE_BLOCK", "TRUE_PASS", "PASS"):
        return None
    if r["category"] == "hedge":
        failed = set(r["detail"]["failed_checks"])
        return "MEDIUM" if failed & {"non_answer", "model_judged", "diagnosis_preserved", "progression"} else "LOW"
    if r["category"] == "leakage" and r["subtype"].startswith("short"):
        return "MEDIUM"
    return SEVERITY.get((r["category"], r["outcome"]), "MEDIUM")


def summarise():
    for r in RESULTS:
        r["severity"] = severity(r)
    by_cat = defaultdict(Counter)
    by_sub = defaultdict(Counter)
    for r in RESULTS:
        by_cat[r["category"]][r["outcome"]] += 1
        by_sub[(r["category"], r["subtype"])][r["outcome"]] += 1
    failures = [r for r in RESULTS if r["severity"]]
    return by_cat, by_sub, failures


def baseline():
    def sh(*a):
        return subprocess.run(a, cwd=REPO, capture_output=True, text=True).stdout.strip()
    files = sorted((REPO / "src/university_jarvis").glob("*.py"))
    return {"git_head": sh("git", "rev-parse", "--short", "HEAD"),
            "git_dirty_tracked_files": [l for l in sh("git", "status", "--porcelain").splitlines()
                                        if not l.startswith("??")],
            "python": sys.version.split()[0],
            "source_sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest()[:16] for f in files
                              if f.name in ("tutoring.py", "tutor_policy.py", "retrieval.py", "reasoning.py",
                                            "hub_service.py")}}


def main():
    eval_root(); eval_citation(); eval_quant(); eval_leak(); eval_hedge()
    by_cat, by_sub, failures = summarise()
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / "results.json").write_text(json.dumps(
        {"baseline": baseline(), "totals": {c: dict(v) for c, v in by_cat.items()}, "cases": RESULTS}, indent=1))
    lines = ["# Diagnostic Slice 0 -- generated summary", "", f"Baseline: {json.dumps(baseline())}", "",
             "## Outcomes by category", ""]
    for c, cnt in by_cat.items():
        lines.append(f"- {c}: " + ", ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    lines += ["", "## Outcomes by subtype", ""]
    for (c, st), cnt in sorted(by_sub.items()):
        lines.append(f"- {c}/{st}: " + ", ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    lines += ["", f"## Failed cases ({len(failures)})", ""]
    for r in failures:
        lines.append(f"- {r['case_id']} [{r['severity']}] {r['outcome']} gold={json.dumps(r['gold'])[:90]} "
                     f"observed={json.dumps(r['observed'])[:90]} {r['note']}")
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
