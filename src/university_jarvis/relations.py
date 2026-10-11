"""Deterministic checks for a few narrow, explicit relationships between a text and its cited passages.

Stage 2 of academic reliability. A reference answer or generated question can reuse the passage's own words
and still state a different relation ("price divided by quantity" where the passage divides quantity by price).
Vocabulary overlap cannot see that, so this module parses a small closed set of patterns from both texts and
compares them:

* arithmetic: ``A divided by B``, ``A multiplied by B`` / ``A times B``, ``A plus B``, ``A minus B``;
* comparison: ``A is greater/larger/higher/more than B``, ``A is less/smaller/lower/fewer than B``,
  ``A exceeds B``, ``A is above/below B``;
* direction: ``a larger/higher X gives a smaller/lower Y`` (and the same-direction forms);
* explicit negation: a clause that is the passage's clause with ``not`` / ``cannot`` / ``never`` added or removed.

Each relation found in the text gets one of three verdicts against the passages:

SUPPORTED      a passage states the same relation (commutative operations match in either operand order).
CONTRADICTED   a passage states a conflicting relation over the same operands: reversed operands of a
               non-commutative operation, the opposite operation, the opposite comparison or direction, or the
               same clause with its negation flipped.
UNDETERMINED   anything else: no pattern, an operand that does not match any passage operand, an ambiguous
               clause. Undetermined is NOT evidence in either direction; callers must not treat it as correct.

This is a lexical pattern check, not semantic reasoning. It never establishes that a text is correct, only that a
specific recognised relation clearly conflicts with a recognised relation in the cited text. Nothing here calls a
model or the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .retrieval import tokenize

SUPPORTED, CONTRADICTED, UNDETERMINED = "SUPPORTED", "CONTRADICTED", "UNDETERMINED"

OPERAND_JACCARD = 0.75     # two operand phrases name the same quantity at this stem overlap or better
NEGATION_MIN_STEMS = 4     # a shorter clause carries too little to tell whether only the negation differs
# Negation compares only clauses whose ordered content stems are identical once the negator is removed: any other
# difference (an extra qualifier, a prefix such as un-, a different subject) leaves the pair undetermined.

_CLAUSE_BREAK = re.compile(r"[,;:()\n]|\.(?=\s|$)|[!?]")
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_ARITHMETIC = {("divided", "by"): "div", ("multiplied", "by"): "mul", ("times",): "mul",
               ("plus",): "add", ("minus",): "sub"}
_FLIPPED = {"div": "mul", "mul": "div", "add": "sub", "sub": "add"}
_COMMUTATIVE = frozenset({"mul", "add"})
_GREATER = {("greater", "than"), ("larger", "than"), ("higher", "than"), ("bigger", "than"), ("more", "than"),
            ("exceeds",)}
_LESSER = {("less", "than"), ("smaller", "than"), ("lower", "than"), ("fewer", "than")}
_UP = frozenset({"higher", "larger", "greater", "bigger", "more", "increased", "rising"})
_DOWN = frozenset({"lower", "smaller", "less", "fewer", "decreased", "reduced", "falling"})
_LINKS = (("leads", "to"), ("lead", "to"), ("results", "in"), ("result", "in"), ("gives",), ("give",),
          ("produces",), ("produce",), ("yields",), ("yield",))
_BOUNDARY = frozenset({"as", "is", "are", "was", "were", "equals", "equal", "gives", "give", "so", "and", "or",
                       "which", "then", "when", "if", "because", "since", "that", "where", "while", "called",
                       "calculated", "found", "raised", "but", "thus", "therefore", "hence", "whereas"})
_FILLER = frozenset({"a", "an", "the", "therefore", "thus", "hence", "also", "then"})
_NEGATORS = frozenset({"not", "cannot", "never", "no"})
# Words that make the negated clause's scope or polarity unclear: such a clause is never compared.
_SCOPE_TRAPS = frozenset({"only", "just", "longer", "unless", "except", "without", "neither", "nor", "but",
                          "although", "though", "however", "if", "whether", "rather", "instead", "than", "either"})
_AUX = frozenset({"do", "does", "did", "is", "are", "was", "were", "be", "been", "being", "can", "could", "will",
                  "would", "may", "might", "should", "must", "has", "have", "had"})
# A sentence that reports, doubts or corrects a claim ("students often say X, which is wrong") may quote a false
# relation on purpose. Relations in such a sentence are never judged: they are UNDETERMINED, not contradicted.
_FRAMING = frozenset({"mistake", "mistakes", "mistaken", "wrong", "wrongly", "incorrect", "incorrectly", "misconception",
                      "misconceptions", "myth", "false", "true", "fallacy", "believe", "believes",
                      "believed", "claim", "claims", "claimed", "say", "says", "said", "think", "thinks", "thought",
                      "assume", "assumes", "assumed", "suppose", "supposed", "imagine", "pretend", "whether", "if",
                      "unlike", "contrary", "misunderstand", "misunderstanding", "confuse", "confused", "instead",
                      "avoid", "beware", "careful", "common", "commonly", "often", "some", "students", "people"})
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
_PRONOUN_START = frozenset({"it", "this", "that", "they", "these", "those", "he", "she", "which", "there", "its"})


@dataclass(frozen=True)
class Finding:
    kind: str       # arithmetic | comparison | direction | negation
    verdict: str    # SUPPORTED | CONTRADICTED | UNDETERMINED
    detail: str


def _clauses(text: str | None) -> list[list[str]]:
    lowered = (text or "").lower().replace("’", "'").replace("can't", "cannot")
    lowered = re.sub(r"n't\b", " not", lowered).replace("'", "")
    return [w for part in _CLAUSE_BREAK.split(lowered) if (w := _WORD.findall(part))]


def _phrase_at(clause: list[str], i: int, phrases: Iterable[tuple[str, ...]]) -> tuple[str, ...] | None:
    return next((p for p in phrases if tuple(clause[i:i + len(p)]) == p), None)


def _stems(words: list[str]) -> frozenset[str]:
    return frozenset(tokenize(" ".join(w for w in words if w not in _FILLER)))


def _same(a: frozenset[str], b: frozenset[str]) -> bool:
    return bool(a) and bool(b) and (a == b or len(a & b) / len(a | b) >= OPERAND_JACCARD)


# --- extraction -------------------------------------------------------------------------

def _operators(clause: list[str]) -> list[tuple[int, int, str]]:
    found, i = [], 0
    while i < len(clause):
        if (phrase := _phrase_at(clause, i, _ARITHMETIC)):
            found.append((i, i + len(phrase), _ARITHMETIC[phrase]))
            i += len(phrase)
        else:
            i += 1
    return found


def _arithmetic(clause: list[str]) -> tuple[list[tuple[str, frozenset[str], frozenset[str]]], bool]:
    """``(relations, ambiguous)``: operands of each operation, or ambiguous when they cannot be told apart."""
    ops = _operators(clause)
    if not ops:
        return [], False
    if _NEGATORS & set(clause) or len(ops) > 2:
        return [], True
    heavy = [o for o in ops if o[2] in ("mul", "div")]
    if len(heavy) > 1:
        return [], True
    # Mixed precedence: only the multiplication/division is read, the addition/subtraction stays inside its operand.
    chosen = heavy or ops
    if not heavy and len(ops) > 1:
        return [], True
    relations = []
    for start, end, op in chosen:
        lo = start
        while lo > 0 and clause[lo - 1] not in _BOUNDARY:
            lo -= 1
        hi = end
        while hi < len(clause) and clause[hi] not in _BOUNDARY:
            hi += 1
        left, right = _stems(clause[lo:start]), _stems(clause[end:hi])
        if not left or not right:
            return [], True
        relations.append((op, left, right))
    return relations, False


def _comparison(clause: list[str]) -> tuple[list[tuple[frozenset[str], frozenset[str]]], bool]:
    """Relations as ``(greater, lesser)`` operand pairs."""
    found, i = [], 0
    while i < len(clause):
        phrase = _phrase_at(clause, i, _GREATER | _LESSER)
        above = clause[i:i + 1] in (["above"], ["below"]) and i > 0 and clause[i - 1] in ("is", "are")
        if not phrase and not above:
            i += 1
            continue
        if _NEGATORS & set(clause):
            return [], True
        width = len(phrase) if phrase else 1
        hi_greater = (phrase in _GREATER) if phrase else clause[i] == "above"
        lo = i
        while lo > 0 and clause[lo - 1] in ("is", "are", "be", "was", "were"):
            lo -= 1
        start = lo
        while start > 0 and clause[start - 1] not in _BOUNDARY:
            start -= 1
        end = i + width
        while end < len(clause) and clause[end] not in _BOUNDARY:
            end += 1
        left, right = _stems(clause[start:lo]), _stems(clause[i + width:end])
        if not left or not right:
            return [], True
        found.append((left, right) if hi_greater else (right, left))
        i += width
    return found, False


def _direction(clause: list[str]) -> list[tuple[frozenset[str], int, frozenset[str], int]]:
    """``(subject, subject_sign, object, object_sign)`` for "a larger X gives a smaller Y"; sign +1 up, -1 down."""
    sign = lambda w: 1 if w in _UP else -1 if w in _DOWN else 0  # noqa: E731
    out = []
    for i in range(len(clause)):
        link = _phrase_at(clause, i, _LINKS)
        if not link:
            continue
        before = [j for j in range(max(0, i - 6), i) if sign(clause[j])]
        if not before:
            continue
        j = before[-1]
        rest = [w for w in clause[i + len(link):] if w not in _FILLER]
        if not rest or not sign(rest[0]) or _NEGATORS & set(clause):
            continue
        tail = []
        for w in rest[1:]:
            if w in _BOUNDARY:
                break
            tail.append(w)
        subject, obj = _stems(clause[j + 1:i]), _stems(tail)
        if subject and obj:
            out.append((subject, sign(clause[j]), obj, sign(rest[0])))
    return out


def _negation_core(clause: list[str]) -> tuple[bool, list[str]] | None:
    """``(negated, ordered content stems)`` for a clause that is safe to compare, else None."""
    present = _NEGATORS & set(clause)
    if len(present) > 1 or _SCOPE_TRAPS & set(clause) or (clause and clause[0] in _PRONOUN_START):
        return None
    if _operators(clause) or any(_phrase_at(clause, i, _GREATER | _LESSER) for i in range(len(clause))):
        return None
    stems = tokenize(" ".join(w for w in clause if w not in _NEGATORS and w not in _AUX))
    return (bool(present), stems) if len(stems) >= NEGATION_MIN_STEMS else None


# --- comparison -------------------------------------------------------------------------

def _arith_verdict(ref, passage) -> str:
    op, left, right = ref
    verdict = UNDETERMINED
    for p_op, p_left, p_right in passage:
        if _same(left, right) or _same(p_left, p_right):
            continue
        ordered = _same(left, p_left) and _same(right, p_right)
        swapped = _same(left, p_right) and _same(right, p_left)
        if p_op == op and (ordered or (swapped and op in _COMMUTATIVE)):
            return SUPPORTED
        if p_op == _FLIPPED[op] and (ordered or swapped):
            verdict = CONTRADICTED
        elif p_op == op and swapped and op not in _COMMUTATIVE:
            verdict = CONTRADICTED
    return verdict


def _pairs_verdict(ref: tuple, passage: list[tuple]) -> str:
    verdict = UNDETERMINED
    for other in passage:
        if _same(ref[0], ref[1]) or _same(other[0], other[1]):
            continue
        if _same(ref[0], other[0]) and _same(ref[1], other[1]):
            return SUPPORTED
        if _same(ref[0], other[1]) and _same(ref[1], other[0]):
            verdict = CONTRADICTED
    return verdict


def _direction_verdict(ref, passage) -> str:
    verdict = UNDETERMINED
    for subject, s_sign, obj, o_sign in passage:
        if _same(ref[0], subject) and _same(ref[2], obj):
            if ref[1] * ref[3] == s_sign * o_sign:
                return SUPPORTED
            verdict = CONTRADICTED
    return verdict


def _negation_verdict(ref: tuple[bool, list[str]], passage: list[tuple[bool, list[str]]]) -> str:
    verdict = UNDETERMINED
    for negated, stems in passage:
        if ref[1] != stems:
            continue
        if negated == ref[0]:
            return SUPPORTED
        verdict = CONTRADICTED
    return verdict


def check_relations(text: str | None, passages: Iterable[str]) -> list[Finding]:
    """Every recognised relation in ``text`` with its verdict against ``passages`` (cited text, one per page)."""
    passage_clauses = [c for page in passages for c in _clauses(page)]
    arithmetic, comparison, direction, negation = [], [], [], []
    for clause in passage_clauses:
        arithmetic += _arithmetic(clause)[0]
        comparison += _comparison(clause)[0]
        direction += _direction(clause)
        if (core := _negation_core(clause)):
            negation.append(core)
    findings: list[Finding] = []
    pairs_to_judge = []
    for sentence in _SENTENCE.split(text or ""):
        framed = bool(_FRAMING & set(_WORD.findall(sentence.lower())))
        pairs_to_judge += [(clause, framed) for clause in _clauses(sentence)]
    for clause, framed in pairs_to_judge:
        text_of = " ".join(clause)
        if framed:
            if _arithmetic(clause)[0] or _comparison(clause)[0] or _direction(clause) or _negation_core(clause):
                findings.append(Finding("framed", UNDETERMINED, text_of))
            continue
        relations, ambiguous = _arithmetic(clause)
        for relation in relations:
            findings.append(Finding("arithmetic", _arith_verdict(relation, arithmetic), text_of))
        pairs, comparison_ambiguous = _comparison(clause)
        for pair in pairs:
            findings.append(Finding("comparison", _pairs_verdict(pair, comparison), text_of))
        for relation in _direction(clause):
            findings.append(Finding("direction", _direction_verdict(relation, direction), text_of))
        if (ambiguous or comparison_ambiguous) and not (relations or pairs):
            findings.append(Finding("arithmetic", UNDETERMINED, text_of))
        if (core := _negation_core(clause)):
            if (verdict := _negation_verdict(core, negation)) != UNDETERMINED:
                findings.append(Finding("negation", verdict, text_of))
    return findings


def relation_conflict(text: str | None, passages: Iterable[str]) -> str | None:
    """Reason ``text`` clearly contradicts a recognised relation in ``passages``, or None.

    None means only that no recognised relation was contradicted. It does not mean the text is supported.
    """
    findings = check_relations(text, list(passages))
    bad = next((f for f in findings if f.verdict == CONTRADICTED), None)
    if bad is None:
        return None
    return f"its {bad.kind} relationship ('{bad.detail}') contradicts the cited passage"
