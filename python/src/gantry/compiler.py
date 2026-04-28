from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from gantry.schema import RetryConfig, RedactConfig, PolicySpec

# ---------------------------------------------------------------------------
# NOTE
#
# [Compiled Policy]
#
# hot-path object, built once, reused forever.
#
# All expensive work (import resolution, set construction) happens here.
# __slots__ keeps instances small; no __dict__ overhead.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CompiledPolicy:
    name: str
    max_attempts: int
    wait_seconds: float
    exc_types: tuple[type[BaseException], ...]  # resolved classes, not strings
    status_codes: frozenset[int]  # O(1) membership test
    full_fields: frozenset[str]
    partial_fields: frozenset[str]
    hashed_fields: frozenset[str]
    observer: Callable[[str, dict], None] | None = None

    @property
    def has_redaction(self) -> bool:
        # ---------------------------------------------------------------
        # Evaluated once per call, boolean OR on frozensets is O(1)
        # ---------------------------------------------------------------
        return bool(self.full_fields or self.partial_fields or self.hashed_fields)


# ---------------------------------------------------------------------------
# NOTE
#
# load_policy()
#
# Validates, normalizes, resolves exception types, builds frozensets.
# Never called in the hot path.
# ---------------------------------------------------------------------------


def _resolve_exc(name: str) -> type[BaseException]:
    """Resolve 'TimeoutError' or 'requests.exceptions.Timeout' to its class."""
    import builtins

    builtin = getattr(builtins, name, None)
    if isinstance(builtin, type) and issubclass(builtin, BaseException):
        return builtin

    # ----------------------------------------------
    # Dotted import path: "module.ClassName"
    # ----------------------------------------------
    parts = name.rsplit(".", 1)
    if len(parts) == 2:
        import importlib

        mod = importlib.import_module(parts[0])
        cls = getattr(mod, parts[1])
        if isinstance(cls, type) and issubclass(cls, BaseException):
            return cls
    raise ValueError(f"Cannot resolve exception type: {name!r}")


def load_policy(
    spec: dict | PolicySpec,
    observer: Callable[[str, dict], None] | None = None,
) -> CompiledPolicy:
    """
    Compile a policy spec into an optimized runtime object.
    This should be called ONCE at module load, never inside a request handler or
    recursive function calls.

    Args:
        spec:     dict (from YAML/JSON/config) or a PolicySpec dataclass.
        observer: optional callable(event_name, data_dict) for hooks.

    Returns:
        CompiledPolicy - immutable, thread-safe, zero per-call overhead.
    """
    if isinstance(spec, dict):
        r = spec.get("retry", {})
        d = spec.get("redact", {})
        retry = RetryConfig(
            max_attempts=int(r.get("max_attempts", 1)),
            wait_seconds=float(r.get("wait_seconds", 0.0)),
            on_exceptions=tuple(r.get("on_exceptions", [])),
            on_status_codes=tuple(r.get("on_status_codes", [])),
        )
        redact = RedactConfig(
            full=tuple(d.get("full", [])),
            partial=tuple(d.get("partial", [])),
            hashed=tuple(d.get("hashed", [])),
        )
        name = spec.get("name", "unnamed")
    else:
        retry, redact, name = spec.retry, spec.redact, spec.name

    if retry.max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if retry.wait_seconds < 0:
        raise ValueError("wait_seconds must be >= 0")

    return CompiledPolicy(
        name=name,
        max_attempts=retry.max_attempts,
        wait_seconds=retry.wait_seconds,
        exc_types=tuple(_resolve_exc(n) for n in retry.on_exceptions),
        status_codes=frozenset(retry.on_status_codes),
        full_fields=frozenset(redact.full),
        partial_fields=frozenset(redact.partial),
        hashed_fields=frozenset(redact.hashed),
        observer=observer,
    )
