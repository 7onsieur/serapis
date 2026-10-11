"""Stage 2 adversarial runner (offline). Reference/text cases go through ``tutor_policy.reference_unsupported``
(the validator, cited text supplied, so retrieval is not involved) and, separately, the relation layer alone.
Generated-question cases go through the production next_question path (retrieval + validators).

    python3 evals/diagnostic_slice0/run_adversarial_stage2.py [label]   # writes results/stage2_adversarial_<label>.json

Outcomes are tracked separately: FALSE_ACCEPT / FALSE_REJECT / TRUE_* and INCONCLUSIVE (relation layer abstained).
"""

from __future__ import annotations

import collections
import json
import sys

import adversarial_stage2 as A
import run_eval as R
from university_jarvis import tutor_policy as tp

try:
    from university_jarvis import relations
except ImportError:  # the pre-Stage-2 tree has no relation layer
    relations = None

label = sys.argv[1] if len(sys.argv) > 1 else "current"
rows = []
for case_id, category, text, pages, gold in A.CASES:
    verdicts = [f.verdict for f in relations.check_relations(text, pages)] if relations else []
    layer = ("CONTRADICTED" if "CONTRADICTED" in verdicts else "SUPPORTED" if "SUPPORTED" in verdicts
             else "UNDETERMINED")
    rejected_by_relation = layer == "CONTRADICTED"
    rejected = tp.reference_unsupported(text, pages) is not None
    if gold == "INCONCLUSIVE":
        # Fail-safe: the relation layer must not reject, and must not claim the text is supported.
        outcome = "INCONCLUSIVE_OK" if layer == "UNDETERMINED" else (
            "FALSE_REJECT" if rejected_by_relation else "UNSAFE_SUPPORT_CLAIM")
    else:
        # The relation layer decides REJECT cases; ACCEPT cases are judged on the relation layer too, because the
        # other lexical rules are frozen Stage 1 behaviour and are reported separately as "rejected_any".
        outcome = {("REJECT", True): "TRUE_REJECT", ("REJECT", False): "FALSE_ACCEPT",
                   ("ACCEPT", False): "TRUE_ACCEPT", ("ACCEPT", True): "FALSE_REJECT"}[(gold, rejected_by_relation)]
    rows.append({"kind": "text", "case": case_id, "category": category, "gold": gold, "relation_layer": layer,
                 "rejected_by_relation": rejected_by_relation, "rejected_any_validator": rejected, "outcome": outcome})
for case_id, subject, question, expected, cites, gold in A.GENERATED:
    obs = R.run_next(subject, question, expected, cites)
    rows.append({"kind": "generated", "case": case_id, "gold": gold, "observed": obs["observed"],
                 "outcome": R.accept_outcome(gold, obs["observed"]), "note": obs["reason"]})
out = R.HERE / "results" / f"stage2_adversarial_{label}.json"
out.write_text(json.dumps(rows, indent=1))
for r in rows:
    print(f"{r['kind']:9} {r['outcome']:22} {r.get('relation_layer',''):13} {r['case']}  {r.get('note','')[:60]}")
print(dict(collections.Counter((r["kind"], r["outcome"]) for r in rows)))
