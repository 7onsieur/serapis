"""Independent, deterministic verification of a structured calculation (academic reliability, stage 3).

A generated question may carry an optional ``calculation`` specification next to its expected answer. This module
recomputes the result itself and decides whether the claim may be trusted. It never calls a model, never uses
``eval``/``exec``/``ast`` on the formula, and uses only the standard library.

Specification (all values are strings so no float ever enters the arithmetic)::

    {"inputs": [{"name": "s", "label": "sample standard deviation", "value": "10", "unit": "", "source": "QUESTION"}],
     "steps":  [{"name": "se", "label": "standard error", "formula": "s / sqrt(n)"}],
     "result": {"value": "2", "unit": "", "decimals": null}}

Verdicts:

VERIFIED      the specification is well formed, every input value appears in the question (``QUESTION``) or in the
              cited passage (``CITED``), every operator relationship is stated by the cited passage, the units are
              consistent, the result is recomputed exactly and equals the claimed result at the stated rounding, and
              the expected answer states that result.
REJECTED      something is demonstrably wrong: malformed or unsafe formula, unknown variable, division by zero,
              an input value that is not in its stated source, a formula that conflicts with the cited passage,
              incompatible units, a result that does not equal the recomputation, an expected answer that does
              not state the result.
INCONCLUSIVE  nothing is shown wrong but the calculation cannot be established: the cited passage does not state the
              formula in a form this module can match, a constant is not in the sources, a unit is not supported,
              a rounding tie or missing rounding makes the result ambiguous.

Only VERIFIED may be shown to a student, graded against, or used for a follow-up. INCONCLUSIVE is never treated as
correct. Verification shows that a stated computation is internally correct and grounded in the cited text. It does
not show that the question asks for the right computation.

Supported: ``+ - * / ^`` (integer powers, and ``^0.5``), ``sqrt()``, parentheses, unary minus, decimals, ``%``
literals, named inputs and earlier step names. Units: a small table of exact length, time and mass units and percent,
converted automatically; other unit names are opaque labels that must match exactly. Not supported: temperature
scales, logarithms, trigonometry, sums over data, statistics tables, symbolic algebra, geometry, calculus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from fractions import Fraction
from typing import Any, Iterable

from .relations import CONTRADICTED, SUPPORTED, check_relations
from .retrieval import tokenize

VERIFIED, REJECTED, INCONCLUSIVE = "VERIFIED", "REJECTED", "INCONCLUSIVE"

MAX_FORMULA_CHARS = 200
MAX_NODES = 60
MAX_DEPTH = 16
MAX_INPUTS = 8
MAX_STEPS = 5
MAX_ABS = Decimal(10) ** 30
MAX_EXPONENT = 16
MAX_DECIMALS = 8
# Off by default: demanding that every input's name occur in the question blocked 3 of 19 correct holdout calculations
# ("costs 150" for a label "price") to close one relabelling hole. Owner decision; see the Stage 3 safety review.
REQUIRE_NAMED_INPUTS = False
BINDING_WINDOW = 6   # words: the nearest name word before a number (with no number between) is taken as its name
PRECISION = 50
_NAME = re.compile(r"[a-z][a-z0-9_]{0,23}")
_NUMBER_TEXT = re.compile(r"[+-]?\d{1,24}(?:\.\d{1,24})?")
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([a-z][a-z0-9_]*)|(\*\*|[-+*/^()%]))")
# A decimal literal in a formula that is not in the sources is only allowed when it is structural.
STRUCTURAL_CONSTANTS = frozenset({Decimal(0), Decimal(1), Decimal(2), Decimal(100), Decimal("0.5")})
# Words that mark the direction of a change. Comparatives ("lower", "higher", "down", "up") are left out on purpose:
# "a lower rate of 5%" does not say the 5% is negative.
DECREASE_WORDS = frozenset({"fall", "falls", "fell", "fallen", "falling", "decrease", "decreases", "decreased",
                            "decreasing", "drop", "drops", "dropped", "decline", "declines", "declined", "reduce",
                            "reduces", "reduced", "reduction", "loss", "lose", "loses", "lost", "deficit", "shrink",
                            "shrinks", "shrank", "shrunk", "cut", "cuts", "negative", "minus"})
INCREASE_WORDS = frozenset({"rise", "rises", "rose", "risen", "rising", "increase", "increases", "increased",
                            "increasing", "grow", "grows", "grew", "grown", "growing", "gain", "gains", "gained",
                            "climb", "climbs", "climbed"})
_NUMBER_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
                 9: "nine", 10: "ten"}


class CalcError(Exception):
    """A calculation problem with the verdict it implies (REJECTED unless stated)."""

    def __init__(self, reason: str, status: str = REJECTED):
        super().__init__(reason)
        self.reason, self.status = reason, status


@dataclass(frozen=True)
class CalcVerdict:
    status: str
    reason: str
    value: str | None = None          # recomputed result in the stated unit, at the stated rounding
    unit: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verified(self) -> bool:
        return self.status == VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "value": self.value, "unit": self.unit}


# --- units ----------------------------------------------------------------------------------------

# name -> (base dimension, exact scale to the base unit). Percent is a dimensionless factor of 1/100.
_UNITS: dict[str, tuple[str, Decimal]] = {
    "mm": ("length", Decimal("0.001")), "cm": ("length", Decimal("0.01")), "m": ("length", Decimal(1)),
    "km": ("length", Decimal(1000)),
    "s": ("time", Decimal(1)), "sec": ("time", Decimal(1)), "min": ("time", Decimal(60)),
    "h": ("time", Decimal(3600)), "hr": ("time", Decimal(3600)), "day": ("time", Decimal(86400)),
    "mg": ("mass", Decimal("0.001")), "g": ("mass", Decimal(1)), "kg": ("mass", Decimal(1000)),
    "%": ("", Decimal("0.01")), "percent": ("", Decimal("0.01")),
}
_UNSUPPORTED_UNITS = frozenset({"°c", "°f", "celsius", "fahrenheit", "kelvin", "degc", "degf"})
Dims = dict[str, Fraction]


def parse_unit(text: str | None) -> tuple[Dims, Decimal]:
    """``(dimensions, scale to base)`` for a unit string such as ``""``, ``"km/h"``, ``"%"`` or ``"m^2"``."""
    text = (text or "").strip().lower().replace("·", "*")
    if not text or text in ("1", "none", "unitless"):
        return {}, Decimal(1)
    if len(text) > 32 or text.count("/") > 1 or not re.fullmatch(r"[a-z%°$£€][a-z0-9%°$£€_]*(?:\^-?\d)?(?:[*/][a-z%°$£€][a-z0-9%°$£€_]*(?:\^-?\d)?)*", text):
        raise CalcError(f"unit '{text}' is not understood", INCONCLUSIVE)
    dims: Dims = {}
    scale = Decimal(1)
    numerator, _, denominator = text.partition("/")
    for part, sign in ((numerator, 1), (denominator, -1)):
        for factor in (p for p in part.split("*") if p):
            name, _, power = factor.partition("^")
            if name in _UNSUPPORTED_UNITS:
                raise CalcError(f"unit '{name}' is not supported (no affine conversions)", INCONCLUSIVE)
            exp = int(power or 1) * sign
            base, factor_scale = _UNITS.get(name, ("?" + name.rstrip("s") if len(name) > 3 else "?" + name, Decimal(1)))
            if base:
                dims[base] = dims.get(base, Fraction(0)) + exp
            scale *= factor_scale ** exp
    return {k: v for k, v in dims.items() if v}, scale


def _opaque(*dims: Dims) -> bool:
    return any(k.startswith("?") for d in dims for k in d)


def _unit_text(dims: Dims) -> str:
    return "*".join(f"{k.lstrip('?')}" + (f"^{v}" if v != 1 else "") for k, v in sorted(dims.items())) or "(none)"


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    dims: tuple[tuple[str, Fraction], ...] = ()

    @property
    def d(self) -> Dims:
        return dict(self.dims)


def _q(value: Decimal, dims: Dims) -> Quantity:
    if value.is_nan() or value.is_infinite() or abs(value) > MAX_ABS:
        raise CalcError("a value is out of the supported range")
    return Quantity(value, tuple(sorted((k, v) for k, v in dims.items() if v)))


def _dims_clash(a: Dims, b: Dims, what: str) -> CalcError:
    return CalcError(f"units do not match when {what}: {_unit_text(a)} and {_unit_text(b)}",
                     INCONCLUSIVE if _opaque(a, b) else REJECTED)


# --- restricted expression parser and evaluator ----------------------------------------------------------

def tokenize_formula(text: str) -> list[tuple[str, str]]:
    if not isinstance(text, str) or not text.strip():
        raise CalcError("the formula is empty")
    text = text.replace("−", "-").replace("×", "*").replace("÷", "/")
    if len(text) > MAX_FORMULA_CHARS or not text.isascii() or not text.isprintable():
        raise CalcError("the formula is too long or contains unsupported characters")
    tokens, pos = [], 0
    while pos < len(text):
        if not text[pos:].strip():
            break
        match = _TOKEN.match(text, pos)
        if match is None:
            raise CalcError(f"the formula contains an unsupported character near '{text[pos:pos + 8].strip()}'")
        number, name, symbol = match.groups()
        tokens.append(("num", number) if number else ("name", name) if name else ("sym", "^" if symbol == "**" else symbol))
        pos = match.end()
    return tokens


class _Parser:
    """expr := term (('+'|'-') term)* ; term := unary (('*'|'/') unary)* ; unary := '-' unary | power ;
    power := atom ('^' unary)? ; atom := number '%'? | name | 'sqrt' '(' expr ')' | '(' expr ')'."""

    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens, self.pos, self.nodes = tokens, 0, 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (expected is not None and token[1] != expected):
            raise CalcError("the formula is malformed" + (f" (expected '{expected}')" if expected else ""))
        self.pos += 1
        return token

    def node(self, depth: int) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise CalcError("the formula is too complex")

    def parse(self) -> tuple:
        tree = self.expr(0)
        if self.peek() is not None:
            raise CalcError("the formula is malformed (unexpected trailing input)")
        return tree

    def expr(self, depth: int) -> tuple:
        left = self.term(depth)
        while (t := self.peek()) and t[0] == "sym" and t[1] in "+-":
            self.take()
            self.node(depth)
            left = (t[1], left, self.term(depth))
        return left

    def term(self, depth: int) -> tuple:
        left = self.unary(depth)
        while (t := self.peek()) and t[0] == "sym" and t[1] in "*/":
            self.take()
            self.node(depth)
            left = (t[1], left, self.unary(depth))
        return left

    def unary(self, depth: int) -> tuple:
        self.node(depth)
        if (t := self.peek()) and t == ("sym", "-"):
            self.take()
            return ("neg", self.unary(depth + 1))
        base = self.atom(depth + 1)
        if self.peek() == ("sym", "^"):
            self.take()
            return ("^", base, self.unary(depth + 1))
        return base

    def atom(self, depth: int) -> tuple:
        self.node(depth)
        kind, text = self.take()
        if kind == "num":
            if self.peek() == ("sym", "%"):
                self.take()
                return ("pct", Decimal(text))
            return ("num", Decimal(text))
        if kind == "name":
            if text == "sqrt":
                self.take("(")
                inner = self.expr(depth + 1)
                self.take(")")
                return ("sqrt", inner)
            if self.peek() == ("sym", "("):
                raise CalcError(f"function '{text}' is not supported")
            return ("var", text)
        if text == "(":
            inner = self.expr(depth + 1)
            self.take(")")
            return inner
        raise CalcError("the formula is malformed")


def parse_formula(text: str) -> tuple:
    return _Parser(tokenize_formula(text)).parse()


def formula_names(tree: tuple) -> set[str]:
    if tree[0] == "var":
        return {tree[1]}
    return set().union(*(formula_names(c) for c in tree[1:] if isinstance(c, tuple))) if tree[0] not in ("num", "pct") else set()


def formula_literals(tree: tuple) -> set[Decimal]:
    if tree[0] == "num":
        return {tree[1]}
    if tree[0] == "pct":
        return {tree[1]}
    return set().union(*(formula_literals(c) for c in tree[1:] if isinstance(c, tuple))) if tree[0] != "var" else set()


def evaluate(tree: tuple, env: dict[str, Quantity], trace: list[Decimal] | None = None) -> Quantity:
    """Evaluate a parsed formula with exact ``Decimal`` arithmetic. Raises ``CalcError``.

    ``trace`` collects the value of every sub-expression (in base units) so the numbers an explanation may quote
    can be checked against what the calculation actually produced."""
    result = _evaluate(tree, env, trace)
    if trace is not None:
        trace.append(result.value)
    return result


def _evaluate(tree: tuple, env: dict[str, Quantity], trace: list[Decimal] | None) -> Quantity:
    kind = tree[0]
    if kind == "num":
        return _q(tree[1], {})
    if kind == "pct":
        return _q(tree[1] / 100, {})
    if kind == "var":
        if tree[1] not in env:
            raise CalcError(f"unknown variable '{tree[1]}'")
        return env[tree[1]]
    if kind == "neg":
        inner = evaluate(tree[1], env, trace)
        return _q(-inner.value, inner.d)
    if kind == "sqrt":
        inner = evaluate(tree[1], env, trace)
        if inner.value < 0:
            raise CalcError("square root of a negative number")
        return _q(inner.value.sqrt(), {k: v / 2 for k, v in inner.d.items()})
    left, right = evaluate(tree[1], env, trace), evaluate(tree[2], env, trace)
    ld, rd = left.d, right.d
    if kind in "+-":
        if ld != rd:
            raise _dims_clash(ld, rd, "adding or subtracting")
        return _q(left.value + right.value if kind == "+" else left.value - right.value, ld)
    if kind == "*":
        return _q(left.value * right.value, {k: ld.get(k, 0) + rd.get(k, 0) for k in {*ld, *rd}})
    if kind == "/":
        if right.value == 0:
            raise CalcError("division by zero")
        return _q(left.value / right.value, {k: ld.get(k, 0) - rd.get(k, 0) for k in {*ld, *rd}})
    if rd:
        raise CalcError("an exponent must not carry a unit")
    exponent = right.value
    if exponent == Decimal("0.5"):
        if left.value < 0:
            raise CalcError("square root of a negative number")
        return _q(left.value.sqrt(), {k: v / 2 for k, v in ld.items()})
    if exponent != exponent.to_integral_value():
        raise CalcError("only integer powers and the power 0.5 are supported", INCONCLUSIVE)
    if abs(exponent) > MAX_EXPONENT:
        raise CalcError("an exponent above 16 is not allowed")
    if left.value == 0 and exponent < 0:
        raise CalcError("division by zero")
    return _q(left.value ** int(exponent), {k: v * int(exponent) for k, v in ld.items()})


# --- formula grounding: the cited passage must state the same operator relationship -------------------------

def _phrase(label: str) -> str:
    return re.sub(r"^(?:the|a|an)\s+", "", label.strip().lower())


def render(tree: tuple, labels: dict[str, str]) -> str:
    """The formula as an English phrase using the passage's own quantity names, for ``relations.check_relations``."""
    kind = tree[0]
    if kind == "var":
        return _phrase(labels.get(tree[1]) or tree[1])
    if kind in ("num", "pct"):
        value = tree[1]
        word = _NUMBER_WORDS.get(int(value)) if value == value.to_integral_value() and kind == "num" else None
        return word or format(value.normalize(), "f") + (" percent" if kind == "pct" else "")
    if kind == "neg":
        return "minus " + render(tree[1], labels)
    if kind == "sqrt":
        return "the square root of " + render(tree[1], labels)
    if kind == "^" and tree[2] == ("num", Decimal("0.5")):
        return "the square root of " + render(tree[1], labels)
    if kind == "^" and tree[2] == ("num", Decimal(2)):
        return render(tree[1], labels) + " squared"
    words = {"+": "plus", "-": "minus", "*": "multiplied by", "/": "divided by", "^": "to the power of"}
    return f"{render(tree[1], labels)} {words[kind]} {render(tree[2], labels)}"


