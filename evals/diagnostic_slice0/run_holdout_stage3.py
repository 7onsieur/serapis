"""Runs the frozen Stage 3 holdout through the full ``tutor_policy.validate_question`` gate (offline).

    python3 evals/diagnostic_slice0/run_holdout_stage3.py <label>   # writes results/holdout_stage3/<label>.json

Outcomes: TRUE_ACCEPT, TRUE_BLOCK, FALSE_ACCEPT (expected BLOCK, was shown), FALSE_REJECT (expected ACCEPT, blocked).
The expected outcomes live in holdout_stage3.py and are not edited after results are seen.
"""

from __future__ import annotations

import collections
import json
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE))
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network access attempted"))  # type: ignore

import importlib
H = importlib.import_module(sys.argv[2] if len(sys.argv) > 2 else "holdout_stage3")  # noqa: E402
from university_jarvis import calculation as calc  # noqa: E402
from university_jarvis import tutor_policy as tp  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "current"
CITE = [{"source_id": "s1", "pdf_page": 1}]
rows = []
for case_id, category, question, expected, passage, spec, gold in H.CASES:
    raw = {"question": question, "expected_answer": expected, "citations": CITE}
    if spec is not None:
        raw["calculation"] = spec
    clean, reason = tp.validate_question(
        raw, step="FOLLOW_UP", citations_ok=lambda c: None, cited_text=lambda c: passage, shown=[],
        prior_questions=["Summarise the lecture."], prior_answers=[], unrevealed_answers=[],
        concept_text=question + " " + expected)
    observed = "ACCEPT" if clean else "BLOCK"
    engine = calc.verify_calculation(spec, question=question, expected_answer=expected, cited_pages=[passage]).status \
        if spec is not None else None
    outcome = {("ACCEPT", "ACCEPT"): "TRUE_ACCEPT", ("BLOCK", "BLOCK"): "TRUE_BLOCK",
               ("BLOCK", "ACCEPT"): "FALSE_ACCEPT", ("ACCEPT", "BLOCK"): "FALSE_REJECT"}[(gold, observed)]
    rows.append({"case": case_id, "category": category, "expected": gold, "observed": observed, "outcome": outcome,
                 "engine": engine, "reason": reason or ""})
out = HERE / "results" / H.__name__
out.mkdir(exist_ok=True)
(out / f"{label}.json").write_text(json.dumps(rows, indent=1))
for r in rows:
    if r["outcome"] in ("FALSE_ACCEPT", "FALSE_REJECT"):
        print(f"{r['outcome']:13} {r['category']:17} {r['case']:44} engine={r['engine']} {r['reason'][:90]}")
print(len(rows), dict(sorted(collections.Counter(r["outcome"] for r in rows).items())))
by = collections.defaultdict(collections.Counter)
for r in rows:
    by[r["category"]][r["outcome"]] += 1
for c, v in by.items():
    print(f"  {c}: {dict(sorted(v.items()))}")
