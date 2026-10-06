from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from university_jarvis.state import StateError, _validate_state, load_state, normalize_academic_truth


ROOT = Path(__file__).resolve().parents[1]


class AcademicTruthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_state(ROOT / "data" / "academic-state.json")

    def test_legacy_value_is_unverified_and_normalization_does_not_mutate_input(self) -> None:
        legacy = copy.deepcopy(self.state)
        legacy.pop("academic_truth_schema_version")
        legacy["modules"][0].pop("fact_provenance")
        assessment = legacy["modules"][0]["assessments"][1]
        assessment.pop("fact_provenance")
        before = copy.deepcopy(legacy)

        normalized = normalize_academic_truth(legacy)

        self.assertEqual(legacy, before)
        self.assertEqual(
            normalized["modules"][0]["assessments"][1]["fact_provenance"]["deadline"]["status"],
            "NEEDS_VERIFICATION",
        )
        self.assertEqual(
            normalized["modules"][0]["assessments"][0]["fact_provenance"]["deadline"]["status"],
            "UNKNOWN",
        )

    def test_load_legacy_state_never_writes_normalized_metadata(self) -> None:
        legacy = copy.deepcopy(self.state)
        legacy.pop("academic_truth_schema_version")
        legacy["modules"][0]["assessments"][1].pop("fact_provenance")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            original = json.dumps(legacy)
            path.write_text(original, encoding="utf-8")
            loaded = load_state(path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(
                loaded["modules"][0]["assessments"][1]["fact_provenance"]["deadline"]["status"],
                "NEEDS_VERIFICATION",
            )

    def test_confirmed_fact_requires_existing_non_derived_evidence(self) -> None:
        bad = copy.deepcopy(self.state)
        bad["modules"][0]["assessments"][1]["fact_provenance"]["deadline"]["evidence"] = []
        with self.assertRaisesRegex(StateError, "requires university or explicitly reconciled LMS evidence"):
            _validate_state(bad)

        derived = copy.deepcopy(self.state)
        source_id = "syn101-fictional-assessment-brief"
        source = next(source for source in derived["sources"] if source["id"] == source_id)
        source["source_class"] = "DERIVED_STUDY_AID"
        with self.assertRaisesRegex(StateError, "requires university or explicitly reconciled LMS evidence"):
            _validate_state(derived)

    def test_invalid_status_source_class_and_scope_are_rejected(self) -> None:
        bad_status = copy.deepcopy(self.state)
        bad_status["modules"][0]["assessments"][1]["fact_provenance"]["deadline"]["status"] = "LIKELY"
        with self.assertRaisesRegex(StateError, "Invalid trust status"):
            _validate_state(bad_status)

        bad_source = copy.deepcopy(self.state)
        bad_source["sources"][0]["source_class"] = "AUTOMATICALLY_TRUSTED"
        with self.assertRaisesRegex(StateError, "Invalid source_class"):
            _validate_state(bad_source)

        bad_scope = copy.deepcopy(self.state)
        bad_scope["sources"][-1]["module_code"] = "SYN999"
        with self.assertRaisesRegex(StateError, "another module|unknown module"):
            _validate_state(bad_scope)

    def test_duplicate_assessment_ids_and_unknown_evidence_are_rejected(self) -> None:
        duplicate = copy.deepcopy(self.state)
        duplicate["modules"][0]["assessments"][1]["id"] = duplicate["modules"][0]["assessments"][0]["id"]
        with self.assertRaisesRegex(StateError, "Assessment IDs must be unique"):
            _validate_state(duplicate)

        missing = copy.deepcopy(self.state)
        missing["modules"][0]["assessments"][1]["fact_provenance"]["deadline"]["evidence"][0]["source_id"] = "absent"
        with self.assertRaisesRegex(StateError, "Unknown evidence source"):
            _validate_state(missing)


if __name__ == "__main__":
    unittest.main()