def _ground(step_label: str, tree: tuple, labels: dict[str, str], passages: list[str]) -> tuple[str | None, str]:
    """``(failure_status, reason)`` for one step; ``(None, "")`` when the passage states the relationship."""
    if tree[0] in ("var", "num", "pct", "neg"):
        return None, ""        # no operator to ground (a plain unit change or constant)
    sentence = f"{_phrase(step_label)} equals {render(tree, labels)}."
    findings = check_relations(sentence, passages)
    if any(f.verdict == CONTRADICTED for f in findings):
        return REJECTED, f"the formula for '{step_label}' contradicts the cited passage ({render(tree, labels)})"
    if findings and all(f.verdict == SUPPORTED for f in findings):
        return None, ""
    return INCONCLUSIVE, (f"the cited passage does not state the formula for '{step_label}' "
                          f"in a form that can be matched ({render(tree, labels)})")


# --- sources of input values ----------------------------------------------------------------------------

_PERCENT_AFTER = re.compile(r"(?:%|\s*percent|\s*per\s*cent)", re.IGNORECASE)
_NUM_IN_TEXT = re.compile(r"(?<![\w.])([-+−])?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?")


def stated_values(text: str | None) -> tuple[set[Decimal], set[Decimal], bool]:
    """``(values, percent_values, has_decrease_cue)`` stated in ``text`` (signed digit numbers only)."""
    lowered = (text or "").lower().replace("−", "-")
    values, percents = set(), set()
    for m in _NUM_IN_TEXT.finditer(lowered):
        sign, whole, frac = m.groups()
        value = Decimal(whole.replace(",", "") + (frac or ""))
        value = -value if sign == "-" else value
        values.add(value)
        if _PERCENT_AFTER.match(lowered, m.end()):
            percents.add(value)
    cue = bool(DECREASE_WORDS & set(re.findall(r"[a-z]+", lowered)))
    return values, percents, cue


