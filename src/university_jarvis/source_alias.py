"""Short source aliases for the model, real ids everywhere else.

Source ids are 36-character hex strings. A model asked to copy one occasionally changes a character
(a live REVISE run cited ``...d14d14c7ca0...`` for ``...eaa161d...``), and the citation validator then
rightly rejects the whole brief. The provider-facing side now sees ``SRC1``, ``SRC2`` ... and the output
schema restricts ``source_id`` to exactly those values, so a mis-copy cannot happen. Everything the model
returns is translated back before any validator, cache or record sees it, so provenance checks are
unchanged and operate on the real ids. An alias the model made up is not translated and is therefore
rejected as an unsupplied source, exactly as before.

Aliases that appear inside the model's prose are replaced by the material's file name, so an internal
identifier never reaches a student.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

_ALIAS = re.compile(r"\bSRC(\d+)\b")
_SOURCE_ID = re.compile(r"\bsrc-[0-9a-f]{8,}\b")


def _collect_ids(value: Any, found: dict[str, None]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("id", "source_id") and isinstance(child, str) and _SOURCE_ID.fullmatch(child):
                found.setdefault(child, None)
            else:
                _collect_ids(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_ids(child, found)


def _titles(value: Any, titles: dict[str, str]) -> None:
    if isinstance(value, dict):
        source_id, title = value.get("id") or value.get("source_id"), value.get("title")
        if isinstance(source_id, str) and isinstance(title, str) and title.strip():
            titles.setdefault(source_id, title)
        for child in value.values():
            _titles(child, titles)
    elif isinstance(value, list):
        for child in value:
            _titles(child, titles)


def _substitute(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        for real in sorted(mapping, key=len, reverse=True):
            if real in value:
                value = value.replace(real, mapping[real])
        return value
    if isinstance(value, dict):
        return {key: _substitute(child, mapping) for key, child in value.items()}
    if isinstance(value, list):
        return [_substitute(child, mapping) for child in value]
    return value


def _restore(value: Any, reverse: dict[str, str], titles: dict[str, str]) -> Any:
    if isinstance(value, dict):
        restored = {}
        for key, child in value.items():
            if key == "source_id" and isinstance(child, str) and child in reverse:
                restored[key] = reverse[child]
            else:
                restored[key] = _restore(child, reverse, titles)
        return restored
    if isinstance(value, list):
        return [_restore(child, reverse, titles) for child in value]
    if isinstance(value, str):
        def name(match: re.Match[str]) -> str:
            real = reverse.get(match.group(0))
            return titles.get(real, "your course material") if real else match.group(0)
        return _ALIAS.sub(name, value)
    return value


def _restrict_schema(schema: Any, aliases: list[str]) -> Any:
    if isinstance(schema, dict):
        out = {}
        for key, child in schema.items():
            if key == "properties" and isinstance(child, dict):
                out[key] = {
                    name: ({**sub, "enum": list(aliases)}
                           if name == "source_id" and isinstance(sub, dict) and sub.get("type") == "string"
                           else _restrict_schema(sub, aliases))
                    for name, sub in child.items()
                }
            else:
                out[key] = _restrict_schema(child, aliases)
        return out
    if isinstance(schema, list):
        return [_restrict_schema(child, aliases) for child in schema]
    return schema


class AliasingProvider:
    """Wraps any reasoning provider; transparent to callers (same identity, same usage reporting)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def inner(self) -> Any:
        return self._inner

    def cache_identity(self) -> dict[str, str]:
        return self._inner.cache_identity()

    @property
    def last_usage(self) -> Any:
        return getattr(self._inner, "last_usage", None)

    def __getattr__(self, name: str) -> Any:  # model, max_output_tokens, calls ... stay reachable
        return getattr(self._inner, name)

    def generate_structured_output(self, context: dict[str, Any], instructions: str,
                                   output_format: dict[str, Any]) -> dict[str, Any]:
        found: dict[str, None] = {}
        _collect_ids(context, found)
        if not found:
            return self._inner.generate_structured_output(context, instructions, output_format)
        mapping = {real: f"SRC{index}" for index, real in enumerate(found, start=1)}
        reverse = {alias: real for real, alias in mapping.items()}
        titles: dict[str, str] = {}
        _titles(context, titles)
        note = ("Sources are identified by short ids such as SRC1. Use them only in source_id fields; "
                "never write them in prose, refer to a material by what it is instead.")
        raw = self._inner.generate_structured_output(
            _substitute(context, mapping), f"{instructions}\n\n{note}",
            _restrict_schema(deepcopy(output_format), list(reverse)))
        return _restore(raw, reverse, titles)


def aliased(provider: Any) -> Any:
    if isinstance(provider, AliasingProvider) or getattr(provider, "handles_source_aliases", False):
        return provider
    return AliasingProvider(provider)
