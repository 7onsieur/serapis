from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.mission import (
    build_objective_context,
    get_mission,
    has_reliable_cohort_information,
)
from university_jarvis.reasoning import OBJECTIVE_INSTRUCTIONS, build_reasoning_context
from university_jarvis.state import load_state


STATE_PATH = Path(__file__).resolve().parents[1] / "data" / "academic-state.json"


class MissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.state = load_state(STATE_PATH)

    def test_persistent_mission_loads_with_distinct_objectives(self) -> None:
        mission = get_mission(self.state)
        self.assertIn("Serapis helps learners", mission["statement"])
        self.assertEqual(
            mission["primary_objective"]["statement"],
            "Build understanding and make steady progress toward the learner's stated academic goals.",
        )
        self.assertEqual(
            mission["stretch_objective"]["statement"],
            "Use reliable evidence and available time to make thoughtful learning choices.",
        )
        self.assertNotEqual(
            mission["primary_objective"], mission["stretch_objective"]
        )
        self.assertTrue(mission["operating_principles"])
        self.assertTrue(mission["constraints"])

    def test_shared_reasoning_context_exposes_compact_objectives(self) -> None:
        objective_context = build_objective_context(self.state)
        context = {
            "workflow": "TEACH",
            "objective_context": objective_context,
            "module": {"code": "SYN101"},
            "assessments": [],
            "sources": [],
            "source_contexts": [],
        }

        supplied = build_reasoning_context(context)

        self.assertIs(supplied["objective_context"], objective_context)
        self.assertEqual(
            supplied["objective_context"]["primary_objective"],
            "Build understanding and make steady progress toward the learner's stated academic goals.",
        )
        self.assertNotIn("statement", supplied["objective_context"])

    def test_cohort_position_is_evidence_gated(self) -> None:
        self.assertFalse(has_reliable_cohort_information(self.state))
        self.assertFalse(
            build_objective_context(self.state)[
                "reliable_cohort_information_available"
            ]
        )

        unverified = copy.deepcopy(self.state)
        unverified["cohort_information"] = {
            "reliability": "unverified",
            "source": "student estimate",
            "current_position": 1,
        }
        self.assertFalse(has_reliable_cohort_information(unverified))

        reliable = copy.deepcopy(self.state)
        reliable["cohort_information"] = {
            "reliability": "reliable",
            "source": "verified university record",
        }
        self.assertTrue(has_reliable_cohort_information(reliable))
        self.assertIn("never claim or infer", OBJECTIVE_INSTRUCTIONS)

    def test_building_mission_context_has_no_provider_boundary(self) -> None:
        context = build_objective_context(self.state)
        self.assertEqual(context["version"], 1)
        self.assertEqual(
            set(context),
            {
                "version",
                "mission_fingerprint",
                "primary_objective",
                "stretch_objective",
                "operating_principles",
                "hard_constraints",
                "reliable_cohort_information_available",
            },
        )


if __name__ == "__main__":
    unittest.main()