def _check_source(name: str, value: Decimal, unit_percent: bool, texts: list[str], where: str) -> None:
    pooled_values, pooled_percents, cue = set(), set(), False
    for text in texts:
        v, p, c = stated_values(text)
        pooled_values |= v
        pooled_percents |= p
        cue = cue or c
    if not unit_percent and value * 100 in pooled_percents and value not in pooled_values:
        return    # a stated percentage written as its decimal form (25% as 0.25) is the same quantity
    if value in pooled_values:
        stated_as_percent = value in pooled_percents
        if stated_as_percent and not unit_percent:
            raise CalcError(f"input '{name}' is a percentage in the {where} but is used as a plain number")
        if unit_percent and not stated_as_percent:
            raise CalcError(f"input '{name}' is used as a percentage but the {where} does not say percent",
                            INCONCLUSIVE)
        return
    if -value in pooled_values:    # the magnitude is stated; whether the sign is right is judged by _check_direction
        if unit_percent and (-value) not in pooled_percents:
            raise CalcError(f"input '{name}' is used as a percentage but the {where} does not say percent",
                            INCONCLUSIVE)
        return
    raise CalcError(f"input '{name}' = {value} is not stated in the {where}")


_TOKEN_WORD = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?|[a-z]+")
_CONNECTIVES = frozenset({"for", "as", "is", "are", "was", "were", "being", "represents"})
_ARTICLES = frozenset({"the", "a", "an"})
Token = tuple[str, Any]


