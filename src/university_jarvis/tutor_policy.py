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
from decimal import Decimal
from typing import Any, Callable, Iterable

from .calculation import VERIFIED, narration_stems, verify_calculation
from .relations import relation_conflict
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
LEAK_STEM_MIN = 8      # a reordered or lightly reworded reference: this many content stems ...
LEAK_STEM_SHARE = 0.85  # ... of which this share appear together in the message

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
# Courtesy and disfluency words carry no answer content. They only matter after a hedge: "idk, sorry" is still
# a non-answer, while "sorry" on its own is left alone (no hedge, so it is sent on like any other short reply).
_COURTESY = re.compile(r"\b(?:sorry|sry|thanks|thank|thx|ty|please|pls|plz|lol|haha|hmm|hm|um|umm|uh|ok|okay)\b")


def detect_hedge(text: str | None) -> dict[str, bool]:
    """``hedged``: the reply signals uncertainty. ``non_answer``: nothing is left once it is removed.

    "I think cells are the basic unit" is hedged but still an answer; "idk" is both.
    Anything with a content word left over is sent on as an answer, however short.
    """
    raw = (text or "").lower().replace("’", "'")
    hedged = bool(_HEDGE_PATTERN.search(raw))
    remainder = _COURTESY.sub(" ", _HEDGE_PATTERN.sub(" ", raw)) if hedged else raw
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

_SMALL = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
          "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_NEGATORS = frozenset({"minus", "negative"})
# A number that follows one of these names a place in the material ("page 2"), not a value.
_LOCATORS = frozenset({"page", "pages", "p", "pp", "slide", "slides", "section", "chapter", "week", "figure", "fig",
                       "table", "step", "question", "q", "paragraph", "line", "lecture", "example", "part", "item"})
# Not followed by a letter: "2nd", "10x" and "3rd" are ordinals and labels, not the value 2, 10 or 3.
_NUMBER = re.compile(r"(?<![\w.])([-+\u2212])?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![a-z])")
_TOKENS = re.compile(r"[a-z]+|[^\sa-z]")
_GENERIC_SHORT = frozenset({"yes", "no", "true", "false", "correct", "incorrect", "none", "both", "all", "neither"})


def _number_words(tokens: list[str]) -> list[tuple[int, Decimal, bool]]:
    """(index, value, negative) for each run of English number words ("minus two", "one thousand").

    A lone "one" is not a number: it is far more often a pronoun ("one plus the rate").
    """
    found, i = [], 0
    while i < len(tokens):
        negative = tokens[i] in _NEGATORS
        j = i + 1 if negative else i
        total, current, used, start = Decimal(0), Decimal(0), 0, j
        while j < len(tokens) and (tokens[j] in _SMALL or tokens[j] in _TENS or tokens[j] in _SCALES):
            word = tokens[j]
            if word in _SMALL:
                current += _SMALL[word]
            elif word in _TENS:
                current += _TENS[word]
            elif word == "hundred":
                current = (current or 1) * 100
            else:
                total += (current or 1) * _SCALES[word]
                current = Decimal(0)
            used += 1
            j += 1
        if used and not (used == 1 and tokens[start] == "one" and not negative):
            found.append((i, total + current, negative))
            i = j
        else:
            i += 1
    return found


def numbers_in(text: str | None) -> list[tuple[Decimal, bool]]:
    """Numeric values stated in ``text`` as (signed value, is_locator): "-2", "minus two", "1,000", "one thousand".

    Digits and number words are folded to one value so wording does not hide a number. A leading sign is
    kept ("-2" is not "2"). A percent sign is ignored (50% and 50 are the same value; 50% and 0.5 are not
    folded together). Values after "page", "step" and the like are marked as locators.
    """
    lowered = (text or "").lower().replace("\u2212", "-")
    out: list[tuple[Decimal, bool]] = []
    for match in _NUMBER.finditer(lowered):
        sign, whole, fraction = match.groups()
        value = Decimal(whole.replace(",", "") + (fraction or ""))
        before = lowered[:match.start()].rstrip()
        previous = _WORDS.findall(before[-24:])
        negative = sign in ("-", "\u2212") or (previous[-1:] and previous[-1] in _NEGATORS)
        locator = bool(previous) and previous[-1] in _LOCATORS
        out.append((-value if negative else value, locator))
    tokens = _TOKENS.findall(_NUMBER.sub(" # ", lowered))  # punctuation and digits break a run of number words
    for index, value, negative in _number_words(tokens):
        out.append((-value if negative else value, bool(index) and tokens[index - 1] in _LOCATORS))
    return out


