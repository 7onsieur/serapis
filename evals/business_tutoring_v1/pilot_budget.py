"""Hard spending controls for the live pilot. Pure logic: no network, no credentials, no model calls.

A request is sent only after a write-ahead RESERVATION of its worst-case cost has been fsynced to an append-only ledger and
fits inside BOTH caps (tokens and dollars). After the response the reservation is settled with the provider-reported usage.

Guarantees (and their limits) are in LIVE_PILOT_PROPOSAL.md. In short:
- worst-case output = the explicit max_output_tokens sent with the request (it also bounds reasoning tokens);
- worst-case input = UTF-8 bytes of instructions + serialised context + output schema, plus a fixed overhead. A token covers
  at least one byte, so bytes bound tokens. This is an assumption about the tokenizer, stated, not measured;
- price = owner-attested per-million rates for the exact model, times an owner-stated surcharge multiplier (>= 1); all input is
  priced at the full input rate (cached-input discounts are ignored, which only over-reserves);
- unknown pricing, missing usage, a usage figure above its reservation, an error with no usage, or an interrupted run all
  end the pilot, and the unsettled reservation is charged at its worst case. Nothing resets spent budget: the ledger is replayed.
- The ledger is a local file. Someone who deletes it can reset it; the real backstop is a provider-side spend limit on the key.
"""

from __future__ import annotations

import datetime
import fcntl
import json
import math
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from university_jarvis.reasoning import ReasoningError  # noqa: E402

HARD_TOKEN_CAP = 600_000          # owner-defined ceilings (LIVE_PILOT_PROPOSAL.md); an approval file can only lower them
HARD_USD_CAP = Decimal("5")
HARD_MAX_OUTPUT_TOKENS = 4_000
HARD_MAX_CALLS = 80
INPUT_OVERHEAD_TOKENS = 1_000     # framing, schema wrapper, anything the provider adds that we cannot see
PRICE_MAX_AGE_DAYS = 30


class ApprovalError(Exception):
    pass


class BudgetRefused(Exception):
    """The next request could exceed a cap, or the pilot is halted. Raised BEFORE anything is sent."""


@dataclass(frozen=True)
class Approval:
    approval_id: str
    model: str
    reviewer: str
    token_cap: int
    usd_cap: Decimal
    max_output_tokens: int
    input_per_million: Decimal
    output_per_million: Decimal
    surcharge_multiplier: Decimal
    pricing_source: str
    pricing_verified_on: str
    pricing_verified_by: str


def _num(value: Any, name: str, *, integer=False, positive=True) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ApprovalError(f"{name} must be a number")
    try:
        d = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise ApprovalError(f"{name} must be a number") from exc
    if not d.is_finite() or (positive and d <= 0) or (integer and d != d.to_integral_value()):
        raise ApprovalError(f"{name} is not a valid {'integer' if integer else 'positive number'}")
    return d


def parse_approval(data: Any, *, today: datetime.date | None = None) -> Approval:
    """Validate an owner approval. Caps can only be LOWERED relative to the hard ceilings; pricing must be attested."""
    today = today or datetime.date.today()
    if not isinstance(data, dict) or data.get("approved") is not True:
        raise ApprovalError("approval file must contain approved: true")
    text = lambda k: (data.get(k) if isinstance(data.get(k), str) and data.get(k).strip() else None)  # noqa: E731
    for key in ("approval_id", "model", "reviewer"):
        if not text(key):
            raise ApprovalError(f"approval file lacks {key}")
    pricing = data.get("pricing")
    if not isinstance(pricing, dict):
        raise ApprovalError("pricing is unknown: approval file needs a pricing object for the selected model")
    if pricing.get("model") != data["model"]:
        raise ApprovalError("pricing.model must equal the approved model")
    for key in ("source", "verified_by"):
        if not (isinstance(pricing.get(key), str) and pricing[key].strip()):
            raise ApprovalError(f"pricing.{key} is required (owner attestation of where and by whom the rates were verified)")
    try:
        verified = datetime.date.fromisoformat(pricing.get("verified_on"))
    except Exception as exc:  # noqa: BLE001
        raise ApprovalError("pricing.verified_on must be an ISO date") from exc
    if verified > today or (today - verified).days > PRICE_MAX_AGE_DAYS:
        raise ApprovalError(f"pricing was not verified within the last {PRICE_MAX_AGE_DAYS} days")
    multiplier = _num(pricing.get("surcharge_multiplier"), "pricing.surcharge_multiplier")
    if multiplier < 1:
        raise ApprovalError("pricing.surcharge_multiplier must be >= 1 (state the worst billing tier you could be charged)")
    token_cap = min(int(_num(data.get("token_cap", HARD_TOKEN_CAP), "token_cap", integer=True)), HARD_TOKEN_CAP)
    usd_cap = min(_num(data.get("usd_cap", HARD_USD_CAP), "usd_cap"), HARD_USD_CAP)
    max_out = int(_num(data.get("max_output_tokens"), "max_output_tokens", integer=True))  # explicit, no default
    if max_out > HARD_MAX_OUTPUT_TOKENS:
        raise ApprovalError(f"max_output_tokens may not exceed {HARD_MAX_OUTPUT_TOKENS}")
    return Approval(data["approval_id"], data["model"], data["reviewer"], token_cap, usd_cap, max_out,
                    _num(pricing.get("input_usd_per_million"), "pricing.input_usd_per_million"),
                    _num(pricing.get("output_usd_per_million"), "pricing.output_usd_per_million"),
                    multiplier, pricing["source"], pricing["verified_on"], pricing["verified_by"])


