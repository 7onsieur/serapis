"""Deterministic, offline foundations for adaptive tutoring (Phase 3C, slices 1-2).

Pure functions only: no provider, no file or network access. The model proposes;
these rules check what it proposed and decide the next suggestion. Nothing here
claims mastery -- every result is a provisional, task-level reading.

* hedge detection        -- "I don't know" is not a wrong answer
* misconception checks   -- a suspected misconception needs a literal quote, a valid
                            citation and a confidence level, or it is dropped
* answer-leak check      -- feedback, hints and explanations must not reproduce the
                            stored reference answer / private rubric
* question novelty       -- is a candidate question new, or a rewording of one already shown?
* next-action policy     -- one suggested next step, from the diagnosis alone
* sequence planning      -- slice 2: which step (follow-up, different question, or stop) may come next
* generated-question check-- slice 2: a model-written follow-up must be cited, supported, related,
                            novel and must not leak any answer, or it is never shown
* evidence classification-- revealed / assisted / unaided first contact / new question after help.
                            Nothing here claims retention or mastery: a same-session question is
                            only ever "a new question after help"
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from .retrieval import tokenize

SELF_CONFIDENCE = ("SURE", "UNSURE", "GUESSING")
MISCONCEPTION_CONFIDENCE = ("low", "medium", "high")
ACTIONABLE_CONFIDENCE = ("medium", "high")
MAX_LABEL_CHARS = 160
MAX_QUOTE_CHARS = 300

# Novelty: a candidate that reuses this much of something already shown is a rewording.
NOVELTY_CONTAINMENT_LIMIT = 0.8
NOVELTY_JACCARD_LIMIT = 0.6
# Leak: this many consecutive words of the reference answer, not said by the student.
LEAK_WINDOW = 6
LEAK_MIN_WORDS = 4
LEAK_SUBSTRING_CHARS = 25

_WORDS = re.compile(r"[a-z0-9]+")
_HEDGES = (
    "i don't know", "i dont know", "i do not know", "dont know", "don't know", "idk", "dunno",
    "no idea", "no clue", "not sure", "unsure", "i guess", "just guessing", "guessing", "guess",
    "maybe", "perhaps", "i think", "i'm not certain", "not certain", "can't remember",
    "cant remember", "i forgot",
)
_HEDGE_PATTERN = re.compile(
    "|".join(r"\b" + re.escape(h).replace(r"\ ", r"\s+") + r"\b" for h in sorted(_HEDGES, key=len, reverse=True)),
    re.IGNORECASE,
)


def words(text: str | None) -> list[str]:
    return _WORDS.findall((text or "").lower().replace("’", "'").replace("'", ""))


def normalise(text: str | None) -> str:
    return " ".join(words(text))


# --- hedge / uncertainty -------------------------------------------------------

def detect_hedge(text: str | None) -> dict[str, bool]:
    """``hedged``: the reply signals uncertainty. ``non_answer``: nothing is left once it is removed.

    "I think cells are the basic unit" is hedged but still an answer; "idk" is both.
    Anything with a content word left over is sent on as an answer, however short.
    """
    raw = (text or "").lower().replace("’", "'")
    hedged = bool(_HEDGE_PATTERN.search(raw))
    remainder = _HEDGE_PATTERN.sub(" ", raw)
    non_answer = (hedged and not tokenize(remainder)) or not _WORDS.search(raw)
    return {"hedged": hedged, "non_answer": non_answer}


# --- misconception validation ---------------------------------------------------

def _contains_run(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    return n > 0 and any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


def validate_misconception(raw: Any, student_response: str, diagnosis: str, *,
                           citations_ok: Any, reference_answer: str | None = None,
                           allowed_text: Iterable[str] = ()) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(clean_misconception, None)`` or ``(None, reason_it_was_dropped)``.

    A misconception is kept only when the diagnosis is "misconception", the quote is
    literally in the student's reply, it cites supplied sources (``citations_ok`` is a
    callable that raises on bad citations), the confidence is stated and at least
    medium, and the label does not leak the reference answer.
    """
    if diagnosis != "misconception":
        return None, None if raw is None else "misconception given for a different diagnosis"
    if not isinstance(raw, dict) or set(raw) != {"label", "quote", "confidence", "citations"}:
        return None, "no structured misconception supplied"
    label, quote, confidence, citations = raw["label"], raw["quote"], raw["confidence"], raw["citations"]
    if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL_CHARS:
        return None, "misconception label is empty or too long"
    if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_QUOTE_CHARS:
        return None, "misconception quote is empty or too long"
    quote_words = words(quote)
    if not quote_words or (len(quote_words) < 2 and len(quote_words[0]) < 4):
        return None, "misconception quote is too short to identify"
    if not _contains_run(words(student_response), quote_words):
        return None, "misconception quote is not in the student's response"
    if confidence not in MISCONCEPTION_CONFIDENCE:
        return None, "misconception confidence is not stated"
    if confidence not in ACTIONABLE_CONFIDENCE:
        return None, "misconception confidence is low"
    if not isinstance(citations, list) or not citations or not all(
        isinstance(c, dict) and set(c) == {"source_id", "pdf_page"} for c in citations
    ):
        return None, "misconception has no source citation"
    try:
        citations_ok(citations)
    except Exception:  # noqa: BLE001 - any citation failure means "not supported by the sources"
        return None, "misconception citation is not a supplied source passage"
    if reveals_reference(label, reference_answer, allowed_text=[student_response, *allowed_text]):
        return None, "misconception label would reveal the reference answer"
    return {"label": label.strip(), "quote": quote.strip(), "confidence": confidence,
            "citations": [dict(c) for c in citations]}, None


