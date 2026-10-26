"""One bounded, accounted retry for model generations that fail in a recoverable way.

A model call is paid for whether or not its output passes our checks. This module decides when a second
attempt is reasonable and keeps every attempt visible:

- At most ``MAX_ATTEMPTS`` (two) calls per generation, and no second call once ``RETRY_WINDOW_SECONDS`` has
  passed since the first started.
- Only failures marked ``retryable`` are retried: the model produced something our validators refused
  (a mis-copied source id, missing provenance, a reply that reproduced the reference answer), a
  malformed or incomplete response, or a transient provider fault (timeout, rate limit, 5xx).
- Never retried: authentication, billing or configuration errors, provider refusals and content-filter
  stops (these may be academic-integrity refusals), spending or call-limit refusals, truncation at the
  output limit, and anything not explicitly marked retryable. The default is not to retry.
- The retry runs the same validators on the new output; nothing is relaxed. State is written by the
  caller only after a generation passes, so a failed first attempt changes nothing and a retry cannot
  duplicate a state change.
- ``KeyboardInterrupt`` and other ``BaseException``s are never caught, so cancellation stops the loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

MAX_ATTEMPTS = 2
RETRY_WINDOW_SECONDS = 150.0

T = TypeVar("T")


def is_retryable(exc: BaseException) -> bool:
    return bool(getattr(exc, "retryable", False))


def usage_dict(usage: Any) -> dict[str, int] | None:
    """A provider's ``last_usage`` as a plain dict, or None when it reported nothing usable."""
    if usage is None:
        return None
    if hasattr(usage, "to_dict"):
        usage = usage.to_dict()
    if not isinstance(usage, dict):
        return None
    counts = {k: usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")}
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in counts.values()):
        return None
    return counts  # type: ignore[return-value]


def add_usage(total: dict[str, int] | None, usage: dict[str, int] | None) -> dict[str, int] | None:
    if usage is None:
        return total
    if total is None:
        return dict(usage)
    return {k: total.get(k, 0) + usage.get(k, 0) for k in ("input_tokens", "output_tokens", "total_tokens")}


@dataclass
class Attempt:
    number: int
    usage: dict[str, int] | None
    error: str | None = None  # the validator's or provider's reason, when the attempt did not succeed

    def to_dict(self) -> dict[str, Any]:
        return {"attempt": self.number, "usage": self.usage, "error": self.error}


@dataclass
class Outcome(Generic[T]):
    value: T
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def usage(self) -> dict[str, int] | None:
        total = None
        for attempt in self.attempts:
            total = add_usage(total, attempt.usage)
        return total


class GenerationFailed(Exception):
    """Internal carrier so callers can read what every attempt cost when the generation finally fails."""

    def __init__(self, original: BaseException, attempts: list[Attempt]) -> None:
        super().__init__(str(original))
        self.original = original
        self.attempts = attempts


def run_checked(
    call: Callable[[str | None], Any],
    check: Callable[[Any], T],
    *,
    last_usage: Callable[[], Any] = lambda: None,
    charge: Callable[[], None] | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    window_seconds: float = RETRY_WINDOW_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    correction: Callable[[BaseException], str | None] = lambda exc: str(exc)[:300],
) -> Outcome[T]:
    """Call, validate, and retry once when the failure is recoverable.

    ``call(note)`` makes one provider request (``note`` is a short, secret-free reason the previous
    attempt was refused, or None on the first). ``check(raw)`` returns the validated value or raises.
    ``charge()`` is invoked before every attempt after the first and may raise to refuse it (for example
    when a per-session call limit is reached); the first attempt is charged by the caller. On final
    failure the original exception is re-raised after attaching ``attempts`` and the summed ``usage``.
    """
    started = clock()
    attempts: list[Attempt] = []
    note: str | None = None
    previous: BaseException | None = None
    for number in range(1, max_attempts + 1):
        if number > 1 and charge is not None:
            try:
                charge()
            except Exception:
                # A limit refused the second call: report the failure that made us want it, not the limit.
                assert previous is not None
                setattr(previous, "attempts", attempts)
                setattr(previous, "total_usage", Outcome(None, attempts).usage)
                raise previous
        error: BaseException | None = None
        try:
            raw = call(note)
        except Exception as exc:
            error = exc
            attempts.append(Attempt(number, usage_dict(getattr(exc, "usage", None)) or usage_dict(last_usage()), str(exc)[:200]))
        else:
            usage = usage_dict(last_usage())
            try:
                value = check(raw)
            except Exception as exc:
                error = exc
                attempts.append(Attempt(number, usage, str(exc)[:200]))
            else:
                attempts.append(Attempt(number, usage))
                return Outcome(value, attempts)
        assert error is not None
        out_of_attempts = number >= max_attempts
        out_of_time = clock() - started > window_seconds
        if out_of_attempts or out_of_time or not is_retryable(error):
            setattr(error, "attempts", attempts)
            setattr(error, "total_usage", Outcome(None, attempts).usage)
            raise error
        previous = error
        note = correction(error)
    raise AssertionError("unreachable")  # pragma: no cover
