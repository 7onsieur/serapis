"""Tutor feedback without answer leakage: regression on the four live rejections, partial understanding,
misconceptions, adversarial replies, and no internal ids in anything a student reads. Offline only."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_tutoring as base  # noqa: E402
from test_tutoring_diagnosis import CITE, WRONG, mis, reply  # noqa: E402

from university_jarvis import tutoring  # noqa: E402
from university_jarvis.tutor_policy import reveals_reference  # noqa: E402

# The fictional reference answers and tutor replies below are copied from the recorded live run
# (evals/learning_workflow_v1/results/live_gpt-5.6-luna_learning): the four replies the leak check refused.
Q5 = "What are stakeholders, and how are they distinguished from primary and secondary stakeholders?"
R5 = ("Stakeholders are people or groups that affect or are affected by an organisation’s actions. Primary "
      "stakeholders have a direct financial or operational relationship with the organisation, while secondary "
      "stakeholders are affected indirectly but may still influence its reputation.")
STUDENT = "A stakeholder map is a weather forecast used by meteorologists."
LIVE_REFUSED = [
    "Your response is off topic: a stakeholder map is not described as a weather forecast in the supplied material. "
    "Stakeholders are people or groups who affect or are affected by what an organisation does. To distinguish the "
    "two types, ask yourself: which stakeholders have a direct financial or operational relationship, and which are "
    "affected indirectly but can still influence reputation? What would your answer be?",
    "Your response is off topic and does not address stakeholders or the distinction between primary and secondary "
    "stakeholders. Try again: define a stakeholder, then explain how a direct financial or operational relationship "
    "differs from being affected indirectly while still influencing reputation. What would your answer be?",
    "Your response is off topic and does not address the question about stakeholders. Try again by defining a "
    "stakeholder, then explaining the difference between a direct financial or operational relationship and an "
    "indirect effect on the organisation’s reputation.",
    "Your response is off target: it describes a weather forecast rather than distinguishing the two stakeholder "
    "types. Primary stakeholders have a direct financial or operational relationship with the organisation; "
    "secondary stakeholders are affected indirectly but may still influence its reputation. What is the key "
    "difference in how primary and secondary stakeholders relate to the organisation?",
]
GOOD = [
    "That does not answer the question yet: it asks what stakeholders are and how primary and secondary "
    "stakeholders are distinguished, and your answer is about something else. Re-read the second slide of the "
    "week 1 deck, then try again in your own words. What would you say a stakeholder is?",
    "You have named the right kind of thing (a group connected to the organisation) but not yet said how the "
    "question's two types differ. Look at page 2 and compare the two, then have another go.",
    "Check the wording you used against page 1 of the slides: where does the slide use that term? Then try the "
    "question again and tell me what you find.",
]


class LeakRegressionTests(unittest.TestCase):
    def leaks(self, message, student=STUDENT):
        return reveals_reference(message, R5, allowed_text=[Q5, student])

    def test_each_reply_the_live_run_refused_was_a_real_restatement_not_a_false_positive(self):
        """The validator was right four times out of four; the cause was the model's behaviour and our prompt."""
        for message in LIVE_REFUSED:
            with self.subTest(message=message[:50]):
                self.assertTrue(self.leaks(message))

    def test_replies_that_follow_the_new_guidance_are_not_blocked(self):
        for message in GOOD:
            with self.subTest(message=message[:50]):
                self.assertFalse(self.leaks(message))

    def test_a_reply_may_reuse_the_questions_own_words_and_the_students_own_words(self):
        self.assertFalse(self.leaks("The question asks how primary and secondary stakeholders are distinguished; "
                                    "your answer, a weather forecast, does not address that. Try again."))
        self.assertFalse(self.leaks(f'You wrote "{STUDENT}". Compare that with page 1 and try again.'))

    def test_adversarial_restatements_are_still_blocked(self):
        attempts = {
            "verbatim": R5,
            "lower case, no punctuation": R5.lower().replace(",", "").replace(".", ""),
            "wrapped in encouragement": f"Good try! Remember: {R5} Does that help?",
            "options that are the answer": "Is it that primary stakeholders have a direct financial or operational "
                                           "relationship with the organisation, or the other way round?",
            "split into two sentences": "Primary stakeholders have a direct financial or operational relationship. "
                                        "With the organisation, while secondary stakeholders are affected indirectly.",
            "as a hint": "Hint: secondary stakeholders are affected indirectly but may still influence its reputation.",
        }
        for name, message in attempts.items():
            with self.subTest(name):
                self.assertTrue(self.leaks(message))