# --- answer leak ------------------------------------------------------------------

def reveals_reference(message: str | None, reference: str | None, *, allowed_text: Iterable[str] = ()) -> bool:
    """True when ``message`` reproduces the stored reference answer / rubric.

    Two tests: the whole normalised reference (25+ characters) appearing inside the
    message, or a run of 6 consecutive reference words (the whole reference if it has
    4-5) that the student or the question did not already say. Echoing the student's
    own words is not a leak. References under 4 words cannot be tested this way.
    """
    ref_words, msg_words = words(reference), words(message)
    if not ref_words or not msg_words:
        return False
    ref_text, msg_text = " ".join(ref_words), " ".join(msg_words)
    allowed = [words(a) for a in allowed_text if a]
    if len(ref_text) >= LEAK_SUBSTRING_CHARS and ref_text in msg_text:
        return not any(_contains_run(a, ref_words) for a in allowed)
    if len(ref_words) < LEAK_MIN_WORDS:
        return False
    window = min(LEAK_WINDOW, len(ref_words))
    for i in range(len(ref_words) - window + 1):
        run = ref_words[i:i + window]
        if _contains_run(msg_words, run) and not any(_contains_run(a, run) for a in allowed):
            return True
    return False


# --- question novelty ----------------------------------------------------------------

def novelty_check(candidate: str, shown: Iterable[str], *, overlap_limit: float = NOVELTY_CONTAINMENT_LIMIT,
                  jaccard_limit: float = NOVELTY_JACCARD_LIMIT) -> dict[str, Any]:
    """Is ``candidate`` a new question, or a rewording of something already shown?

    Compares stemmed content words against every text already shown (earlier questions,
    revealed answers, explanations, hints). Lexical only: it catches rewording, it cannot
    prove a question tests deeper transfer. Rejection-biased on purpose.
    """
    cand = set(tokenize(candidate))
    worst = {"overlap": 0.0, "jaccard": 0.0, "index": None}
    for index, text in enumerate(shown):
        other = set(tokenize(text))
        if not cand or not other:
            continue
        common = len(cand & other)
        overlap, jaccard = common / len(cand), common / len(cand | other)
        if max(overlap, jaccard) > max(worst["overlap"], worst["jaccard"]):
            worst = {"overlap": round(overlap, 3), "jaccard": round(jaccard, 3), "index": index}
    if not cand:
        return {"novel": False, "reason": "no content words", **worst}
    rewording = worst["overlap"] >= overlap_limit or worst["jaccard"] >= jaccard_limit
    return {"novel": not rewording, "reason": "rewording of an earlier text" if rewording else "ok", **worst}


# --- next-action policy -------------------------------------------------------------

