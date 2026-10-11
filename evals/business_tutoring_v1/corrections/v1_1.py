"""Versioned correction V1.1 to the frozen Business Tutoring Evaluation tasks. The V1.0 files are NOT edited.

AP-ACC2 `good_transfer` (V1.0) was an evaluation defect: its question ended "...differ from what the van could be sold for",
which is the closing clause of its own expected answer, so production rightly rejected it as giving away its answer
(see TRIAGE.md). V1.1 replaces only that candidate question; the task, reference, responses and the other five candidates
are unchanged. V1.0 results stay the historical record; V1.1 results are reported separately and labelled as such.

The V1.1 wording was written without running it. Whether production accepts it is an observation, not a guarantee.
"""

from __future__ import annotations

import copy

import tasks as T

VERSION = "1.1"
CHANGES = [{"task": "AP-ACC2", "candidate": "good_transfer", "defect": "question repeated the answer's closing clause"}]

_NEW = T.Q("good_transfer", "ACCEPT",
           "Calder Logistics expects to use a van for five years. After two years, must the van's carrying amount equal its resale price?",
           "No. The carrying amount is its cost less accumulated depreciation, which may differ from what the van could be sold for.", [2])


def apply(tasks: list[dict]) -> list[dict]:
    out = copy.deepcopy(tasks)
    task = next(t for t in out if t["id"] == "AP-ACC2")
    task["questions"] = [_NEW if q["kind"] == "good_transfer" else q for q in task["questions"]]
    task["version"] = VERSION
    return out
