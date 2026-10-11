"""Stage 1 adversarial runner (offline). Leak cases go through reveals_reference and the production
``_check_reply``; generated-question cases go through the production next_question path.

    python3 evals/diagnostic_slice0/run_adversarial.py [label]     # writes results/stage1_adversarial_<label>.json
"""

from __future__ import annotations

import json
import sys

import adversarial as A
import run_eval as R
from university_jarvis import tutor_policy as tp

label = sys.argv[1] if len(sys.argv) > 1 else "current"
rows = []
for case_id, ref, task, message, student, gold in A.LEAK:
    validator = tp.reveals_reference(message, ref, allowed_text=[task, student])
    ctx_subject = "statistics"
    res, why = R._check(ctx_subject, task, ref, message, student)
    production = res == "BLOCKED_LEAK"
    expected_block = gold == "LEAK"
    outcome = ("KNOWN_MISS" if gold == "KNOWN_MISS" and not production else
               "UNEXPECTED_BLOCK" if gold == "KNOWN_MISS" else
               {(True, True): "TRUE_BLOCK", (True, False): "MISSED_LEAK",
                (False, True): "FALSE_BLOCK", (False, False): "TRUE_PASS"}[(expected_block, production)])
    rows.append({"kind": "leak", "case": case_id, "gold": gold, "validator_blocked": validator,
                 "production_blocked": production, "outcome": outcome})
for case_id, subject, question, expected, cites, gold in A.GENERATED:
    obs = R.run_next(subject, question, expected, cites)
    with_pages = R._validate_tolerant(subject, question, expected, cites)
    rows.append({"kind": "generated", "case": case_id, "gold": gold, "observed": obs["observed"],
                 "outcome": R.accept_outcome(gold, obs["observed"]), "note": obs["reason"],
                 "validator_with_pages": with_pages, "validator_outcome": R.accept_outcome(gold, with_pages)})
out = R.HERE / "results" / f"stage1_adversarial_{label}.json"
out.write_text(json.dumps(rows, indent=1))
for r in rows:
    print(f"{r['kind']:9} {r['outcome']:17} {r.get('validator_outcome',''):14} {r['case']}  {r.get('note','')[:70]}")