def next_action(*, diagnosis: str, hedged: bool = False, non_answer: bool = False,
                misconception: bool = False, self_confidence: str | None = None,
                assistance_status: str = "UNAIDED", hints_left: bool = True,
                answer_revealed: bool = False, consecutive_unclear: int = 0) -> str:
    """One suggested next step. Advice shown to the student; it never gates anything.

    Self-reported confidence only shifts the *advice* (e.g. a guess that happened to be
    right is not consolidated); it is never an input to the diagnosis.
    """
    if non_answer or (hedged and diagnosis == "unclear"):
        return "OFFER_HINT" if hints_left and not answer_revealed else "OFFER_REVEAL_OR_END"
    if diagnosis == "unclear":
        return "OFFER_HINT_OR_END" if consecutive_unclear >= 1 else "CLARIFY"
    if diagnosis == "off_target":
        return "RESTATE"
    if diagnosis == "misconception":
        return "REVIEW_SOURCE" if misconception else "CLARIFY"
    if diagnosis == "partial":
        return "FOLLOW_UP" if hints_left and not answer_revealed else "REVIEW_SOURCE"
    if diagnosis == "correct":
        if self_confidence == "GUESSING" or hedged:
            return "CHECK_REASONING"
        if assistance_status != "UNAIDED" or answer_revealed:
            return "UNAIDED_RETEST_LATER"
        return "CONSOLIDATE"
    return "CLARIFY"


# --- sequence planning (slice 2) ------------------------------------------------------

MAX_QUESTIONS = 3          # initial + at most one follow-up + at most one different (transfer) question
MIN_CALLS_FOR_NEXT = 2     # generating a question and then judging an answer to it
MAX_SKIPS = 2
QUESTION_ROLES = ("INITIAL", "FOLLOW_UP", "TRANSFER")

# Fixed, student-facing wording for every reason code. Nothing here is generated by the model.
STEP_REASONS = {
    "PARTIAL_ANSWER": "Your answer covered part of it, so this follow-up targets the part that was missing.",
    "MISCONCEPTION": "Your answer may rest on a misunderstanding (a provisional reading), so this follow-up asks about the point it touches.",
    "OFF_TARGET": "Your answer did not address the question, so this follow-up approaches the same idea from a narrower angle.",
    "REASONING_CHECK": "Your answer looked right but you were unsure, so this follow-up checks the reasoning behind it.",
    "ANSWER_WAS_SHOWN": "The answer was shown, so this is a new question on the same idea. It is recorded as coming after help.",
    "FRESH_ANGLE_AFTER_SKIP": "You skipped the last question, so this is a fresh question on the same idea.",
    "CORRECT_ANSWER": "Your answer looked correct, so this is a different question on the same idea, to see whether it carries over today.",
    "FOLLOW_UP_CORRECT": "Your follow-up answer looked correct, so this is a different question on the same idea.",
    "AWAITING_ANSWER": "Answer, ask for help, skip or reveal this question first.",
    "NEEDS_CLARITY": "Your last answer could not be judged. Say more, ask for a hint, skip or end -- no new question yet.",
    "SEQUENCE_COMPLETE": "That was the last question planned for this session.",
    "QUESTION_LIMIT": "This session has reached its limit of questions.",
    "CALL_BUDGET": "This session is close to its AI-call limit, so no new question can be built.",
    "REPEATED_SKIPS": "You skipped more than one question, so the session suggests stopping here.",
    "NO_PROGRESS": "Two answers in a row could not be judged. Re-read the sources and come back later rather than going on.",
    "GENERATION_FAILED": "A new question could not be built that passed the safety checks, so none will be invented.",
    "REPEATED_MISCONCEPTION": "The same possible misunderstanding came up twice. Re-read the cited passage before more questions.",
    "REVIEW_SOURCES": "The follow-up did not look secure yet. Re-read the sources and come back later.",
}


