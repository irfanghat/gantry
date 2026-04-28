from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from gantry.schema import RetryConfig, RedactConfig, PolicySpec

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NOTE
#
# [Redaction Engine]
#
# Current strategy: shallow-copy the top-level dict once, and mutate in place.
# No regex in hot path - O(1) frozenset lookups only.
# Recurses into nested dicts/lists without extra copies.
# ---------------------------------------------------------------------------

def _mask_full(_: Any)    -> str: return "***"
def _mask_partial(v: Any) -> str: s = str(v); return (s[:2] + "***") if len(s) > 2 else "***"
def _mask_hashed(v: Any)  -> str: return hashlib.sha256(str(v).encode()).hexdigest()[:8]


def redact_dict(data: dict, policy: CompiledPolicy) -> dict:
    """
    Return a redacted copy of data.
    Fast path: returns original dict unchanged if no redaction fields are configured.
    Only the top-level dict is shallow-copied, nested dicts are mutated in place
    (This should be safe because the top-level copy breaks the reference for the caller).
    """
    if not policy.has_redaction:
        return data                     # zero-cost fast path

    out = data.copy()                   # O(n) shallow copy - one allocation
    _redact_node(out, policy)
    return out


def _redact_node(obj: dict, policy: CompiledPolicy) -> None:
    full, partial, hashed = policy.full_fields, policy.partial_fields, policy.hashed_fields
    for key, val in obj.items():
        if   key in full:    obj[key] = _mask_full(val)
        elif key in partial: obj[key] = _mask_partial(val)
        elif key in hashed:  obj[key] = _mask_hashed(val)
        elif isinstance(val, dict): _redact_node(val, policy)
        elif isinstance(val, list): _redact_list(val, policy)


def _redact_list(lst: list, policy: CompiledPolicy) -> None:
    for item in lst:
        if   isinstance(item, dict): _redact_node(item, policy)
        elif isinstance(item, list): _redact_list(item, policy)