def _short_leak(msg_words: list[str], message: str, ref_words: list[str], reference: str,
                allowed: list[list[str]], allowed_raw: list[str]) -> bool:
    """A reference under LEAK_MIN_WORDS words is a name or a number, so it is tested as one.

    A number matches by value ("-2", "minus two", "1,000", "one thousand"); a name must appear as whole words.
    Neither counts when the student or the question already said it, and a number after "page"/"step" is a place.
    """
    ref_numbers = {v for v, _ in numbers_in(reference)}
    if ref_numbers:
        said = {v for text in allowed_raw for v, _ in numbers_in(text)}
        return any(v in ref_numbers and v not in said and not locator for v, locator in numbers_in(message))
    if not tokenize(reference) or all(w in _GENERIC_SHORT for w in ref_words):
        return False
    return _contains_run(msg_words, ref_words) and not any(_contains_run(a, ref_words) for a in allowed)


def reveals_reference(message: str | None, reference: str | None, *, allowed_text: Iterable[str] = ()) -> bool:
    """True when ``message`` reproduces the stored reference answer / rubric.

    Tests, each ignoring what the student or the question already said:
    - the whole normalised reference (25+ characters) inside the message;
    - a run of 6 consecutive reference words (the whole reference if it has 4-5);
    - a short reference (under 4 words): the name as whole words, or the number by value in any common
      spelling (see ``_short_leak``);
    - a close reordering: at least ``LEAK_STEM_SHARE`` of 8+ content stems of the reference present together.
    This is lexical. A paraphrase in different vocabulary is NOT detected, and an unrelated message that
    happens to contain a short reference's number or name is blocked (a false block, not a leak).
    """
    ref_words, msg_words = words(reference), words(message)
    if not ref_words or not msg_words:
        return False
    ref_text, msg_text = " ".join(ref_words), " ".join(msg_words)
    allowed_raw = [a for a in allowed_text if a]
    allowed = [words(a) for a in allowed_raw]
    if len(ref_text) >= LEAK_SUBSTRING_CHARS and ref_text in msg_text:
        return not any(_contains_run(a, ref_words) for a in allowed)
    if len(ref_words) < LEAK_MIN_WORDS:
        return _short_leak(msg_words, message or "", ref_words, reference or "", allowed, allowed_raw)
    window = min(LEAK_WINDOW, len(ref_words))
    for i in range(len(ref_words) - window + 1):
        run = ref_words[i:i + window]
        if _contains_run(msg_words, run) and not any(_contains_run(a, run) for a in allowed):
            return True
    known = set().union(*(set(tokenize(a)) for a in allowed_raw)) if allowed_raw else set()
    ref_stems = set(tokenize(reference or "")) - known
    return len(ref_stems) >= LEAK_STEM_MIN and \
        len(ref_stems & set(tokenize(message or ""))) / len(ref_stems) >= LEAK_STEM_SHARE


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
                      unrevealed_answers: Iterable[str], concept_text: str, other_pages: Iterable[str] = (),
                      ) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(clean_question, None)`` or ``(None, reason_it_was_rejected)``.

    A generated question is shown only when it is structured, cited to supplied passages that
    support its own expected answer, tied to the original concept, new rather than a rewording
    (stricter for a different/transfer question), and reproduces no reference answer that is
    still private. Lexical checks only: they reject rewordings and leaks, they do not prove depth.

    ``other_pages`` are the supplied passages the question did NOT cite. They let two relevance checks run:
    the question must not be clearly better supported by an uncited page (the answer would then address a
    different concept), and a cited page that only repeats what the other cited pages already support, and
    matches the question clearly worse than they do, is a decoy citation. Neither proves the answer is right.
    """
    if step not in NEW_WORDS_MIN:
        return None, "unknown question step"
    if not isinstance(raw, dict) or set(raw) not in ({"question", "expected_answer", "citations"},
                                                      {"question", "expected_answer", "citations", "calculation"}):
        return None, "question does not match the required structure"
    question, expected, citations = raw["question"], raw["expected_answer"], raw["citations"]
    calculation = raw.get("calculation")
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
    cited_pages = [cited_text([c]) for c in citations]
    if calculation is None and (why := requires_calculation(question, expected, cited_pages)):
        return None, f"a computed answer needs a verified calculation: {why}"
    if calculation is not None:
        verdict = verify_calculation(calculation, question=question, expected_answer=expected, cited_pages=cited_pages)
        if verdict.status != VERIFIED:
            return None, f"calculation {verdict.status.lower()}: {verdict.reason}"
    expected_all, passage_stems = set(tokenize(expected)), set(tokenize(cited_text(citations)))
    # A verified calculation yields numbers the passage cannot contain, and narrates them in words that state no
    # fact ("negative", "divided", a unit name). The calculation checked the numbers (including that the answer
    # quotes no other), so only the remaining words are held to the passage. The result still counts as something
    # the answer adds to the question.
    ignore = narration_stems(calculation) if calculation is not None else set()
    keep = lambda stems: {x for x in stems if not x.isdigit() and x not in ignore} if calculation is not None else stems  # noqa: E731
    expected_stems = keep(expected_all)
    if len(expected_all) < 2 or not passage_stems:
        return None, "expected answer is too thin to check against the sources"
    support = len(expected_stems & passage_stems) / len(expected_stems) if expected_stems else 1.0
    if support < SUPPORT_MIN:
        return None, "expected answer is not supported by the cited passages"
    # Support must come from what the answer adds beyond the question's own words, and every
    # cited page must carry some of it: a decoy citation cannot borrow another page's support.
    answer_all = expected_all - set(tokenize(question))
    if len(answer_all) < 2:
        return None, "expected answer adds nothing beyond the question"
    answer_words = keep(answer_all)
    if answer_words:
        if len(answer_words & passage_stems) / len(answer_words) < SUPPORT_MIN:
            return None, "expected answer is not supported by the cited passages"
        if any(not (answer_words & set(tokenize(cited_text([c])))) for c in citations):
            return None, "a cited passage does not support the expected answer"
    if (relevance := _citation_relevance(question, answer_words, [cited_text([c]) for c in citations],
                                         list(other_pages))):
        return None, relevance
    if (conflict := relation_conflict(expected, [cited_text([c]) for c in citations])
            or relation_conflict(question, [cited_text([c]) for c in citations])):
        return None, f"question or expected answer contradicts the cited passages: {conflict}"
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
            **({"calculation": calculation} if calculation is not None else {}),
            "checks": {"support": round(support, 3), "concept_overlap": concept_overlap,
                       "novelty_overlap": novelty["overlap"], "novelty_jaccard": novelty["jaccard"],
                       "new_words": new_words,
                       **({"calculation": VERIFIED} if calculation is not None else {})}}, None


# --- does a generated question need a verified calculation? ---------------------------------------------------------

_COMPUTE_VERB = re.compile(
    r"\b(?:calculate|compute|work out|how much|how many|what (?:is|are) the (?:sum|total|difference|product|ratio|"
    r"average|mean|percentage|rate|present value|interest|profit|cost|price|area|volume|speed|probability|standard error)"
    r")\b", re.IGNORECASE)


def requires_calculation(question: str, expected: str, cited_pages: Iterable[str]) -> str | None:
    """Why a newly generated question must carry a verified calculation, or None.

    A question is computational when its answer states a number that is neither in the question nor in the cited
    passages (a derived value), or when it asks for a calculation over two or more numbers it gives and its answer
    states a number. A question that only mentions numbers, dates, percentages or statistics the sources already state
    ("began in 1998", "set at 0.05", "three stages") is not. Digits and English number words are both read. This
    is a screen, not a proof: a computed value written with a different spelling of a stated number (50% for one half)
    is read as derived, and a computation that happens to produce a number the sources state is caught only when it is
    phrased as a request to calculate.
    """
    pages = list(cited_pages)
    stated = {abs(v) for text in (question, *pages) for v, _ in numbers_in(text)}
    for value, locator in numbers_in(expected):
        if not locator and abs(value) not in stated:
            return f"it states {value.normalize():f}, which neither the question nor the cited passages state"
    given = {abs(v) for v, locator in numbers_in(question) if not locator}
    if _COMPUTE_VERB.search(question) and len(given) >= 2 and any(not loc for _, loc in numbers_in(expected)):
        return "it asks for a calculation over numbers it gives"
    return None


QUESTION_PAGE_MARGIN = 0.15  # how much better one page must match the question than another to count
QUESTION_OTHER_MIN = 0.5     # an uncited page must itself cover this share of the question to outrank the cited


def _citation_relevance(question: str, answer_words: set[str], cited: list[str], others: list[str]) -> str | None:
    """Reason a generated question's citations are clearly irrelevant to it, or None.

    Conservative on purpose: vocabulary shared with a decoy page is not enough. The margins mean a valid
    question whose cited page only matches the question slightly worse than another is never rejected.
    """
    q = set(tokenize(question))
    if not q:
        return None
    share = lambda stems: len(q & stems) / len(q)  # noqa: E731
    pages = [set(tokenize(text)) for text in cited]
    cited_share = share(set().union(*pages))
    for text in others:
        other = share(set(tokenize(text)))
        if other >= QUESTION_OTHER_MIN and other > cited_share + QUESTION_PAGE_MARGIN:
            return "the question is better supported by a page that was not cited"
    if len(pages) > 1 and answer_words:
        for i, page in enumerate(pages):
            rest = [p for j, p in enumerate(pages) if j != i]
            rest_cover = answer_words & set().union(*rest)
            if (answer_words & page) <= rest_cover and len(rest_cover) / len(answer_words) >= SUPPORT_MIN \
                    and share(page) <= max(share(p) for p in rest) - QUESTION_PAGE_MARGIN:
                return "a cited passage adds nothing to the expected answer"
    return None


def answer_support(expected: str | None, passage_text: str) -> float:
    """Share of the reference answer's content words found in the passages it is judged against."""
    stems = set(tokenize(expected or ""))
    return len(stems & set(tokenize(passage_text))) / len(stems) if stems else 0.0