def plan_next(*, role: str, asked: int, settled: bool, skipped: bool = False, revealed: bool = False,
              diagnosis: str | None = None, hedged: bool = False, non_answer: bool = False,
              self_confidence: str | None = None, skips_total: int = 0, unclear_streak: int = 0,
              repeated_misconception: bool = False, calls_left: int = 0,
              generation_failures: int = 0, max_questions: int = MAX_QUESTIONS) -> dict[str, str]:
    """The one step the session may move to next: FOLLOW_UP, TRANSFER, NONE (not yet) or END.

    Pure and deterministic; the model has no say. ``settled`` means the current question was
    answered (and judged), skipped or revealed. The student may still decline any step or end.
    """
    def out(step: str, reason: str) -> dict[str, str]:
        return {"step": step, "reason": reason}

    if not settled:
        return out("NONE", "AWAITING_ANSWER")
    if generation_failures:
        return out("END", "GENERATION_FAILED")
    if role == "TRANSFER":
        return out("END", "SEQUENCE_COMPLETE")
    if asked >= max_questions:
        return out("END", "QUESTION_LIMIT")
    if skips_total >= MAX_SKIPS:
        return out("END", "REPEATED_SKIPS")
    if unclear_streak >= 2:
        return out("END", "NO_PROGRESS")
    if repeated_misconception:
        return out("END", "REPEATED_MISCONCEPTION")
    if calls_left < MIN_CALLS_FOR_NEXT:
        return out("END", "CALL_BUDGET")
    if skipped:
        return out("FOLLOW_UP" if role == "INITIAL" else "END", "FRESH_ANGLE_AFTER_SKIP" if role == "INITIAL" else "REVIEW_SOURCES")
    if revealed:
        return out("FOLLOW_UP" if role == "INITIAL" else "END", "ANSWER_WAS_SHOWN" if role == "INITIAL" else "REVIEW_SOURCES")
    if non_answer or diagnosis in (None, "unclear"):
        return out("NONE", "NEEDS_CLARITY")
    secure = diagnosis == "correct" and not hedged and self_confidence != "GUESSING"
    if role == "FOLLOW_UP":
        return out("TRANSFER", "FOLLOW_UP_CORRECT") if secure else out("END", "REVIEW_SOURCES")
    if secure:
        return out("TRANSFER", "CORRECT_ANSWER")
    return out("FOLLOW_UP", {"correct": "REASONING_CHECK", "partial": "PARTIAL_ANSWER",
                             "misconception": "MISCONCEPTION"}.get(diagnosis, "OFF_TARGET"))


# --- generated questions (slice 2) -----------------------------------------------------

MAX_QUESTION_CHARS = 400
MAX_EXPECTED_CHARS = 600
MIN_QUESTION_CHARS = 15
SUPPORT_MIN = 0.6           # share of the expected answer's content words found in the cited passages
CONCEPT_OVERLAP_MIN = 2     # content words shared with the original concept
ANSWER_SAME_JACCARD = 0.8
TRANSFER_OVERLAP_LIMIT = 0.7
TRANSFER_JACCARD_LIMIT = 0.5
NEW_WORDS_MIN = {"FOLLOW_UP": 1, "TRANSFER": 2}