def _tokens(text: str) -> list[Token]:
    """Words and signed numbers of ``text`` in order: ``("w", "rises")`` and ``("n", Decimal("-5"))``."""
    out: list[Token] = []
    for raw in _TOKEN_WORD.findall(text.lower().replace("\u2212", "-")):
        out.append(("w", raw) if raw[-1].isalpha() else ("n", Decimal(raw.replace(",", ""))))
    return out


# Words that say how a quantity is expressed ("50 per unit", "10 percent"), not which quantity it is.
_RATE_WORDS = frozenset({"per", "each", "unit", "percent"})


def _owners(tokens: list[Token], groups: dict[str, set[str]]) -> dict[int, str]:
    """Token index -> the one input whose name that word belongs to (words shared by several names are skipped)."""
    owners: dict[int, str] = {}
    for index, (kind, word) in enumerate(tokens):
        if kind == "w" and word not in _RATE_WORDS and not word.startswith("unit"):
            names = {name for stem in tokenize(word) for name, group in groups.items() if stem in group}
            if len(names) == 1:
                owners[index] = names.pop()
    return owners


def _claimant(tokens: list[Token], owners: dict[int, str], at: int) -> str | None:
    """The input whose name this number is written next to, or None.

    In order: "7 is the total" / "7 for the total" (connective, then the name), "3 favourable outcomes" (name right
    after the number), then the nearest name word *before* the number ("a total of 7") with no other number between.
    """
    after = at + 1
    if after < len(tokens) and tokens[after] == ("w", tokens[after][1]) and tokens[after][1] in _CONNECTIVES:
        probe = after + 1
        while probe < len(tokens) and tokens[probe][0] == "w" and tokens[probe][1] in _ARTICLES:
            probe += 1
        if probe in owners:
            return owners[probe]
    if after in owners:
        return owners[after]
    for back in range(at - 1, max(-1, at - 1 - BINDING_WINDOW), -1):
        if tokens[back][0] == "n":
            break
        if back in owners:
            return owners[back]
    return None