class TutorBehaviourTests(unittest.TestCase):
    setUp = base.TutoringTests.setUp
    _context = base.TutoringTests._context
    create = base.TutoringTests.create
    learning = base.TutoringTests.learning
    session_file = base.TutoringTests.session_file

    def submit(self, session, text=WRONG, turn="a1"):
        return tutoring.submit_response({}, "BIO101", 1, session["session_id"], client_turn_id=turn, text=text,
                                        provider=self.provider, workspace_root=self.root)

    def test_partial_understanding_is_recognised_and_another_attempt_encouraged(self):
        session = self.create()
        self.provider.override = reply("partial", message="You have the first part: cells matter as the basic "
                                                           "building blocks. The question also asks what they do; "
                                                           "re-read page 1 and try again.")
        done = self.submit(session, text="Cells are the basic building blocks")
        self.assertEqual(done["diagnosis"], "partial")
        self.assertEqual(self.learning()["evidence"][0]["evaluation"]["outcome"], "PARTLY_SUPPORTED")
        self.assertIn("try again", done["tutor"]["text"])
        self.assertIn("ANSWER", done["session"]["available_actions"])

    def test_a_misconception_is_named_with_the_students_words_and_the_page_to_check_never_the_answer(self):
        session = self.create()
        self.provider.override = reply(
            "misconception", message="Your answer treats viruses as the basic unit; compare that with page 1.",
            misconception=mis())
        done = self.submit(session)
        turn = next(t for t in done["session"]["turns"] if t["turn_id"] == done["turn_id"])
        self.assertEqual(turn["misconception"]["quote"], "viruses are the basic unit")
        self.assertNotIn(base.ANSWER_TEXT, json.dumps(done))

    def test_a_leaking_first_reply_costs_two_calls_and_the_student_sees_only_the_clean_one(self):
        session = self.create()
        replies = [reply("off_target", message=f"Off target. {base.ANSWER_TEXT}."),
                   reply("off_target", message="That does not answer the question. Re-read page 1 and try again.")]
        original = self.provider.generate_structured_output

        def go(context, instructions, output_format):
            self.provider.override = replies.pop(0)
            return original(context, instructions, output_format)
        with patch.object(self.provider, "generate_structured_output", side_effect=go):
            done = self.submit(session)
        self.assertEqual(done["tutor"]["text"], "That does not answer the question. Re-read page 1 and try again.")
        self.assertEqual(done["session"]["model_calls"], 2)
        stored = json.loads(self.session_file(session).read_text())
        self.assertNotIn(base.ANSWER_TEXT, json.dumps([t.get("text") for t in stored["turns"]]))

    def test_when_both_attempts_leak_the_fallback_points_to_the_cited_page_when_it_can(self):
        session = self.create()
        self.provider.override = reply("off_target", message=f"Off target. {base.ANSWER_TEXT}.")
        done = self.submit(session)
        self.assertTrue(done["tutor"]["text"].startswith(tutoring.FALLBACK_FEEDBACK))
        self.assertNotIn(base.ANSWER_TEXT, done["tutor"]["text"])
        self.assertEqual(done["diagnosis"], "unclear")

    def test_the_prompt_teaches_the_structure_and_forbids_describing_the_answer(self):
        text = tutoring.TUTOR_INSTRUCTIONS
        for fragment in ("What is right", "What is incomplete or mistaken", "name the belief",
                         "guiding question", "invite another", "does not\nanswer the question",
                         "Do not teach the answer", "Bad:", "never contain it, a paraphrase of it",
                         "previous_reply_refused_because", "Never state or hint at the content"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, text.replace("never state or hint", "Never state or hint"))
        self.assertEqual(tutoring.TUTOR_PROMPT_VERSION, "tutor-turn-v3")

    def test_the_refusal_note_never_repeats_the_refused_reply_or_the_private_answer(self):
        note = tutoring._refusal_note(Exception("Tutor reply would reveal the reference answer"))
        self.assertNotIn("Cells", note)
        self.assertIn("private reference answer", note)


class NoInternalIdsTests(unittest.TestCase):
    CONTEXT = {"sources": [{"id": "src-0123456789abcdef0123456789abcdef", "title": "week1-w1.pptx"}],
               "source_contexts": [{"source_id": "src-0123456789abcdef0123456789abcdef",
                                    "excerpts": [{"pdf_page": 2, "text": "Stakeholders affect organisations."}]}]}
    ID = "src-0123456789abcdef0123456789abcdef"

    def checked(self, label):
        raw = reply("misconception", message="Compare with the slide.",
                    misconception={"label": label, "quote": "viruses are the basic unit", "confidence": "high",
                                   "citations": [{"source_id": self.ID, "pdf_page": 2}]},
                    citations=[{"source_id": self.ID, "pdf_page": 2}])
        task = {"task": "What is the basic unit of life?", "expected_answer": base.ANSWER_TEXT}
        return tutoring._check_reply(raw, action="FEEDBACK", task=task, context=self.CONTEXT, response=WRONG,
                                     revealed=False)

    def test_misconception_notes_carry_the_file_name_not_the_internal_id(self):
        out = self.checked(f"Treats viruses as the basic unit (see {self.ID})")
        shown = out["misconception"]
        self.assertNotIn("src-", shown["label"] + shown["quote"])  # what the page prints; ids stay only as data
        self.assertEqual(out["misconception"]["citations"][0]["title"], "week1-w1.pptx")
        self.assertIn("week1-w1.pptx", out["misconception"]["label"])

    def test_the_tutor_page_template_never_prints_a_source_id(self):
        template = (Path(__file__).resolve().parents[1] / "src" / "university_jarvis" / "hub_templates" / "tutor.html").read_text()
        self.assertNotIn("c.source_id", template)
        self.assertIn("c.title", template)
