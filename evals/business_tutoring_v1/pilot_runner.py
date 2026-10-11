"""Live-pilot runner for Business Tutoring Evaluation V1 (see LIVE_PILOT_PROPOSAL.md).

    python3 evals/business_tutoring_v1/pilot_runner.py --dry-run         # default: scripted stand-in, no network, no cost
    python3 evals/business_tutoring_v1/pilot_runner.py --live --approval approval.json   # NOT approved, NOT run

The dry run exercises the exact pilot flow, the token ledger and the hard caps against a scripted provider that reports
synthetic token counts, so the machinery can be checked offline. A live run needs ALL of: --live, SERAPIS_PILOT_LIVE=1,
and an approval file written by the owner: {"approved": true, "model": "...", "token_cap": 600000, "usd_cap": 5,
"price_per_million_input_usd": x, "price_per_million_output_usd": y, "reviewer": "..."}.
Nothing here has made a model call. Measured usage only: a call with no usage is listed as unmeasured, never estimated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_eval as E  # noqa: E402  (installs the offline socket guard)
import tasks as T  # noqa: E402
from university_jarvis.reasoning import ReasoningError  # noqa: E402

PILOT_TASKS = ("CT-FIN1", "CT-MGT2", "MD-ECO1", "MD-FIN2", "CS-ACC1", "CS-MGT1", "AP-MKT2", "AP-ACC2")
DEFAULT_TOKEN_CAP, DEFAULT_USD_CAP, MEASURE_FIRST = 600_000, 5.0, 5


class CapReached(ReasoningError):
    pass


class Usage:
    def __init__(self, i, o):
        self.i, self.o = i, o

    def to_dict(self):
        return {"input_tokens": self.i, "output_tokens": self.o, "total_tokens": self.i + self.o}


class Ledger:
    def __init__(self, token_cap, usd_cap, price_in=None, price_out=None):
        self.token_cap, self.usd_cap, self.price = token_cap, usd_cap, (price_in, price_out)
        self.calls, self.input, self.output, self.unmeasured = [], 0, 0, 0

    @property
    def total(self):
        return self.input + self.output

    @property
    def usd(self):
        if None in self.price:
            return None
        return (self.input * self.price[0] + self.output * self.price[1]) / 1e6

    def exceeded(self):
        return self.total >= self.token_cap or (self.usd is not None and self.usd >= self.usd_cap)

    def projected_over_cap(self):
        """After the first calls: would the measured average per call blow the cap over the planned call count?"""
        n = len(self.calls)
        return n == MEASURE_FIRST and self.total / n * 45 > self.token_cap


class Capped:
    """Wraps any provider: enforces the cap before each call, records measured usage and the raw reply."""

    def __init__(self, inner, ledger, tag):
        self.inner, self.ledger, self.tag = inner, ledger, tag
        self.last_usage = None

    def cache_identity(self):
        return self.inner.cache_identity()

    def generate_structured_output(self, context, instructions, output_format):
        if self.ledger.exceeded():
            raise CapReached("pilot cap reached; remaining calls NOT RUN")
        if self.ledger.projected_over_cap():
            raise CapReached("first-5 average projects past the cap; halted for owner review")
        reply = self.inner.generate_structured_output(context, instructions, output_format)
        usage = getattr(self.inner, "last_usage", None)
        measured = usage.to_dict() if hasattr(usage, "to_dict") else None
        self.last_usage = usage
        if measured:
            self.ledger.input += measured["input_tokens"]
            self.ledger.output += measured["output_tokens"]
        else:
            self.ledger.unmeasured += 1
        self.ledger.calls.append({"tag": self.tag, "action": context.get("action"), "usage": measured, "raw_reply": reply})
        return reply


class FakeUsageTutor(E.Tutor):
    """Dry-run stand-in: scripted replies plus synthetic token counts (clearly not real)."""

    def generate_structured_output(self, context, instructions, output_format):
        reply = super().generate_structured_output(context, instructions, output_format)
        self.last_usage = Usage(len(json.dumps(context)) // 4, len(json.dumps(reply)) // 4)
        return reply


def make_provider(task, live, model):
    if live:
        from university_jarvis.reasoning import OpenAIReasoningProvider
        return OpenAIReasoningProvider(model)
    base = FakeUsageTutor(task)
    base.question = {"question": "Placeholder question for the dry run?", "expected_answer": "Placeholder.", "citations": base.cites}
    return base


def run_pilot(live, ledger, model=None):
    out = []
    for task in (t for t in T.TASKS if t["id"] in PILOT_TASKS):
        record = {"task": task["id"], "sessions": []}
        try:
            with E.Bench(task) as b:  # TEACH_ME: explanation
                p = Capped(make_provider(task, live, model), ledger, f"{task['id']}/teach")
                err = b.create("TEACH_ME", p)
                record["sessions"].append({"mode": "TEACH_ME", "error": err, "turns": b.view()["turns"] if b.sid else []})
                if ledger.exceeded():
                    raise CapReached("pilot cap reached; remaining sessions NOT RUN")
            for i, resp in enumerate(task["responses"]):
                with E.Bench(task) as b:
                    p = Capped(make_provider(task, live, model), ledger, f"{task['id']}/r{i+1}-{resp['kind']}")
                    err = b.create("TEST_ME", p) or b.answer(resp["text"], p)
                    s = {"mode": "TEST_ME", "response_kind": resp["kind"], "expected": T.EXPECTED_BY_KIND[resp["kind"]],
                         "error": err, "turns": b.view()["turns"] if b.sid else []}
                    if i == 0 and task.get("questions") and b.sid:
                        s["next_question_error"] = b.next_question(p)
                        s["questions"] = b.view()["questions"]
                    record["sessions"].append(s)
                    if ledger.exceeded():  # production code turns provider errors into rejected replies: check here too
                        raise CapReached("pilot cap reached; remaining sessions NOT RUN")
        except CapReached as exc:
            record["halted"] = str(exc)
            out.append(record)
            break
        out.append(record)
    return out


def main():
    live = "--live" in sys.argv
    cap = min(int(sys.argv[sys.argv.index("--token-cap") + 1]), DEFAULT_TOKEN_CAP) if "--token-cap" in sys.argv else DEFAULT_TOKEN_CAP
    ledger = Ledger(cap, DEFAULT_USD_CAP)  # --token-cap can only lower the cap
    model = None
    if live:
        a = sys.argv[sys.argv.index("--approval") + 1] if "--approval" in sys.argv else None
        if os.environ.get("SERAPIS_PILOT_LIVE") != "1" or not a or not Path(a).is_file():
            sys.exit("Refusing: live run needs --live, SERAPIS_PILOT_LIVE=1 and an owner approval file. Nothing was called.")
        ap = json.loads(Path(a).read_text())
        if ap.get("approved") is not True or not ap.get("model") or not ap.get("reviewer"):
            sys.exit("Refusing: approval file lacks approved=true, model or reviewer. Nothing was called.")
        ledger = Ledger(min(int(ap.get("token_cap", DEFAULT_TOKEN_CAP)), DEFAULT_TOKEN_CAP),
                        min(float(ap.get("usd_cap", DEFAULT_USD_CAP)), DEFAULT_USD_CAP),
                        ap.get("price_per_million_input_usd"), ap.get("price_per_million_output_usd"))
        model = ap["model"]
        import socket
        socket.socket.connect = E.ORIGINAL_CONNECT  # the offline guard is lifted for an approved --live run only
    sessions = run_pilot(live, ledger, model)
    summary = {"mode": "LIVE" if live else "DRY RUN (scripted; synthetic token counts, not real usage)", "model": model,
               "tasks": list(PILOT_TASKS), "calls": len(ledger.calls), "input_tokens": ledger.input, "output_tokens": ledger.output,
               "total_tokens": ledger.total, "unmeasured_calls": ledger.unmeasured, "usd": ledger.usd,
               "token_cap": ledger.token_cap, "usd_cap": ledger.usd_cap,
               "halted": [s["task"] for s in sessions if s.get("halted")]}
    out = HERE / "results" / ("live_pilot" if live else "pilot_dry_run")
    if "--out" in sys.argv:
        out = HERE / sys.argv[sys.argv.index("--out") + 1]
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger.json").write_text(json.dumps({"summary": summary, "calls": ledger.calls}, indent=1, sort_keys=True, default=str) + "\n")
    (out / "sessions.json").write_text(json.dumps(sessions, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