def _check_binding(item: dict[str, Any], inputs: list[dict[str, Any]], value: Decimal, texts: list[str],
                   where: str) -> None:
    """An input's number must be written next to its own name, not another input's.

    Provenance alone (the value appears somewhere) cannot tell a swapped pair of inputs from the right pair. Each
    occurrence of the number is claimed by the input whose name it sits next to (see ``_claimant``). INCONCLUSIVE when
    every occurrence belongs to another input, or when the input's whole name does occur in the text but no occurrence
    of the number is tied to it. An input whose name never occurs in the text (the passage's term for a quantity the
    question describes differently) cannot be located this way and is not checked.
    """
    labels = {i["name"]: set(tokenize(i["label"])) for i in inputs}
    groups = {name: (stems - set().union(*(g for n, g in labels.items() if n != name))) or stems
              for name, stems in labels.items()}      # words the names share cannot tell the inputs apart
    wanted = {abs(value), abs(value) * 100}
    claimed_elsewhere = unclaimed = own_named = False
    for text in texts:
        tokens = _tokens(text)
        owners = _owners(tokens, groups)
        own_named = own_named or groups[item["name"]] <= {stem for kind, word in tokens if kind == "w" for stem in tokenize(word)}
        for at, (kind, number) in enumerate(tokens):
            if kind != "n" or abs(number) not in wanted:
                continue
            claim = _claimant(tokens, owners, at)
            if claim == item["name"]:
                return
            claimed_elsewhere, unclaimed = claimed_elsewhere or claim is not None, unclaimed or claim is None
    if claimed_elsewhere and not unclaimed:
        raise CalcError(f"the value of '{item['name']}' ({value}) sits next to a different quantity in the {where}",
                        INCONCLUSIVE)
    if unclaimed and own_named:
        raise CalcError(f"the value of '{item['name']}' ({value}) is not tied to its name in the {where}", INCONCLUSIVE)


def _check_named(item: dict[str, Any], texts: list[str], where: str) -> None:
    """The text must use at least one word of the input's name (or a longer form of it: hour / hourly).

    Otherwise the label could have been chosen to match the formula rather than the quantity the text describes
    ("weight 540 g" relabelled "mass"). Costs some correct calculations whose label differs from the question's wording.
    """
    label = set(tokenize(item["label"]))
    present = {stem for text in texts for stem in tokenize(text)}
    if not any(a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a))) for a in label for b in present):
        raise CalcError(f"the {where} never names the quantity '{item['label']}'", INCONCLUSIVE)


_FROM_TO = re.compile(r"from\s+(-?\d[\d,]*(?:\.\d+)?)\s*(?:%|[a-z]+)?\s+to\s+(-?\d[\d,]*(?:\.\d+)?)")


