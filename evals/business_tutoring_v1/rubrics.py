"""Scoring rubrics for Business Tutoring Evaluation V1 (frozen before any run).

Each dimension is scored 0-3 by a live-model judge AND/OR a human reviewer, never by this offline harness.
Offline, every dimension below is reported as NOT YET EVALUATED. No score is produced or implied.

Anchors: 0 = unacceptable / harmful, 1 = weak, 2 = acceptable for an undergraduate, 3 = strong.
A "hard fail" overrides the dimension score and is reported separately.
"""

from __future__ import annotations

STATUS = "NOT YET EVALUATED"

RUBRICS: dict[str, dict] = {
    "CONCEPTUAL_TEACHING": {
        "assessor": "human reviewer (primary); live model judge only as a secondary, calibrated against human scores",
        "dimensions": {
            "accuracy": "Every claim in the explanation/feedback is correct with respect to the supplied pack and standard "
                        "undergraduate understanding. 0: a false claim; 1: vague or partly wrong; 2: correct; 3: correct and precise.",
            "grounding": "Claims are traceable to the supplied pages and cited to the right page. 0: unsupported claims; "
                         "1: cites but loosely; 2: grounded; 3: grounded with the key sentence identified.",
            "level": "Appropriate for a first/second-year business undergraduate. 0: wrong level; 1: jargon-heavy or condescending; "
                     "2: appropriate; 3: appropriate and adapts to the student's answer.",
            "feedback_usefulness": "The student learns what was right, what was missing and what to do next. 0: none; 1: generic "
                                   "praise/criticism; 2: names the gap; 3: names the gap and a concrete next step without giving the answer.",
        },
        "hard_fails": ["states a false fact as true", "reproduces the reference answer before the student has answered or asked to reveal"],
    },
    "MISCONCEPTION_DIAGNOSIS": {
        "assessor": "human reviewer (primary); live model judge secondary",
        "dimensions": {
            "diagnosis_accuracy": "The category (correct / partial / hedged / misconception / off-target) matches the frozen "
                                  "expected category. 0: opposite; 1: adjacent category; 2: exact for clear cases; 3: exact incl. borderline cases.",
            "no_false_accusation": "A correct or hedged-correct answer is never labelled a misconception. 0: accused; 3: not accused. "
                                   "(Binary in practice: 0 or 3.)",
            "misconception_precision": "The named misconception is the one the student actually holds, quoted from their words. "
                                       "0: wrong; 1: vague; 2: right; 3: right and linked to the source.",
            "corrective_guidance": "Guidance points to the relevant idea or passage without stating the reference answer. "
                                   "0: gives the answer or none; 1: generic; 2: targeted; 3: targeted and Socratic.",
        },
        "hard_fails": ["accuses a correct answer of a misconception", "reveals the reference answer in the corrective guidance"],
    },
    "CASE_STUDY_APPLICATION": {
        "assessor": "human reviewer (primary); live model judge secondary",
        "dimensions": {
            "framework_application": "The framework is applied to the facts of the scenario rather than recited. 0: recited only; "
                                     "1: partly applied; 2: applied; 3: applied with justified conclusion.",
            "reasoning_over_memory": "Feedback evaluates the student's reasoning chain, not only keyword matches. 0: keyword matching; "
                                     "1: mostly keywords; 2: reasoning-aware; 3: reasoning-aware and probes the chain.",
            "missing_steps": "Names the reasoning steps the student omitted (see each partial response's frozen missing_steps). "
                             "0: none; 1: some; 2: most; 3: all, in a sensible order.",
            "no_unsupported_claims": "Adds no business facts, numbers or outcomes that are absent from the pack. "
                                     "0: invented fact; 3: none. (Binary in practice.)",
        },
        "hard_fails": ["asserts a business fact, figure or outcome not in the supplied material"],
    },
    "ASSESSMENT_PREPARATION": {
        "assessor": "human reviewer (primary); live model judge secondary",
        "dimensions": {
            "relevance_answerability": "The question is on the concept and answerable from the pack. 0: off-concept or unanswerable; "
                                       "2: answerable; 3: answerable and exam-like.",
            "difficulty": "Difficulty is right for the student's last answer (easier/narrower after partial; transfer after correct). "
                          "0: mismatched; 2: reasonable; 3: well-calibrated.",
            "novelty": "A genuinely new question rather than a rewording. 0: rewording; 2: new angle; 3: new context requiring transfer.",
            "feedback_by_outcome": "Feedback differs appropriately after correct, partial and incorrect answers. 0: identical; "
                                   "2: differs; 3: differs and sets up the next step.",
            "adaptive_followup": "The follow-up responds to the specific gap. 0: unrelated; 2: related; 3: targets the gap exactly.",
        },
        "hard_fails": ["asks a question whose reference answer is not in the supplied material", "question text gives away its own answer"],
    },
}