def worst_case_input_tokens(instructions: str, context: dict, output_format: dict) -> int:
    """Upper bound on billed input tokens: bytes of everything we send (a token spans >= 1 byte) plus fixed overhead."""
    body = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    schema = json.dumps(output_format, ensure_ascii=False, separators=(",", ":"))
    return len((instructions + body + schema).encode("utf-8")) + INPUT_OVERHEAD_TOKENS


def cost_usd(a: Approval, input_tokens: int, output_tokens: int) -> Decimal:
    return (Decimal(input_tokens) * a.input_per_million + Decimal(output_tokens) * a.output_per_million) \
        / Decimal(1_000_000) * a.surcharge_multiplier


class Budget:
    """Write-ahead ledger + replay. One instance per run; the ledger file persists across runs and interruptions."""

    def __init__(self, approval: Approval, ledger_path: Path, *, max_calls: int = HARD_MAX_CALLS):
        self.a, self.path, self.max_calls = approval, Path(ledger_path), max_calls
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BudgetRefused("another run holds this ledger") from exc
        self.entries: list[dict] = self._replay()
        if not self.entries:
            self._append({"type": "open", "approval_id": approval.approval_id, "model": approval.model,
                          "token_cap": approval.token_cap, "usd_cap": str(approval.usd_cap)})
        else:
            first = self.entries[0]
            if first.get("type") != "open" or first.get("approval_id") != approval.approval_id or first.get("model") != approval.model:
                raise BudgetRefused("ledger belongs to a different approval/model; it is never reset by the runner")
        # An approval can never raise caps recorded when the ledger was opened.
        opened = self.entries[0]
        self.token_cap = min(approval.token_cap, int(opened["token_cap"]))
        self.usd_cap = min(approval.usd_cap, Decimal(opened["usd_cap"]))

    # -- persistence
    def _replay(self) -> list[dict]:
        with open(self.path, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        try:
            return [json.loads(ln) for ln in lines]
        except json.JSONDecodeError as exc:
            raise BudgetRefused("ledger is corrupt; refusing to run (spent budget cannot be determined)") from exc

    def _append(self, entry: dict) -> None:
        entry = {"seq": len(self.entries), **entry}
        os.write(self._fd, (json.dumps(entry, sort_keys=True) + "\n").encode())
        os.fsync(self._fd)
        self.entries.append(entry)

    # -- state
    def halted(self) -> str | None:
        return next((e["reason"] for e in self.entries if e["type"] == "halt"), None)

    def spent(self) -> tuple[int, Decimal]:
        reserved, settled = {}, {}
        for e in self.entries:
            if e["type"] == "reserve":
                reserved[e["id"]] = e
            elif e["type"] == "settle":
                settled[e["id"]] = e
        tokens, usd = 0, Decimal(0)
        for rid, r in reserved.items():
            s = settled.get(rid)
            tokens += int(s["charged_tokens"]) if s else int(r["worst_tokens"])  # unsettled (interrupted) = worst case
            usd += Decimal(s["charged_usd"]) if s else Decimal(r["worst_usd"])
        return tokens, usd

    def calls(self) -> int:
        return sum(e["type"] == "reserve" for e in self.entries)

    def halt(self, reason: str) -> None:
        if not self.halted():
            self._append({"type": "halt", "reason": reason})

    # -- the gate
    def reserve(self, tag: str, instructions: str, context: dict, output_format: dict) -> dict:
        if (why := self.halted()):
            raise BudgetRefused(f"pilot halted: {why}")
        if self.calls() >= self.max_calls:
            self.halt("call limit reached")
            raise BudgetRefused("call limit reached")
        in_tok = worst_case_input_tokens(instructions, context, output_format)
        out_tok = self.a.max_output_tokens
        w_tokens, w_usd = in_tok + out_tok, cost_usd(self.a, in_tok, out_tok)
        spent_tokens, spent_usd = self.spent()
        if spent_tokens + w_tokens > self.token_cap or spent_usd + w_usd > self.usd_cap:
            self.halt("next request could exceed a cap")
            raise BudgetRefused(f"refused: worst case {w_tokens} tokens / ${w_usd:.4f} exceeds remaining "
                                f"{self.token_cap - spent_tokens} tokens / ${self.usd_cap - spent_usd:.4f}")
        rid = f"r{self.calls() + 1:04d}"
        self._append({"type": "reserve", "id": rid, "tag": tag, "worst_input_tokens": in_tok, "max_output_tokens": out_tok,
                      "worst_tokens": w_tokens, "worst_usd": str(w_usd)})  # fsynced BEFORE the request is sent
        return {"id": rid, "worst_tokens": w_tokens, "worst_usd": w_usd, "input_bound": in_tok}

    def settle(self, reservation: dict, usage: Any) -> None:
        """Record actual usage. Missing, malformed or above-reservation usage charges the worst case and halts the pilot."""
        rid = reservation["id"]
        d = usage.to_dict() if hasattr(usage, "to_dict") else None
        ok = isinstance(d, dict) and all(isinstance(d.get(k), int) and not isinstance(d.get(k), bool) and d[k] >= 0
                                         for k in ("input_tokens", "output_tokens"))
        if not ok:
            self._append({"type": "settle", "id": rid, "measured": False, "charged_tokens": reservation["worst_tokens"],
                          "charged_usd": str(reservation["worst_usd"])})
            self.halt("usage missing or malformed: charged at worst case")
            return
        i, o = d["input_tokens"], d["output_tokens"]
        actual_usd = cost_usd(self.a, i, o)
        self._append({"type": "settle", "id": rid, "measured": True, "input_tokens": i, "output_tokens": o,
                      "charged_tokens": i + o, "charged_usd": str(actual_usd)})
        if i > reservation["input_bound"] or o > self.a.max_output_tokens:
            self.halt("actual usage exceeded its reservation (input bound or max_output_tokens is wrong)")

    def summary(self) -> dict:
        t, u = self.spent()
        return {"approval_id": self.a.approval_id, "model": self.a.model, "calls": self.calls(), "tokens_charged": t,
                "usd_charged": str(u), "token_cap": self.token_cap, "usd_cap": str(self.usd_cap),
                "halted": self.halted(), "unmeasured_calls": sum(e["type"] == "settle" and not e["measured"] for e in self.entries),
                "unsettled_reservations": sum(1 for e in self.entries if e["type"] == "reserve") -
                                          sum(1 for e in self.entries if e["type"] == "settle")}

    def close(self) -> None:
        os.close(self._fd)


class HaltedError(ReasoningError):
    pass


class Capped:
    """The only route to a provider. Reserve -> request -> settle; every failure path settles too."""

    def __init__(self, inner, budget, tag, log):
        if not hasattr(inner, "max_output_tokens"):
            raise BudgetRefused("provider cannot carry a hard max_output_tokens; a strict cap is not enforceable with it")
        self.inner, self.budget, self.tag, self.log = inner, budget, tag, log
        self.last_usage = None

    def cache_identity(self):
        return self.inner.cache_identity()

    def generate_structured_output(self, context, instructions, output_format):
        try:
            reservation = self.budget.reserve(self.tag, instructions, context, output_format)
        except BudgetRefused as exc:
            raise HaltedError(str(exc)) from exc
        self.inner.max_output_tokens = self.budget.a.max_output_tokens
        self.inner.last_usage = None  # never reuse the previous call's usage
        try:
            reply = self.inner.generate_structured_output(context, instructions, output_format)
        except BaseException as exc:  # includes KeyboardInterrupt: spend is recorded, never forgotten
            usage = getattr(exc, "usage", None) or getattr(self.inner, "last_usage", None)
            self.budget.settle(reservation, usage)
            raise
        self.last_usage = getattr(self.inner, "last_usage", None)
        self.budget.settle(reservation, self.last_usage)
        self.log.append({"tag": self.tag, "id": reservation["id"], "raw_reply": reply})
        return reply