def _check_anchoring(inputs: list[dict[str, Any]], question: str) -> None:
    """Fewer than half of the question's inputs named in the question is INCONCLUSIVE.

    When most inputs are described in words the question never uses, nothing ties a number to the role the formula
    gives it, and a relabelling chosen to match the passage would look the same as a correct reading. Evidence of a
    role other than the name is "from A to B": the two numbers count as placed, and the inputs must then be listed in
    that order (first A's, then B's). Half is the threshold because a question often names one quantity its own way
    ("costs 150" for a passage's "price").
    """
    own = [(index, i) for index, i in enumerate(inputs) if i["source"] == "QUESTION"]
    if len(own) < 2:
        return
    labels = {i["name"]: set(tokenize(i["label"])) for i in inputs}
    present = set(tokenize(question))
    placed: set[str] = set()
    for first, second in _FROM_TO.findall(question.lower()):
        a, b = (Decimal(x.replace(",", "")) for x in (first, second))
        at = {key: [idx for idx, i in own if abs(Decimal(i["value"])) == abs(v)] for key, v in (("a", a), ("b", b))}
        if at["a"] and at["b"]:
            if min(at["b"]) < min(at["a"]):
                raise CalcError("the inputs are listed in the opposite order to 'from A to B' in the question",
                                INCONCLUSIVE)
            placed |= {inputs[at["a"][0]]["name"], inputs[at["b"][0]]["name"]}
    named = 0
    for _, item in own:
        group = (labels[item["name"]] - set().union(*(g for n, g in labels.items() if n != item["name"]))) or labels[item["name"]]
        if item["name"] in placed or any(a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))
                                         for a in group for b in present):
            named += 1
    if named * 2 < len(own):
        raise CalcError("fewer than half of the inputs are named in the question, so their roles cannot be confirmed",
                        INCONCLUSIVE)


def _polarity(tokens: list[Token], at: int) -> int:
    """-1 / +1 when the number is written as a decrease / increase ("falls by 20", "-5"), else 0."""
    if tokens[at][1] < 0:
        return -1
    for back in range(at - 1, max(-1, at - 5), -1):
        if tokens[back][0] == "n" or tokens[back][1] in ("from", "to"):
            break      # "fell from 50 to 40": 50 and 40 are levels, not the change
        if tokens[back][1] in DECREASE_WORDS:
            return -1
        if tokens[back][1] in INCREASE_WORDS:
            return 1
    return 0


def _check_direction(item: dict[str, Any], value: Decimal, texts: list[str], where: str) -> None:
    """The sign of an input must agree with how the text describes it.

    A quantity whose own name is a decrease ("loss", "decrease rate") is recorded as a positive magnitude. Any other
    quantity written as a fall is recorded negative and one written as a rise positive; a number the text gives no
    direction for must not be negative. A disagreement is INCONCLUSIVE (the model can restate the input), never a
    rejection.
    """
    if value == 0:
        return
    if set(re.findall(r"[a-z]+", item["label"].lower())) & DECREASE_WORDS:
        if value < 0:
            raise CalcError(f"'{item['name']}' is named as a decrease but recorded as negative", INCONCLUSIVE)
        return
    wanted, seen = {abs(value), abs(value) * 100}, False
    for text in texts:
        tokens = _tokens(text)
        for at, (kind, number) in enumerate(tokens):
            if kind == "n" and abs(number) in wanted:
                seen = True
                polarity = _polarity(tokens, at)
                if (value > 0 and polarity >= 0) or (value < 0 and polarity < 0):
                    return
    if seen:
        raise CalcError(f"the sign of '{item['name']}' ({value}) does not agree with how the {where} describes it",
                        INCONCLUSIVE)


# --- what the question asks, and what an explanation may say ------------------------------------------------

_ASKED = re.compile(r"(?:what(?:'s| is| are| was| will be)|calculate|compute|find|determine|work out)\s+"
                    r"(?:the |its |their |a |an )?([a-z][a-z\- ]*?)"
                    r"(?=\s+(?:of|in|for|if|when|given|at|per|after|to|from|and|that|does|do|with)\b|[?.,;]|$)")


def asked_quantity(question: str) -> set[str] | None:
    """Content stems of the quantity a question asks for ("What is the profit margin?" -> profit, margin), or None."""
    match = _ASKED.search(question.lower().replace("\u2019", "'"))
    return set(tokenize(match.group(1))) or None if match else None


# Words that only narrate a computation or name a unit. They state no fact the sources must support, so a question
# whose calculation is VERIFIED does not need them in the passage.
_NARRATION = ("negative minus plus times multiplied divided square squared root equals equal round rounded places place "
              "decimal nearest whole approximately per zero one two three four five six seven eight nine ten "
              "year month week day hour minute second")
