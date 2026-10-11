"""Deterministic, offline foundations for adaptive tutoring (Phase 3C, slice 1).

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
* evidence classification-- revealed / assisted / unaided-but-unlinked (no transfer or retention
                            claims until verified question lineage exists)
"""

from __future__ import annotations

import re
from typing import Any, Iterable

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

def novelty_check(candidate: str, shown: Iterable[str]) -> dict[str, Any]:
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
    rewording = worst["overlap"] >= NOVELTY_CONTAINMENT_LIMIT or worst["jaccard"] >= NOVELTY_JACCARD_LIMIT
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


# --- evidence classification --------------------------------------------------------

def classify_evidence(attempt: dict[str, Any]) -> str:
    """Conservative, derived label for one attempt; never stored, so it can never become mastery.

    REVEALED         -- the attempt followed the answer being shown.
    ASSISTED         -- the attempt followed a hint, explanation or feedback on that very task.
    UNAIDED_UNLINKED -- no help was recorded on this task. Whether the *concept* was taught or
                        tested earlier is unknown: attempts carry no verified concept or question
                        lineage yet, and capability + week + elapsed time is not evidence of one.

    Deliberately there is no "transfer" or "retention" label. Slice 2 may add them once an
    attempt records a verified relationship to an earlier question; they must be derived from
    that lineage, never from a time gap alone.
    """
    status = attempt.get("assistance_status")
    if status == "REVEALED":
        return "REVEALED"
    if status == "UNAIDED":
        return "UNAIDED_UNLINKED"
    return "ASSISTED"
