"""Deterministic, offline passage retrieval over extracted academic sources.

Source units (PDF pages / PPTX slides) are split into small passages that keep
the document identity, unit number, title and source fingerprint. Passages are
ranked with BM25 against a student's topic or question and packed into a fixed
character budget. Nothing here calls a model or the network, and nothing is
persisted: retrieval runs on text that is already extracted at request time.

Every result states what happened (``matched`` / ``no_match`` /
``no_query_terms``) and how much matching material the budget left out, so a
caller can never mistake a bounded selection for the whole document.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

RETRIEVAL_CHARACTER_LIMIT = 8_000
PASSAGE_CHARACTER_TARGET = 600
MAX_PASSAGES_PER_UNIT = 2
RELATIVE_SCORE_FLOOR = 0.25
BM25_K1 = 1.5
BM25_B = 0.75
TITLE_WEIGHT = 2

STATUS_MATCHED = "matched"
STATUS_NO_MATCH = "no_match"
STATUS_NO_QUERY_TERMS = "no_query_terms"

_STOPWORDS = frozenset(
    """a about above after again all also am an and any are as at be because been before being
    between both but by can could did do does doing down during each few for from further had has
    have having he her here hers him his how i if in into is it its itself just me more most my no
    nor not now of off on once only or other our out over own same she should so some such than
    that the their them then there these they this those through to too under until up very was
    we were what when where which while who whom why will with would you your explain describe
    tell give understand please""".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_BLOCK_BREAK = re.compile(r"\n\s*\n")


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase, drop stopwords and one-character tokens, lightly stem."""
    return [
        _stem(token)
        for token in _TOKEN.findall(text.lower())
        if token not in _STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


@dataclass(frozen=True)
class Passage:
    source_id: str
    source_order: int
    unit: int
    index: int
    text: str
    title: str | None

    @property
    def passage_id(self) -> str:
        return f"{self.source_id}:{self.unit}:{self.index}"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_long(sentence: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in sentence.split():
        if current and len(current) + 1 + len(word) > limit:
            pieces.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        pieces.append(current)
    return pieces


def split_passages(raw_text: str, limit: int = PASSAGE_CHARACTER_TARGET) -> list[str]:
    """Split one unit's text on blocks then sentences, packed up to ``limit`` characters."""
    sentences: list[str] = []
    for block in _BLOCK_BREAK.split(raw_text):
        for sentence in _SENTENCE_END.split(_normalize(block)):
            if sentence:
                sentences.extend(
                    [sentence] if len(sentence) <= limit else _split_long(sentence, limit)
                )
    passages: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > limit:
            passages.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        passages.append(current)
    return passages


def build_passages(
    source_id: str,
    source_order: int,
    units: list[str],
    titles: dict[int, str | None] | None = None,
) -> list[Passage]:
    passages: list[Passage] = []
    for unit_number, raw in enumerate(units, start=1):
        title = (titles or {}).get(unit_number)
        for index, text in enumerate(split_passages(raw), start=1):
            passages.append(Passage(source_id, source_order, unit_number, index, text, title))
    return passages


def rank_passages(
    passages: list[Passage], query: str
) -> tuple[list[tuple[float, Passage]], list[str]]:
    """BM25-rank passages for ``query``; return (score, passage) pairs, best first, and query terms."""
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms or not passages:
        return [], terms
    documents = [
        tokenize(passage.text) + tokenize(passage.title or "") * TITLE_WEIGHT
        for passage in passages
    ]
    average_length = sum(len(doc) for doc in documents) / len(documents) or 1.0
    document_frequency = {
        term: sum(1 for doc in documents if term in doc) for term in terms
    }
    total = len(documents)
    scored: list[tuple[float, Passage]] = []
    for passage, doc in zip(passages, documents):
        score = 0.0
        for term in terms:
            frequency = doc.count(term)
            if not frequency:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            norm = frequency + BM25_K1 * (1 - BM25_B + BM25_B * len(doc) / average_length)
            score += idf * frequency * (BM25_K1 + 1) / norm
        if score > 0:
            scored.append((score, passage))
    scored.sort(
        key=lambda pair: (-pair[0], pair[1].source_order, pair[1].unit, pair[1].index)
    )
    return scored, terms


def select_passages(
    passages: list[Passage],
    query: str,
    *,
    character_limit: int = RETRIEVAL_CHARACTER_LIMIT,
    pinned: Iterable[tuple[str, int]] = (),
) -> tuple[list[Passage], dict[str, Any]]:
    """Choose the best passages within budget and describe the outcome explicitly.

    ``pinned`` units ``(source_id, unit_number)`` are included first (all their
    passages), for callers that already know exactly which unit is cited.
    """
    ranked, terms = rank_passages(passages, query)
    pinned_units = set(pinned)
    selected: list[Passage] = []
    used = 0
    for passage in passages:
        if (passage.source_id, passage.unit) in pinned_units and used + len(passage.text) <= character_limit:
            selected.append(passage)
            used += len(passage.text)

    floor = ranked[0][0] * RELATIVE_SCORE_FLOOR if ranked else 0.0
    candidates = [pair for pair in ranked if pair[0] >= floor]
    per_unit: dict[tuple[str, int], int] = {}
    chosen_ids = {p.passage_id for p in selected}
    omitted = 0
    for _score, passage in candidates:
        if passage.passage_id in chosen_ids:
            continue
        key = (passage.source_id, passage.unit)
        if per_unit.get(key, 0) >= MAX_PASSAGES_PER_UNIT or used + len(passage.text) > character_limit:
            omitted += 1
            continue
        per_unit[key] = per_unit.get(key, 0) + 1
        selected.append(passage)
        chosen_ids.add(passage.passage_id)
        used += len(passage.text)
    selected.sort(key=lambda p: (p.source_order, p.unit, p.index))

    if not terms:
        status = STATUS_NO_QUERY_TERMS
    elif not candidates and not selected:
        status = STATUS_NO_MATCH
    else:
        status = STATUS_MATCHED
    report = {
        "method": "bm25_passages",
        "status": status,
        "query_terms": terms,
        "passages_indexed": len(passages),
        "passages_matched": len(ranked),
        "passages_selected": len(selected),
        "matched_passages_omitted": omitted + (len(ranked) - len(candidates)),
        "character_limit": character_limit,
        "character_count": used,
        "complete": status == STATUS_MATCHED and omitted == 0 and len(candidates) == len(ranked),
    }
    return selected, report


def retrieval_note(report: dict[str, Any]) -> str:
    """Plain statement for the model and the student about what the selection is."""
    status = report["status"]
    if status == STATUS_MATCHED:
        base = (
            "Excerpts are passages retrieved for the request, not the whole source; "
            "absence of a topic here does not show the source omits it."
        )
        if not report["complete"]:
            base += (
                f" {report['matched_passages_omitted']} lower-ranked matching passage(s) "
                "were left out to bound context."
            )
        return base
    return (
        "No passage matched the request. The excerpts are only the leading material of "
        "the source and are NOT evidence for the requested topic; treat it as unsupported."
    )
