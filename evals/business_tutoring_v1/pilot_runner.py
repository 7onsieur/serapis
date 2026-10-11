"""Live-pilot runner for Business Tutoring Evaluation V1 (see LIVE_PILOT_PROPOSAL.md).

    python3 evals/business_tutoring_v1/pilot_runner.py --dry-run [--out DIR]     # default: scripted stand-in, no network, no cost
    python3 evals/business_tutoring_v1/pilot_runner.py --live --approval FILE    # NOT approved, NOT run

Every request, dry or live, passes through pilot_budget.Budget: a worst-case reservation (explicit max_output_tokens, byte-bounded
input, owner-attested pricing) is fsynced to a persistent ledger and checked against BOTH caps before the request is sent, and
settled with measured usage afterwards. Missing usage, unknown pricing, an over-reservation or an interrupted run halts the pilot
and is charged at worst case. Projected averages are not used as a limit.

A live run needs ALL of: --live, SERAPIS_PILOT_LIVE=1, and an owner approval file (schema: pilot_budget.parse_approval). The
offline socket guard stays installed until those checks pass. A provider that cannot carry a hard max_output_tokens is refused.
The pilot uses the V1.1 tasks (AP-ACC2 corrected); V1.0 results are untouched. Nothing here has made a model call.
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
from corrections import v1_1  # noqa: E402
import pilot_budget as PB  # noqa: E402
from university_jarvis.retrieval import build_passages, select_passages  # noqa: E402

PILOT_TASKS = ("CT-FIN1", "CT-MGT2", "MD-ECO1", "MD-FIN2", "CS-ACC1", "CS-MGT1", "AP-MKT2", "AP-ACC2")
KNOWN_LIMITATIONS = [
    "Retrieval: question generation can only cite pages retrieved for the ROOT question; transfer questions that cite a "
    "scenario page may be rejected for that reason, not because the model wrote a bad question (see retrieval_supplied_pages).",
    "Lexical validators: paraphrased answer leaks and quote-of-a-correct-answer misconception claims are not detectable offline.",
    "Gold labels were written by one author; AP-ACC2 good_transfer was corrected in V1.1.",
    "n = 8 tasks: finds gross failures, does not estimate quality.",
]


class Usage:
    def __init__(self, i, o):
        self.i, self.o = i, o

    def to_dict(self):
        return {"input_tokens": self.i, "output_tokens": self.o, "total_tokens": self.i + self.o}


class FakeUsageTutor(E.Tutor):
    """Dry-run stand-in: scripted replies plus synthetic token counts (clearly not real). Honours max_output_tokens."""

    max_output_tokens = None

    def generate_structured_output(self, context, instructions, output_format):
        reply = super().generate_structured_output(context, instructions, output_format)
        self.last_usage = Usage(len(json.dumps(context)) // 4, min(len(json.dumps(reply)) // 4, self.max_output_tokens or 10**9))
        return reply


def make_provider(task, live, model):
    if live:
        from university_jarvis.reasoning import OpenAIReasoningProvider
        return OpenAIReasoningProvider(model)
    base = FakeUsageTutor(task)
    base.question = {"question": "Placeholder question for the dry run?", "expected_answer": "Placeholder.", "citations": base.cites}
    return base


def supplied_pages(task):
    pack = E.P.PACKS[task["pack"]]
    sel, _ = select_passages(build_passages(pack["source_id"], 0, pack["pages"]), task["root_task"] + " " + task["reference"])
    return sorted(p.unit for p in sel)


def retrieval_report():
    """Pages the candidate good questions need vs pages root-question retrieval supplies. Reported even if the run halts."""
    report = {}
    for task in (t for t in v1_1.apply(T.TASKS) if t["id"] in PILOT_TASKS):
        needed = set(task["cite_pages"]) | {p for q in task.get("questions", []) if q["kind"].startswith("good") for p in q["pages"]}
        gap = sorted(needed - set(supplied_pages(task)))
        report[task["id"]] = {"supplied": supplied_pages(task), "needed": sorted(needed), "gap": gap}
    return report


def run_pilot(live, budget, model=None):
    out, log = [], []
    tasks = [t for t in v1_1.apply(T.TASKS) if t["id"] in PILOT_TASKS]
    for task in tasks:
        record = {"task": task["id"], "version": task.get("version", "1.0"), "sessions": []}
        out.append(record)
        plan = [("TEACH_ME", None)] + [("TEST_ME", r) for r in task["responses"]]
        for i, (mode, resp) in enumerate(plan):
            if budget.halted():
                record["halted"] = budget.halted()
                return out, log
            with E.Bench(task) as b:
                tag = f"{task['id']}/{'teach' if resp is None else f'r{i}-' + resp['kind']}"
                p = PB.Capped(make_provider(task, live, model), budget, tag, log)
                err = b.create(mode, p) if resp is None else (b.create(mode, p) or b.answer(resp["text"], p))
                s = {"mode": mode, "response_kind": resp and resp["kind"], "error": err,
                     "expected": resp and T.EXPECTED_BY_KIND[resp["kind"]], "turns": b.view()["turns"] if b.sid else []}
                if resp is not None and i == 1 and task.get("questions") and b.sid and not budget.halted():
                    s["next_question_error"] = b.next_question(p)
                    s["questions"] = b.view()["questions"]
                record["sessions"].append(s)
    return out, log


def main():
    live = "--live" in sys.argv
    arg = lambda name: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None  # noqa: E731
    out = HERE / (arg("--out") or ("results/live_pilot" if live else "results/pilot_dry_run"))
    out.mkdir(parents=True, exist_ok=True)
    if live:
        path = arg("--approval")
        if os.environ.get("SERAPIS_PILOT_LIVE") != "1" or not path or not Path(path).is_file():
            sys.exit("Refusing: live run needs --live, SERAPIS_PILOT_LIVE=1 and an owner approval file. Nothing was called.")
        try:
            approval = PB.parse_approval(json.loads(Path(path).read_text()))
        except (PB.ApprovalError, ValueError) as exc:
            sys.exit(f"Refusing: {exc}. Nothing was called.")
        ledger = out / "ledger.jsonl"  # never truncated: spend survives retries, crashes and restarts
    else:
        approval = PB.Approval("dry-run", "scripted", "none", min(PB.HARD_TOKEN_CAP, int(arg("--token-cap") or PB.HARD_TOKEN_CAP)),
                               PB.HARD_USD_CAP, 1_500, PB.Decimal(1), PB.Decimal(2), PB.Decimal(1),
                               "DRY RUN ONLY: synthetic rates", "1970-01-01", "n/a")
        ledger = out / "ledger.jsonl"
        ledger.unlink(missing_ok=True)  # dry-run ledgers are throwaway; a live ledger is never deleted by this code
    budget = PB.Budget(approval, ledger)
    if live:
        import socket
        socket.socket.connect = E.ORIGINAL_CONNECT  # the offline guard is lifted for an approved --live run only
    try:
        sessions, log = run_pilot(live, budget, approval.model if live else None)
    finally:
        budget.close()
    summary = {"mode": "LIVE" if live else "DRY RUN (scripted; synthetic token counts and rates, not real usage)",
               **budget.summary(), "tasks": list(PILOT_TASKS), "known_limitations": KNOWN_LIMITATIONS,
               "retrieval_gaps": {k: v["gap"] for k, v in retrieval_report().items() if v["gap"]},
               "retrieval_by_task": retrieval_report()}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    (out / "sessions.json").write_text(json.dumps(sessions, indent=1, sort_keys=True, default=str) + "\n")
    (out / "raw_replies.json").write_text(json.dumps(log, indent=1, sort_keys=True, default=str) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