# --- reference-answer support (root and generated) ---------------------------------------

REFERENCE_PAGE_MARGIN = 0.1  # an uncited page this much better supported than the cited ones is a mis-citation
_OPPOSITES = (("positive", "negative"), ("upward", "downward"), ("higher", "lower"), ("larger", "smaller"),
              ("increase", "decrease"), ("increases", "decreases"), ("above", "below"),
              ("multiply", "divide"), ("multiplied", "divided"), ("multiplying", "dividing"),
              ("elastic", "inelastic"), ("equivalent", "different"))
_OPPOSITE_OF = {a: b for a, b in _OPPOSITES} | {b: a for a, b in _OPPOSITES}
_ABSOLUTES = frozenset({"only", "always", "never", "cannot", "guarantee", "guarantees", "proves", "exactly"})


def reference_unsupported(reference: str | None, cited_pages: list[str], other_pages: Iterable[str] = (),
                          *, ignore_stems: set[str] | None = None) -> str | None:
    """Why ``reference`` cannot be treated as backed by ``cited_pages`` (one text per cited page), or None.

    Lexical screening only. It rejects a reference that is thin, mostly absent from the cited text, cited to
    a page that adds nothing, cited to a page when an uncited page supports it clearly better, flips a known
    direction word the passage uses the other way, or asserts an absolute the passage never states.
    A few explicit relations (reversed operands, opposite operation, reversed comparison or direction, flipped
    negation) are also compared with the passage by ``relations.relation_conflict``; only a clear contradiction
    rejects. It does NOT prove the reference is true: a relation it cannot parse or match passes, and so does a
    derived number.
    """
    stems = set(tokenize(reference or ""))
    if ignore_stems is not None:  # numbers and narration of a VERIFIED calculation: the calculation checked them
        stems = {stem for stem in stems if not stem.isdigit() and stem not in ignore_stems}
    if not stems or not cited_pages:
        return "the reference has no checkable content or no cited page text"
    cited_stems = [set(tokenize(page)) for page in cited_pages]
    union = set().union(*cited_stems)
    support = len(stems & union) / len(stems)
    if support < SUPPORT_MIN:
        return "the reference is not supported by the cited passages"
    if any(not (stems & page) for page in cited_stems):
        return "a cited page does not support the reference"
    for other in other_pages:
        if len(stems & set(tokenize(other))) / len(stems) > support + REFERENCE_PAGE_MARGIN:
            return "the reference is better supported by a page that was not cited"
    ref_words, passage_words = set(words(reference)), set(words(" ".join(cited_pages)))
    for word in sorted(ref_words):
        if word in _OPPOSITE_OF and word not in passage_words and _OPPOSITE_OF[word] in passage_words:
            return f"the reference says '{word}' where the passage says '{_OPPOSITE_OF[word]}'"
        if word in _ABSOLUTES and word not in passage_words:
            return f"the reference claims '{word}' which the passage does not"
    if (conflict := relation_conflict(reference, cited_pages)):
        return f"the reference contradicts the cited passages: {conflict}"
    return None