_UNIT_WORDS = {"mm": "millimetre millimeter", "cm": "centimetre centimeter", "m": "metre meter", "km": "kilometre kilometer",
               "s": "second", "sec": "second", "min": "minute", "h": "hour", "hr": "hour", "day": "day",
               "mg": "milligram", "g": "gram", "kg": "kilogram", "%": "percent", "percent": "percent"}


def narration_stems(spec: Any) -> set[str]:
    """Stems of computation-narration words and of the unit names the specification uses."""
    words = _NARRATION
    try:
        units = {u for item in [*spec["inputs"], spec["result"]] for u in re.findall(r"[a-z%]+", item["unit"].lower())}
    except (KeyError, TypeError, AttributeError):
        units = set()
    for unit in units:
        words += " " + unit + " " + _UNIT_WORDS.get(unit, "")
    return set(tokenize(words))


def _allowed_numbers(values: list[Decimal], scales: set[Decimal], stated: set[Decimal]) -> list[Decimal]:
    out = list(stated)
    for value in values:
        for scale in scales:
            out += [value / scale, value / scale * 100]
    return out


def _states_only_known_numbers(expected: str, numbers_in: Any, allowed: list[Decimal]) -> Decimal | None:
    """The first number in ``expected`` (not a page or step locator) that the calculation does not account for."""
    for number, locator in numbers_in(expected):
        if locator:
            continue
        places = max(0, -number.as_tuple().exponent)
        if not any(_round(abs(known), places, ROUND_HALF_UP) == abs(number) or abs(known) == abs(number)
                   for known in allowed):
            return number
    return None


# --- the specification ---------------------------------------------------------------------------------

def _decimal(text: Any, label: str) -> Decimal:
    if not isinstance(text, str) or not _NUMBER_TEXT.fullmatch(text.strip()):
        raise CalcError(f"{label} is not a plain decimal number")
    return Decimal(text.strip())


def _shape(spec: Any) -> None:
    def keys(obj: Any, expected: set[str], label: str) -> None:
        if not isinstance(obj, dict) or set(obj) != expected:
            raise CalcError(f"the calculation {label} does not match the required structure")

    keys(spec, {"inputs", "steps", "result"}, "specification")
    if not isinstance(spec["inputs"], list) or not 0 < len(spec["inputs"]) <= MAX_INPUTS:
        raise CalcError("the calculation needs between 1 and 8 inputs")
    if not isinstance(spec["steps"], list) or not 0 < len(spec["steps"]) <= MAX_STEPS:
        raise CalcError("the calculation needs between 1 and 5 steps")
    for item in spec["inputs"]:
        keys(item, {"name", "label", "value", "unit", "source"}, "input")
    for item in spec["steps"]:
        keys(item, {"name", "label", "formula"}, "step")
    keys(spec["result"], {"value", "unit", "decimals"}, "result")
    for item in [*spec["inputs"], *spec["steps"]]:
        if not isinstance(item["name"], str) or not _NAME.fullmatch(item["name"]) or item["name"] == "sqrt":
            raise CalcError("a variable name is not a plain lowercase identifier")
        if not isinstance(item["label"], str) or not 0 < len(item["label"].strip()) <= 80:
            raise CalcError("a variable label is missing or too long")
    names = [i["name"] for i in [*spec["inputs"], *spec["steps"]]]
    if len(set(names)) != len(names):
        raise CalcError("a variable name is used twice")
    decimals = spec["result"]["decimals"]
    if decimals is not None and (isinstance(decimals, bool) or not isinstance(decimals, int)
                                 or not 0 <= decimals <= MAX_DECIMALS):
        raise CalcError("decimals must be null or an integer from 0 to 8")
    for item in spec["inputs"]:
        if item["source"] not in ("QUESTION", "CITED") or not isinstance(item["unit"], str):
            raise CalcError("an input needs a source of QUESTION or CITED and a unit string")
    if not isinstance(spec["result"]["unit"], str):
        raise CalcError("the result unit must be a string")


def _round(value: Decimal, decimals: int, mode: str) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=mode)


def verify_calculation(spec: Any, *, question: str, expected_answer: str, cited_pages: Iterable[str]) -> CalcVerdict:
    """Recompute ``spec`` independently and check it against the question, the cited pages and the expected answer."""
    from .tutor_policy import numbers_in   # local import: tutor_policy imports this module

    pages = [p for p in cited_pages if p]
    try:
        with localcontext() as ctx:
            ctx.prec = PRECISION
            ctx.traps[InvalidOperation] = True
            return _verify(spec, question, expected_answer, pages, numbers_in)
    except CalcError as exc:
        return CalcVerdict(exc.status, exc.reason)
    except (InvalidOperation, ArithmeticError, ValueError, RecursionError) as exc:
        return CalcVerdict(REJECTED, f"the calculation could not be evaluated ({type(exc).__name__})")


