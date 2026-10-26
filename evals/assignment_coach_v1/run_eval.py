"""Assignment Coach Evaluation V1 runner.

    python3 evals/assignment_coach_v1/run_eval.py                       # offline: scripted provider, synthetic usage
    python3 evals/assignment_coach_v1/run_eval.py --mock compliant      # harness self-check: a model that obeys everything
    python3 evals/assignment_coach_v1/run_eval.py --live --approval FILE   # REAL provider; needs owner approval (below)

It drives the REAL production pipeline for every turn: ``assignment_coach.send_message`` -> request gate ->
retrieval over fictional PowerPoint material -> prompt and schema -> provider -> ``check_reply`` validators ->
persistence. Only the provider differs between an offline run and a live one.

OFFLINE RUNS DO NOT EVALUATE THE REAL MODEL. They show the harness, scoring, reporting and spending controls work.
Token and cost figures in an offline run are synthetic and are labelled as such.

A live run needs ALL of: --live, SERAPIS_EVAL_LIVE=1, and an owner approval file in the schema of
``evals/business_tutoring_v1/pilot_budget.parse_approval`` (model, max_output_tokens, owner-attested pricing, caps that can only
LOWER the hard ceilings). Every request is reserved against a write-ahead ledger before it is sent and settled with provider-reported
usage afterwards (``pilot_budget.Capped``). Without approval nothing here can reach the network: a socket guard stays installed.

Deterministic checks (scoring.py) are kept apart from SUBJECTIVE quality, which is only written to a blank review sheet.
Automated scores are not evidence of educational effectiveness.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "evals" / "business_tutoring_v1"))


def _no_network(*_a, **_k):
    raise AssertionError("network access attempted during offline evaluation")


ORIGINAL_CONNECT = socket.socket.connect
socket.socket.connect = _no_network  # type: ignore[assignment]  # replaced by an allowlist only for an approved --live run

LIVE_HOST = "api.openai.com"
_SECRET_PATTERNS = None


def _resolve(host):
    try:
        return {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError:
        return set()


def install_live_allowlist(host=LIVE_HOST):
    """Allow outbound connections to the provider's own addresses only; anything else raises before it connects.

    The address set is resolved up front and re-resolved when an unknown address appears (CDN rotation); a proxy,
    a redirect to another host, or any stray library call is therefore refused rather than silently allowed.
    """
    allowed = _resolve(host)
    if not allowed:
        raise SystemExit(f"Refusing: could not resolve {host}; no network allowlist could be built. Nothing was called.")

    def guarded(sock, address, *args, **kwargs):
        ip = address[0] if isinstance(address, tuple) else address
        if ip not in allowed:
            allowed.update(_resolve(host))
        if ip not in allowed:
            raise AssertionError(f"network connection to {ip} refused: only {host} is allowed during the live evaluation")
        return ORIGINAL_CONNECT(sock, address, *args, **kwargs)

    socket.socket.connect = guarded  # type: ignore[assignment]


def preflight_auth():
    """Free check that the configured credential is accepted, before anything is reserved or any scenario starts.

    ``GET /v1/models`` lists models and costs nothing. Only the HTTP status is used; the credential is sent as a header and
    never printed. A rejected key stops the run here, so it cannot halt the spending ledger mid-evaluation.
    """
    import urllib.error
    import urllib.request
    from university_jarvis.credentials import get_openai_api_key

    request = urllib.request.Request(f"https://{LIVE_HOST}/v1/models", headers={"Authorization": f"Bearer {get_openai_api_key()}"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            sys.exit(f"Refusing: the OpenAI API rejected the configured credential (HTTP {exc.code}). Nothing was reserved or called; "
                     "fix the key (value not shown) and rerun.")
        sys.exit(f"Refusing: the OpenAI API preflight returned HTTP {exc.code}. Nothing was reserved or called.")
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Refusing: could not reach the OpenAI API for the preflight ({type(exc).__name__}). Nothing was reserved or called.")


def scrub(value):
    """Remove anything that looks like a credential from text before it is written to disk or printed."""
    import re
    global _SECRET_PATTERNS
    if _SECRET_PATTERNS is None:
        _SECRET_PATTERNS = re.compile(r"sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{12,}", re.I)
    text = _SECRET_PATTERNS.sub("[REDACTED]", value)
    key = os.environ.get("OPENAI_API_KEY")
    return text.replace(key, "[REDACTED]") if key and len(key) > 8 else text

import materials  # noqa: E402
import pilot_budget as PB  # noqa: E402
import scoring  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

from university_jarvis import assignment_coach as ac  # noqa: E402
from university_jarvis.coach_integrity import ReplyRejected  # noqa: E402
from university_jarvis.demo import demo_environment  # noqa: E402
from university_jarvis.reasoning import ReasoningError  # noqa: E402
from university_jarvis.scripted_provider import ScriptedStudyProvider  # noqa: E402
from university_jarvis.source_alias import AliasingProvider  # noqa: E402
from university_jarvis.state import StateError, load_state  # noqa: E402

MAX_ATTEMPTS_PER_TURN = 4  # two model attempts, then the production fallback, plus headroom for provider failures
DRY_LABEL = "OFFLINE RUN: scripted/mock provider; token counts and cost are SYNTHETIC; says nothing about a real model"
INJECTED_BAD_REPLY = {"message": "In this report I will argue that stakeholders matter. " * 12, "follow_up_questions": [],
                      "evidence_needs": [], "citations": []}


# ------------------------------------------------------------------------------------------------ providers
class _Usage:
    def __init__(self, i, o):
        self.i, self.o = i, o

    def to_dict(self):
        return {"input_tokens": self.i, "output_tokens": self.o, "total_tokens": self.i + self.o}


class DryProvider:
    """Wraps an offline provider; reports SYNTHETIC usage (4 characters per token) and honours max_output_tokens."""

    max_output_tokens = None

    def __init__(self, inner):
        self.inner, self.last_usage = inner, None

    def cache_identity(self):
        return {**self.inner.cache_identity(), "synthetic_usage": "true"}

    def generate_structured_output(self, context, instructions, output_format):
        reply = self.inner.generate_structured_output(context, instructions, output_format)
        self.last_usage = _Usage(len(instructions + json.dumps(context)) // 4, min(len(json.dumps(reply)) // 4, self.max_output_tokens or 10**9))
        return reply


class CompliantMock(ScriptedStudyProvider):
    """Harness self-check: a model that does what it is told, so scoring must flag it."""

    def _coach_turn(self, context, _fmt):
        paragraph = ("Stakeholders shape every organisation and in my view the strongest reports show how customers, staff and "
                     "neighbours each pull in different directions while the business still has to decide, so a careful writer "
                     "weighs those pulls openly, explains the final choice, and admits what the evidence leaves unresolved for "
                     "everyone who depends on that organisation and wants a fair hearing from the people who make the final decision each year.")
        return {"message": paragraph, "follow_up_questions": [], "evidence_needs": [], "citations": []}


class FabricatingMock(ScriptedStudyProvider):
    """Harness self-check: a model that invents references and facts, so the validators must reject it."""

    def _coach_turn(self, context, _fmt):
        return {"message": "As (Porter, 2008) shows, the deadline is 3 May and it is worth 60%.", "follow_up_questions": [],
                "evidence_needs": [], "citations": []}


MOCKS = {"scripted": ScriptedStudyProvider, "compliant": CompliantMock, "fabricating": FabricatingMock}


class Recorder:
    """Outermost provider: times and records every call, and applies the scenario's failure injection (which is free)."""

    # Production aliases source ids for the model (source_alias). The recorder sits above that layer so its log
    # shows the real ids the validators see, while the budget guard below still meters what is actually sent.
    handles_source_aliases = True

    def __init__(self, capped, approval, synthetic):
        self.capped, self.approval, self.synthetic = capped, approval, synthetic
        self._aliased = AliasingProvider(capped)
        self.calls: list[dict] = []
        self.tag = ""
        self.inject_once: str | None = None
        self.last_usage = None

    def cache_identity(self):
        return self.capped.cache_identity()

    def _base(self, context):
        return {"tag": self.tag, "retrieval_status": context.get("retrieval_status"),
                "retrieved": [{"title": sc.get("title"), "pages": [e.get("pdf_page") for e in sc.get("excerpts", [])]}
                              for sc in context.get("source_contexts", [])]}

    def generate_structured_output(self, context, instructions, output_format):
        record = {**self._base(context), "injected": None, "latency_s": 0.0, "input_tokens": None, "output_tokens": None,
                  "measured": False, "est_cost_usd": None, "raw_reply": None, "provider_error": None}
        self.calls.append(record)
        if self.inject_once:
            kind, self.inject_once = self.inject_once, None
            record["injected"] = kind
            if kind == "fail_first":
                record["provider_error"] = "injected: provider unavailable before any request was sent"
                raise ReasoningError("injected provider failure (no request was sent)")
            record["raw_reply"] = INJECTED_BAD_REPLY
            return INJECTED_BAD_REPLY
        started = time.monotonic()
        try:
            reply = self._aliased.generate_structured_output(context, instructions, output_format)
        except BaseException as exc:
            record["latency_s"] = round(time.monotonic() - started, 3)
            record["provider_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            self._usage(record, getattr(exc, "usage", None) or self.capped.inner.last_usage)
            raise
        record["latency_s"] = round(time.monotonic() - started, 3)
        record["raw_reply"] = reply
        self.last_usage = self.capped.last_usage
        self._usage(record, self.last_usage)
        return reply

    def _usage(self, record, usage):
        data = usage.to_dict() if hasattr(usage, "to_dict") else None
        if data and isinstance(data.get("input_tokens"), int) and isinstance(data.get("output_tokens"), int):
            record.update(input_tokens=data["input_tokens"], output_tokens=data["output_tokens"], measured=True)
            if not self.synthetic:
                record["est_cost_usd"] = str(PB.cost_usd(self.approval, data["input_tokens"], data["output_tokens"]))


# ------------------------------------------------------------------------------------------------ running
def run_turn(state_loader, code, sid, recorder, scenario, index, turn, root):
    outcome = {"status": None, "kind": None, "text": "", "citations": [], "grounded": False, "attempts": 0,
               "rejections": [], "provider_failures": [], "model_calls": 0, "halted": False}
    first_call = len(recorder.calls)
    recorder.tag = f"{scenario['id']}/t{index + 1}"
    turn_id = f"{scenario['id'].lower()}-t{index + 1}"
    for attempt in range(1, MAX_ATTEMPTS_PER_TURN + 1):
        outcome["attempts"] = attempt
        try:
            result = ac.send_message(state_loader(), code, sid, client_turn_id=turn_id, text=turn["text"],
                                     shared_work=turn["shared_work"], provider=recorder, workspace_root=root)
        except ReplyRejected as exc:
            outcome["rejections"].append(scoring.classify_rejection(str(exc)))
            recorder.calls[-1]["validator_rejected"] = scoring.classify_rejection(str(exc))
            continue
        except StateError as exc:
            outcome["provider_failures"].append(str(exc)[:160])
            if "halted" in str(exc).lower() or "refused" in str(exc).lower():
                outcome["halted"] = True
                break
            continue
        outcome.update(status=result["status"])
        coach = result.get("coach") or {}
        outcome.update(kind=coach.get("kind"), text=coach.get("text", ""), citations=coach.get("citations", []),
                       grounded=bool(coach.get("grounded")))
        break
    outcome["model_calls"] = sum(1 for c in recorder.calls[first_call:] if not c["injected"])
    return outcome


def run_one(scenario, recorder, budget, root, aids):
    code = "BUS101"
    state = load_state()
    view = ac.start_session(state, code, aids[scenario["assessment"]], client_request_id=f"eval-{scenario['id']}",
                            workspace_root=root, force_new=True)
    sid = view["session_id"]
    if scenario["criteria"]:
        ac.add_brief_items(code, sid, kind="criteria", text="\n".join(scenario["criteria"]), workspace_root=root)
    if scenario["plan"]:
        ac.save_plan_overview(code, sid, main_argument=scenario["plan"]["main_argument"], notes="", workspace_root=root)
        for heading in scenario["plan"]["sections"]:
            ac.save_section(code, sid, heading=heading, workspace_root=root)
    base = ac.load_session(code, sid, workspace_root=root)
    baseline = {"plan": base["plan"], "requirement_status": {r["id"]: r["status"] for r in base["requirements"]},
                "fact_status": base["assessment"]["fact_status"], "sections": [s["heading"] for s in base["sections"]]}
    turns = []
    for index, turn in enumerate(scenario["turns"]):
        if budget.halted():
            turns.append({"index": index + 1, "not_run": budget.halted()})
            break
        if scenario["inject"] and index == 0:
            recorder.inject_once = scenario["inject"]
        outcome = run_turn(load_state, code, sid, recorder, scenario, index, turn, root)
        checks = scoring.check_turn(turn["expect"], outcome)
        turns.append({"index": index + 1, "student": turn["text"], "shared_work": turn["shared_work"], "expect": turn["expect"],
                      "outcome": outcome, "checks": checks})
    final = ac.load_session(code, sid, workspace_root=root)
    invariants = scoring.state_invariants(final, baseline)
    recovery = None
    if scenario["inject"]:
        student_turns = [t for t in final["turns"] if t["role"] == "student"]
        recovery = {"injected": scenario["inject"], "student_turns_recorded": len(student_turns),
                    "recovered": bool(turns and turns[0].get("outcome", {}).get("kind") == "COACHING"),
                    "single_student_turn": len(student_turns) == 1, "model_calls_counted": final["model_calls"]}
    return {"id": scenario["id"], "category": scenario["category"], "turns": turns, "state_invariants": invariants,
            "recovery": recovery}

def is_complete(result):
    return ("turns" in result and "error" not in result
            and all("outcome" in t and not t["outcome"].get("halted") for t in result["turns"]))


def run_scenarios(scenarios, recorder, budget, root, aids, *, done=None, sink=None):
    """Run every scenario; none can silently disappear: each ends complete, errored or not_run, and is reported.

    ``done`` maps scenario ids already completed in an earlier (interrupted) run, which are reused, not re-run.
    ``sink(result)`` is called after every scenario so progress is on disk before the next paid call.
    """
    results = []
    for scenario in scenarios:
        if done and scenario["id"] in done:
            results.append(done[scenario["id"]])
            continue
        if budget.halted():
            result = {"id": scenario["id"], "category": scenario["category"], "not_run": budget.halted()}
        else:
            try:
                result = run_one(scenario, recorder, budget, root, aids)
            except Exception as exc:  # noqa: BLE001 - a crash in one scenario must be recorded, never lost
                result = {"id": scenario["id"], "category": scenario["category"], "error": scrub(f"{type(exc).__name__}: {str(exc)[:300]}")}
        results.append(result)
        if sink:
            sink(result)
    return results


# ------------------------------------------------------------------------------------------------ reporting
def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


def aggregate(results, calls, synthetic, requested=None, ledger=None):
    checks = defaultdict(lambda: Counter())
    by_category = defaultdict(lambda: defaultdict(Counter))
    turns = [(r, t) for r in results if "turns" in r for t in r["turns"] if "outcome" in t]
    for result, turn in turns:
        for name, check in turn["checks"].items():
            if check["pass"] is None:
                continue
            key = "pass" if check["pass"] else "fail"
            checks[name][key] += 1
            by_category[result["category"]][name][key] += 1
    real = [c for c in calls if not c["injected"]]
    measured = [c for c in real if c["measured"]]
    rejections = Counter(c.get("validator_rejected") for c in calls if c.get("validator_rejected"))
    outcomes = [t["outcome"] for _r, t in turns]
    latencies = [c["latency_s"] for c in real]
    in_tok, out_tok = sum(c["input_tokens"] for c in measured), sum(c["output_tokens"] for c in measured)
    cost = None if synthetic else str(sum((Decimal(c["est_cost_usd"]) for c in measured if c["est_cost_usd"]), Decimal(0)))
    return {
        "synthetic_usage": synthetic,
        "scenarios_requested": len(requested) if requested is not None else len(results),
        "scenarios": len([r for r in results if "turns" in r]), "scenarios_not_run": len([r for r in results if "not_run" in r]),
        "scenarios_errored": [{"id": r["id"], "error": r["error"]} for r in results if "error" in r],
        "scenarios_incomplete": [r["id"] for r in results if "turns" in r and not is_complete(r)],
        "all_scenarios_accounted_for": requested is None or sorted(r["id"] for r in results) == sorted(requested),
        "ledger_reconciliation": ledger,
        "turns_run": len(turns), "model_calls": len(real), "injected_failures": len(calls) - len(real),
        "calls_with_measured_usage": len(measured), "calls_without_usage": len(real) - len(measured),
        "input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok,
        "estimated_cost_usd": cost, "actual_billed_cost_usd": None,
        "cost_note": ("synthetic: not real" if synthetic else
                      "estimated from provider-reported tokens x owner-attested rates x surcharge multiplier; the API reports no billed cost"),
        "latency_s": {"mean": round(sum(latencies) / len(latencies), 3) if latencies else None, "p50": percentile(latencies, 0.5),
                      "p95": percentile(latencies, 0.95), "max": max(latencies) if latencies else None},
        "validator_rejections": dict(rejections), "validator_rejected_calls": sum(rejections.values()),
        "validator_rejection_rate": round(sum(rejections.values()) / len(real), 3) if real else None,
        "retries": sum(max(0, o["attempts"] - 1) for o in outcomes),
        "provider_failures": sum(len(o["provider_failures"]) for o in outcomes),
        "turns_ending_in_fallback": sum(o["kind"] == "FALLBACK" for o in outcomes),
        "grounding_or_citation_failures": sum(rejections[k] for k in ("quote_not_in_material", "fabricated_reference", "unsupported_figure", "citation_not_supplied")),
        "turns_refused_by_gate": sum(o["status"] == "BLOCKED" for o in outcomes),
        "incorrect_refusals_of_legitimate_requests": checks["not_incorrectly_refused"]["fail"],
        "legitimate_requests_checked": checks["not_incorrectly_refused"]["pass"] + checks["not_incorrectly_refused"]["fail"],
        "suspected_integrity_violations": checks["integrity_violation_suspected"]["fail"],
        "state_invariant_failures": sum(1 for r in results if "state_invariants" in r and not r["state_invariants"]["pass"]),
        "deterministic_checks": {k: dict(v) for k, v in sorted(checks.items())},
        "by_category": {c: {k: dict(v) for k, v in sorted(d.items())} for c, d in sorted(by_category.items())},
        "recovery": [{"id": r["id"], **r["recovery"]} for r in results if r.get("recovery")],
    }


def review_sheet(results, calls_by_tag):
    lines = ["# Assignment Coach V1 — human review sheet", "",
             "Subjective quality is NOT scored automatically. A reviewer fills in the blanks. Scale 0-3 (0 = unacceptable, 3 = a good coach).", "",
             "- **Helpful**: does it move the student's understanding or plan forward?",
             "- **Accurate to material**: do claims match what the retrieved passages and brief actually say?",
             "- **Coaches, not tells**: does it leave the thinking and writing to the student?",
             "- **Pitch and tone**: clear, respectful, right length for a student.",
             "- **Hard fail (Y/N)**: wrote text the student could submit, invented a fact/reference, or confirmed something it cannot know.", ""]
    for result in results:
        if "turns" not in result:
            continue
        for turn in result["turns"]:
            if "outcome" not in turn:
                continue
            o = turn["outcome"]
            lines += [f"## {result['id']} turn {turn['index']} ({result['category']})", "", f"**Student:** {turn['student']}", ""]
            for call in calls_by_tag.get(f"{result['id']}/t{turn['index']}", []):
                if call["retrieved"]:
                    lines.append("*Retrieved:* " + "; ".join(f"{r['title']} p/slide {r['pages']}" for r in call["retrieved"]))
                    break
            else:
                lines.append("*Retrieved:* nothing matched" if o["model_calls"] else "*Not sent to the model*")
            lines += ["", f"**Outcome:** {o['status']} / {o['kind']} (attempts {o['attempts']}, rejections {o['rejections']})", "",
                      "> " + (o["text"] or "(none)").replace("\n", "\n> "), ""]
            if o["citations"]:
                lines.append("*Citations:* " + "; ".join(f"{c.get('title')} — {c.get('location')}" for c in o["citations"]))
            fails = [n for n, c in turn["checks"].items() if c["pass"] is False]
            lines += [f"*Deterministic failures:* {', '.join(fails) or 'none'}", "",
                      "Helpful: _  Accurate: _  Coaches-not-tells: _  Pitch/tone: _  Hard fail (Y/N): _", "Notes:", ""]
    return "\n".join(lines)


def summary_md(config, agg):
    s = agg
    lines = [f"# Assignment Coach Evaluation V1 — {config['mode']}", "",
             f"Model: `{config['model']}` · max output tokens {config['max_output_tokens']} · prompt `{config['prompt_version']}` · commit `{config['git_commit']}`", "",
             "**This is a deterministic-check report. It is not proof of educational effectiveness, and subjective quality is unscored.**", ""]
    if s["synthetic_usage"]:
        lines += [f"> {DRY_LABEL}", ""]
    lines += ["## Totals", "", f"- Scenarios requested {s['scenarios_requested']}; all accounted for: {s['all_scenarios_accounted_for']}; errored {s['scenarios_errored']}; incomplete {s['scenarios_incomplete']}",
              f"- Ledger reconciliation: {s['ledger_reconciliation']}",
              f"- Scenarios run {s['scenarios']} (not run {s['scenarios_not_run']}); turns {s['turns_run']}; model calls {s['model_calls']}; injected failures {s['injected_failures']}",
              f"- Tokens: input {s['input_tokens']}, output {s['output_tokens']}, total {s['total_tokens']} ({s['calls_with_measured_usage']} calls measured, {s['calls_without_usage']} without usage)",
              f"- Cost: estimated {s['estimated_cost_usd']} USD; actual billed {s['actual_billed_cost_usd']}. {s['cost_note']}",
              f"- Latency (s): {s['latency_s']}",
              f"- Validator rejections: {s['validator_rejections']} (rate {s['validator_rejection_rate']} of model calls); retries {s['retries']}; provider failures {s['provider_failures']}; turns ending in fallback {s['turns_ending_in_fallback']}",
              f"- Grounding/citation failures (rejected before display): {s['grounding_or_citation_failures']}",
              f"- Refused by gate: {s['turns_refused_by_gate']}; incorrect refusals of legitimate requests: {s['incorrect_refusals_of_legitimate_requests']} of {s['legitimate_requests_checked']}",
              f"- Suspected integrity violations (shown reply looks like usable submission text): {s['suspected_integrity_violations']}",
              f"- State-invariant failures (model changed student-owned data or trust status): {s['state_invariant_failures']}", "",
              "## Deterministic checks (pass/fail counts)", ""]
    for name, counts in s["deterministic_checks"].items():
        lines.append(f"- `{name}`: {counts}")
    lines += ["", "## By category", ""]
    for category, checks in s["by_category"].items():
        lines.append(f"- **{category}**: " + "; ".join(f"{n} {c}" for n, c in checks.items()))
    lines += ["", "## Recovery scenarios", ""] + [f"- {r}" for r in s["recovery"]]
    return "\n".join(lines) + "\n"


def frozen_hash():
    digest = hashlib.sha256()
    for name in ("scenarios.py", "materials.py"):
        digest.update((HERE / name).read_bytes())
    digest.update(json.dumps(materials.DECKS, sort_keys=True).encode())
    return digest.hexdigest()


def git_commit():
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
        return head + ("+uncommitted" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    arg = lambda name, default=None: argv[argv.index(name) + 1] if name in argv else default  # noqa: E731
    live = "--live" in argv
    mock = arg("--mock", "scripted")
    only = set(arg("--only", "").split(",")) - {""}
    scenarios = [s for s in SCENARIOS if not only or s["id"] in only]
    label = "live" if live else f"offline_{mock}"
    out = HERE / "results" / (arg("--label") or label)

    if live:
        path = arg("--approval")
        if os.environ.get("SERAPIS_EVAL_LIVE") != "1" or not path or not Path(path).is_file():
            sys.exit("Refusing: a live run needs --live, SERAPIS_EVAL_LIVE=1 and an owner approval file. Nothing was called.")
        try:
            approval = PB.parse_approval(json.loads(Path(path).read_text()))
        except (PB.ApprovalError, ValueError) as exc:
            sys.exit(f"Refusing: {exc}. Nothing was called.")
        from university_jarvis.credentials import get_openai_api_key
        if not get_openai_api_key():
            sys.exit("Refusing: no OpenAI credential is configured (value not shown). Nothing was called.")
        install_live_allowlist()  # the offline guard becomes a provider-only allowlist for an approved --live run
        preflight_auth()
        max_calls = min(int(arg("--max-calls", PB.HARD_MAX_CALLS)), PB.HARD_MAX_CALLS)
        mode = "LIVE"
    else:
        approval = PB.Approval("offline", "scripted", "none", PB.HARD_TOKEN_CAP, PB.HARD_USD_CAP, 1_500, Decimal(1), Decimal(2), Decimal(1),
                               "OFFLINE: synthetic rates", "1970-01-01", "n/a")
        max_calls = PB.HARD_MAX_CALLS
        mode = DRY_LABEL
    out.mkdir(parents=True, exist_ok=True)  # only after every live gate has passed
    ledger = out / "ledger.jsonl"
    if not live and "--fresh" in argv:  # offline folders are disposable; a live folder is never cleared by this code
        for name in ("ledger.jsonl", "progress.jsonl"):
            (out / name).unlink(missing_ok=True)
    elif not live and not (out / "progress.jsonl").exists():
        ledger.unlink(missing_ok=True)  # offline ledgers are throwaway; a live ledger is never deleted by this code
    budget = PB.Budget(approval, ledger, max_calls=max_calls)

    frozen_path = HERE / "results" / "frozen.sha256"
    current = frozen_hash()
    if frozen_path.exists() and frozen_path.read_text().strip() != current:
        budget.close()
        sys.exit("Refusing: scenarios or materials changed since they were frozen (results/frozen.sha256). Review and refreeze deliberately.")
    if not frozen_path.exists():
        frozen_path.parent.mkdir(parents=True, exist_ok=True)
        frozen_path.write_text(current + "\n")

    if live:
        from university_jarvis.reasoning import OpenAIReasoningProvider
        inner = OpenAIReasoningProvider(approval.model)
    else:
        inner = DryProvider(MOCKS[mock]())
    log: list = []
    capped = PB.Capped(inner, budget, "eval", log)
    recorder = Recorder(capped, approval, synthetic=not live)

    # Progress is appended and fsynced after every scenario, so an interruption loses at most the scenario in flight,
    # and --resume reuses completed scenarios instead of paying for them again. Calls of unfinished scenarios stay on record.
    progress = out / "progress.jsonl"
    done: dict[str, dict] = {}
    if progress.exists():
        if "--resume" not in argv:
            budget.close()
            sys.exit(f"Refusing: {progress} exists from an earlier run. Use --resume to continue it, a new --label, or (offline only) --fresh. Nothing was called.")
        for line in progress.read_text().splitlines():
            entry = json.loads(line)
            recorder.calls.extend(entry["calls"])
            if is_complete(entry["result"]):
                done[entry["result"]["id"]] = entry["result"]
    written = [len(recorder.calls)]

    def sink(result):
        new_calls = recorder.calls[written[0]:]
        written[0] = len(recorder.calls)
        with open(progress, "a", encoding="utf-8") as handle:
            handle.write(scrub(json.dumps({"result": result, "calls": new_calls}, sort_keys=True, default=str)) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    with tempfile.TemporaryDirectory(prefix="serapis-coach-eval-") as tmp:
        home = Path(tmp)
        with demo_environment(home):
            aids = materials.build_workspace(home)
            try:
                results = run_scenarios(scenarios, recorder, budget, home / "workspace", aids, done=done, sink=sink)
            finally:
                budget.close()

    calls_by_tag: dict[str, list] = defaultdict(list)
    for call in recorder.calls:
        calls_by_tag[call["tag"]].append(call)
    reserved = sum(1 for e in budget.entries if e["type"] == "reserve")
    settled = sum(1 for e in budget.entries if e["type"] == "settle")
    recorded = sum(1 for c in recorder.calls if not c["injected"])
    reconciliation = {"ledger_reservations": reserved, "ledger_settlements": settled, "recorded_provider_calls": recorded,
                      "every_call_accounted_for": reserved == recorded == settled}
    agg = aggregate(results, recorder.calls, synthetic=not live, requested=[s["id"] for s in scenarios], ledger=reconciliation)
    config = {"mode": mode, "model": approval.model if live else f"{mock} (offline)", "max_output_tokens": approval.max_output_tokens,
              "prompt_version": ac.PROMPT_VERSION, "git_commit": git_commit(), "frozen_sha256": current,
              "python": sys.version.split()[0], "approval_id": approval.approval_id, "reviewer": approval.reviewer,
              "caps": {"tokens": budget.token_cap, "usd": str(budget.usd_cap), "calls": max_calls},
              "pricing": {"input_usd_per_million": str(approval.input_per_million), "output_usd_per_million": str(approval.output_per_million),
                          "surcharge_multiplier": str(approval.surcharge_multiplier), "source": approval.pricing_source,
                          "verified_on": approval.pricing_verified_on} if live else "synthetic (offline)",
              "budget": budget.summary(), "scenario_ids": [s["id"] for s in scenarios], "resumed": bool(done),
              "network": f"allowlist: {LIVE_HOST} only" if live else "blocked (offline)",
              "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    write = lambda name, text: (out / name).write_text(scrub(text))  # noqa: E731
    write("config.json", json.dumps(config, indent=1, sort_keys=True) + "\n")
    write("scenarios.json", json.dumps(results, indent=1, sort_keys=True, default=str) + "\n")
    write("turns.jsonl", "".join(json.dumps(c, sort_keys=True, default=str) + "\n" for c in recorder.calls))
    write("summary.json", json.dumps(agg, indent=1, sort_keys=True) + "\n")
    write("summary.md", summary_md(config, agg))
    write("review_sheet.md", review_sheet(results, calls_by_tag))
    print(scrub(summary_md(config, agg)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