def reference_problem(reference: str | None, source_references: Any, source_contexts: list[dict[str, Any]], *,
                      calculation: Any = None, question: str | None = None) -> str | None:
    """Why a stored reference answer must not be graded against, revealed, hinted from or explained; else None.

    The one gate every use of a stored reference goes through. A task with no reference has nothing to verify.
    Otherwise every citation needs a source id, a source fingerprint and an integer page that was actually
    supplied, and the cited pages must support the reference (``reference_unsupported``).
    A task that carries a ``calculation`` must also have it VERIFIED (``calculation.verify_calculation``) against its
    question and cited pages: REJECTED and INCONCLUSIVE both block the reference. A task without one is unchanged.
    """
    if not reference:
        return None
    refs = source_references or []
    if not refs or not all(isinstance(r, dict) and r.get("source_id") and r.get("fingerprint") is not None
                           and isinstance(r.get("pdf_page"), int) and not isinstance(r.get("pdf_page"), bool)
                           for r in refs):
        return "the reference has no page-level citation with a source fingerprint"
    cited = {(r["source_id"], r["pdf_page"]) for r in refs}
    pages = {(sc.get("source_id"), e.get("pdf_page")): e.get("text", "")
             for sc in source_contexts or [] for e in sc.get("excerpts", []) or []}
    if any(key not in pages for key in cited):
        return "a cited page was not among the supplied passages"
    cited_pages = [pages[k] for k in sorted(cited)]
    if calculation is not None:
        verdict = verify_calculation(calculation, question=question or "", expected_answer=reference,
                                     cited_pages=cited_pages)
        if verdict.status != VERIFIED:
            return f"the calculation is {verdict.status.lower()}: {verdict.reason}"
    return reference_unsupported(reference, cited_pages, [text for key, text in pages.items() if key not in cited],
                                 ignore_stems=narration_stems(calculation) if calculation is not None else None)


HINT_TERMS_MIN, HINT_TERMS_MAX = 2, 4


def source_only_hint(task_text: str | None, cited_pages: list[str]) -> str | None:
    """A deterministic level-2 hint built from the question and the cited passages alone, or None.

    Used when the stored reference cannot be verified: the reference is neither read nor sent anywhere.
    The hint only repeats the question's own content words that the cited pages also use, and points the
    student back at how the passage relates them. It states nothing the question did not already say,
    so it cannot leak an answer. Fewer than ``HINT_TERMS_MIN`` shared terms means no safe hint exists.
    """
    page_stems = set().union(*(set(tokenize(page)) for page in cited_pages)) if cited_pages else set()
    terms: list[str] = []
    for word in words(task_text):
        stem = tokenize(word)
        if stem and stem[0] in page_stems and word not in terms:
            terms.append(word)
    if len(terms) < HINT_TERMS_MIN:
        return None
    shown = terms[:HINT_TERMS_MAX]
    return ("Hint 2: in the passage you were pointed to, find where it talks about "
            + ", ".join(f"'{t}'" for t in shown[:-1]) + f" and '{shown[-1]}'. Ask yourself how the passage "
            "connects them, and put that connection in your own words.")


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