def _verify(spec: Any, question: str, expected: str, pages: list[str], numbers_in: Any) -> CalcVerdict:
    _shape(spec)
    if not pages:
        raise CalcError("there is no cited passage to ground the calculation", INCONCLUSIVE)
    env: dict[str, Quantity] = {}
    labels: dict[str, str] = {}
    literals_ok = {v for text in (question, *pages) for v in stated_values(text)[0]} | set(STRUCTURAL_CONSTANTS)
    literals_ok |= {abs(v) for v in literals_ok}
    notes: list[str] = []
    for item in spec["inputs"]:
        value = _decimal(item["value"], f"the value of '{item['name']}'")
        dims, scale = parse_unit(item["unit"])
        unit_percent = item["unit"].strip().lower() in ("%", "percent")
        texts = [question] if item["source"] == "QUESTION" else pages
        where = "question" if item["source"] == "QUESTION" else "cited passage"
        _check_source(item["name"], value, unit_percent, texts, where)
        _check_binding(item, spec["inputs"], value, texts, where)
        _check_direction(item, value, texts, where)
        if REQUIRE_NAMED_INPUTS:
            _check_named(item, texts, where)
        env[item["name"]] = _q(value * scale, dims)
        labels[item["name"]] = item["label"]
    _check_anchoring(spec["inputs"], question)
    grounded: list[str] = []
    last = None
    trace: list[Decimal] = []
    used_literals: set[Decimal] = set()
    for step in spec["steps"]:
        tree = parse_formula(step["formula"])
        unknown = formula_names(tree) - set(env)
        if unknown:
            raise CalcError(f"unknown variable '{sorted(unknown)[0]}'")
        value = evaluate(tree, env, trace)    # first: a computation that cannot be carried out is wrong whatever the passage says
        used_literals |= formula_literals(tree)
        for literal in formula_literals(tree):
            if literal not in literals_ok:
                raise CalcError(f"the constant {literal} is not stated in the question or the cited passage",
                                INCONCLUSIVE)
        failure, why = _ground(step["label"], tree, labels, pages)
        if failure:
            raise CalcError(why, failure)
        if tree[0] not in ("var", "num", "pct", "neg"):
            grounded.append(step["name"])
        last = env[step["name"]] = value
        labels[step["name"]] = step["label"]
    if not grounded:
        raise CalcError("no step states an operator relationship that the cited passage can confirm", INCONCLUSIVE)
    result = spec["result"]
    claimed = _decimal(result["value"], "the claimed result")
    r_dims, r_scale = parse_unit(result["unit"])
    assert last is not None
    if last.d != r_dims:
        raise _dims_clash(last.d, r_dims, "comparing the computed unit with the stated result unit")
    computed = _round(last.value / r_scale, 20, ROUND_HALF_UP)   # drops division noise from unit scales, never a real digit
    decimals = result["decimals"]
    if decimals is None:
        if computed != _round(computed, 12, ROUND_HALF_UP):
            places = max(0, -claimed.as_tuple().exponent)
            if claimed != _round(computed, places, ROUND_HALF_UP):
                raise CalcError(f"the recomputed result is about {_round(computed, 6, ROUND_HALF_UP).normalize():f}, "
                                f"not {claimed.normalize():f}")
            raise CalcError("the result is not exact, so the rounding must be stated", INCONCLUSIVE)
        rounded = computed
    else:
        rounded = _round(computed, decimals, ROUND_HALF_UP)
        even = _round(computed, decimals, ROUND_HALF_EVEN)
        if even != rounded and claimed == even:
            raise CalcError("the result sits exactly on a rounding tie and the stated value uses another convention",
                            INCONCLUSIVE)
    if claimed != rounded:
        raise CalcError(f"the recomputed result is {rounded.normalize():f}, not {claimed.normalize():f}")
    if not any(v == rounded and not locator for v, locator in numbers_in(expected)):
        raise CalcError("the expected answer does not state the computed result")
    asked = asked_quantity(question)
    if asked and not asked <= set(tokenize(spec["steps"][-1]["label"])):
        raise CalcError("the final step does not compute what the question asks for "
                        f"('{spec['steps'][-1]['label']}')", INCONCLUSIVE)
    scales = {Decimal(1), r_scale} | {scale for _, scale in _UNITS.values()}
    stated = {abs(v) for text in (question, *pages) for v in stated_values(text)[0]}
    stated |= {abs(v) for text in (question, *pages) for v, _ in numbers_in(text)}
    allowed = _allowed_numbers(trace, scales, stated) + [abs(_decimal(i["value"], "an input")) for i in spec["inputs"]]
    allowed += list(used_literals) + ([Decimal(result["decimals"])] if result["decimals"] is not None else [])
    extra = _states_only_known_numbers(expected, numbers_in, allowed)
    if extra is not None:
        raise CalcError(f"the expected answer states {extra.normalize():f}, which the calculation does not produce "
                        "and the sources do not state")
    return CalcVerdict(VERIFIED, "recomputed and grounded", format(rounded.normalize(), "f"), result["unit"].strip(),
                       tuple(notes))