def validate_question(raw: Any, *, step: str, citations_ok: Callable[[list[dict[str, Any]]], None],
                      cited_text: Callable[[list[dict[str, Any]]], str], shown: Iterable[str],
                      prior_questions: Iterable[str], prior_answers: Iterable[str],
                      unrevealed_answers: Iterable[str], concept_text: str,
                      ) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(clean_question, None)`` or ``(None, reason_it_was_rejected)``.

    A generated question is shown only when it is structured, cited to supplied passages that
    support its own expected answer, tied to the original concept, new rather than a rewording
    (stricter for a different/transfer question), and reproduces no reference answer that is
    still private. Lexical checks only: they reject rewordings and leaks, they do not prove depth.
    """
    if step not in NEW_WORDS_MIN:
        return None, "unknown question step"
    if not isinstance(raw, dict) or set(raw) != {"question", "expected_answer", "citations"}:
        return None, "question does not match the required structure"
    question, expected, citations = raw["question"], raw["expected_answer"], raw["citations"]
    if not isinstance(question, str) or not MIN_QUESTION_CHARS <= len(question.strip()) <= MAX_QUESTION_CHARS:
        return None, "question is empty, too short or too long"
    if not isinstance(expected, str) or not expected.strip() or len(expected) > MAX_EXPECTED_CHARS:
        return None, "expected answer is missing or too long"
    if not isinstance(citations, list) or not citations or not all(
        isinstance(c, dict) and set(c) == {"source_id", "pdf_page"} and isinstance(c["pdf_page"], int)
        and not isinstance(c["pdf_page"], bool) for c in citations
    ):
        return None, "question has no page-level source citation"
    try:
        citations_ok(citations)
    except Exception:  # noqa: BLE001 - any citation failure means "not a supplied source passage"
        return None, "question citation is not a supplied source passage"
    question, expected = question.strip(), expected.strip()
    if reveals_reference(question, expected):
        return None, "question gives away its own answer"
    expected_stems, passage_stems = set(tokenize(expected)), set(tokenize(cited_text(citations)))
    if len(expected_stems) < 2 or not passage_stems:
        return None, "expected answer is too thin to check against the sources"
    support = len(expected_stems & passage_stems) / len(expected_stems)
    if support < SUPPORT_MIN:
        return None, "expected answer is not supported by the cited passages"
    # Support must come from what the answer adds beyond the question's own words, and every
    # cited page must carry some of it: a decoy citation cannot borrow another page's support.
    answer_words = expected_stems - set(tokenize(question))
    if len(answer_words) < 2:
        return None, "expected answer adds nothing beyond the question"
    if len(answer_words & passage_stems) / len(answer_words) < SUPPORT_MIN:
        return None, "expected answer is not supported by the cited passages"
    if any(not (answer_words & set(tokenize(cited_text([c])))) for c in citations):
        return None, "a cited passage does not support the expected answer"
    own = set(tokenize(question)) | expected_stems
    concept_overlap = len(own & set(tokenize(concept_text)))
    if concept_overlap < CONCEPT_OVERLAP_MIN:
        return None, "question is not tied to the original concept"
    prior_questions, prior_answers = list(prior_questions), list(prior_answers)
    for private in unrevealed_answers:
        if reveals_reference(question, private, allowed_text=prior_questions):
            return None, "question would reveal an earlier reference answer"
    limits = ({"overlap_limit": TRANSFER_OVERLAP_LIMIT, "jaccard_limit": TRANSFER_JACCARD_LIMIT}
              if step == "TRANSFER" else {})
    novelty = novelty_check(question, [*shown, *prior_questions], **limits)
    if not novelty["novel"]:
        return None, "question is a rewording of something already shown"
    for earlier in prior_answers:
        if normalise(expected) == normalise(earlier) or novelty_check(expected, [earlier])["jaccard"] >= ANSWER_SAME_JACCARD:
            return None, "question has the same answer as an earlier question"
    seen = set().union(*(set(tokenize(t)) for t in [*prior_questions, *prior_answers])) if prior_questions or prior_answers else set()
    new_words = len(set(tokenize(question)) - seen)
    if new_words < NEW_WORDS_MIN[step]:
        return None, "question adds nothing new to what was already asked"
    return {"question": question, "expected_answer": expected, "citations": [dict(c) for c in citations],
            "checks": {"support": round(support, 3), "concept_overlap": concept_overlap,
                       "novelty_overlap": novelty["overlap"], "novelty_jaccard": novelty["jaccard"],
                       "new_words": new_words}}, None


def answer_support(expected: str | None, passage_text: str) -> float:
    """Share of the reference answer's content words found in the passages it is judged against."""
    stems = set(tokenize(expected or ""))
    return len(stems & set(tokenize(passage_text))) / len(stems) if stems else 0.0


# --- evidence classification --------------------------------------------------------

def classify_evidence(attempt: dict[str, Any]) -> str:
    """Conservative, derived label for one attempt; never stored, so it can never become mastery.

    REVEALED              -- the attempt followed the answer being shown.
    ASSISTED              -- the attempt followed a hint, explanation or feedback on that very task.
    UNAIDED_FIRST_CONTACT -- the session's opening question, answered with no recorded help on it
                             AND with no help or exposure recorded elsewhere in the week at the time
                             (``lineage.earlier_help_elsewhere`` is exactly False). Whether another
                             task covers the same concept is unknowable, so any other recorded help,
                             or a missing flag, keeps the label conservative.
    NEW_QUESTION_AFTER_HELP -- a later question in the same session (follow-up or different
                             question), answered with no help on *it*, after help on an earlier
                             linked question. Immediate, same-session performance only.
    UNAIDED_UNLINKED      -- no help recorded on this task, and no question lineage (older attempts).

    Deliberately there is no "transfer", "retention" or "mastery" label: a same-session question
    shows what the student could do just after help, not what they will remember or can do alone.
    """
    status = attempt.get("assistance_status")
    if status == "REVEALED":
        return "REVEALED"
    if status != "UNAIDED":
        return "ASSISTED"
    lineage = attempt.get("lineage")
    if not isinstance(lineage, dict):
        return "UNAIDED_UNLINKED"
    if lineage.get("role") == "INITIAL":
        return "UNAIDED_FIRST_CONTACT" if lineage.get("earlier_help_elsewhere") is False else "UNAIDED_UNLINKED"
    return "NEW_QUESTION_AFTER_HELP" if lineage.get("prior_help") else "UNAIDED_UNLINKED"
