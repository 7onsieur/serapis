"""Stage 3 adversarial runner (offline): independent mathematical verification.

    python3 evals/diagnostic_slice0/run_adversarial_stage3.py after            # verifier on
    python3 evals/diagnostic_slice0/run_adversarial_stage3.py before --before  # same questions, calculation stripped

ENGINE cases call ``calculation.verify_calculation`` directly (cited text supplied, so retrieval is not involved).
In ``--before`` mode the stand-in for the old behaviour is the Stage 1/2 reference gate alone
(``tutor_policy.reference_unsupported`` on the expected answer): the old system had no channel for a formula, so the
``malicious`` category has no "before".
GENERATED cases go through the production path (real retrieval, create_session -> skip -> next_question). In
``--before`` mode the calculation is dropped from the model's reply, which is exactly what the old system saw.

Outcomes: TRUE_ACCEPT / TRUE_REJECT / FALSE_ACCEPT / FALSE_REJECT;
  SAFE_BLOCK        gold REJECT, verifier INCONCLUSIVE (blocked, but not rejected for the right reason);
  UNVERIFIED_VALID  gold ACCEPT, verifier INCONCLUSIVE (a correct calculation that could not be verified: usability cost);
  INCONCLUSIVE_OK   gold INCONCLUSIVE and the verifier abstained;  BLOCKED_OTHER  gold INCONCLUSIVE, verifier REJECTED;
  KNOWN_LIMIT_*     cases whose right answer needs meaning the verifier cannot see.
"""

from __future__ import annotations

import collections
import json
import sys

import adversarial_stage3 as A
import run_eval as R
from university_jarvis import calculation as calc
from university_jarvis import tutor_policy as tp

label = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "current"
before = "--before" in sys.argv


def engine_outcome(gold: str, status: str) -> str:
    if gold == "KNOWN_LIMIT":
        return "KNOWN_LIMIT_FALSE_ACCEPT" if status == "ACCEPT" or status == calc.VERIFIED else "KNOWN_LIMIT_BLOCKED"
    if gold == "ACCEPT":
        return {calc.VERIFIED: "TRUE_ACCEPT", "ACCEPT": "TRUE_ACCEPT", calc.INCONCLUSIVE: "UNVERIFIED_VALID",
                calc.REJECTED: "FALSE_REJECT", "REJECT": "FALSE_REJECT"}[status]
    if gold == "REJECT":
        return {calc.VERIFIED: "FALSE_ACCEPT", "ACCEPT": "FALSE_ACCEPT", calc.INCONCLUSIVE: "SAFE_BLOCK",
                calc.REJECTED: "TRUE_REJECT", "REJECT": "TRUE_REJECT"}[status]
    return {calc.VERIFIED: "FALSE_ACCEPT", "ACCEPT": "FALSE_ACCEPT", calc.INCONCLUSIVE: "INCONCLUSIVE_OK",
            calc.REJECTED: "BLOCKED_OTHER", "REJECT": "INCONCLUSIVE_OK"}[status]


rows = []
for case_id, category, question, expected, passage, spec, gold in A.ENGINE:
    if before:
        if category == "malicious":
            continue
        status = "ACCEPT" if passage and tp.reference_unsupported(expected, [passage]) is None else "REJECT"
        reason = "old reference gate"
    else:
        verdict = calc.verify_calculation(spec, question=question, expected_answer=expected,
                                          cited_pages=[passage] if passage else [])
        status, reason = verdict.status, verdict.reason
    rows.append({"kind": "engine", "case": case_id, "category": category, "gold": gold, "observed": status,
                 "outcome": engine_outcome(gold, status), "note": reason})

for case_id, subject, question, expected, spec, gold in A.GENERATED:
    cites = [{"source_id": R.C.SUBJECTS[subject]["source_id"], "pdf_page": 1}]
    obs = R.run_next(subject, question, expected, cites, calculation=None if before else spec)
    rows.append({"kind": "generated", "case": case_id, "category": "production", "gold": gold,
                 "observed": obs["observed"], "outcome": R.accept_outcome(gold, obs["observed"]),
                 "note": obs["reason"]})

out = R.HERE / "results" / f"stage3_adversarial_{label}.json"
out.write_text(json.dumps(rows, indent=1))
for r in rows:
    print(f"{r['kind']:9} {r['outcome']:24} {r['observed']:12} {r['case']:48} {r['note'][:90]}")
print(dict(sorted(collections.Counter((r["kind"], r["outcome"]) for r in rows).items())))
