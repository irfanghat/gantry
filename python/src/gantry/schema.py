from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)

# ------------------------------------------------------------
# NOTE
#
# [Schema Definition]
#
# [Structured], [typed] policy definition.
# Frozen dataclasses: [hashable], safe to share across threads.
# ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int = 1
    wait_seconds: float = 0.0
    on_exceptions: tuple[str, ...] = ()     # resolved at compile time
    on_status_codes: tuple[int, ...] = ()   # matched against result dict


@dataclass(frozen=True, slots=True)
class RedactConfig:
    full:    tuple[str, ...] = ()   # maps to: "***"
    partial: tuple[str, ...] = ()   # maps to: "ab***" (First 2 chars kept)
    hashed:  tuple[str, ...] = ()   # maps to: sha256[:8]


@dataclass(frozen=True, slots=True)
class PolicySpec:
    retry:  RetryConfig  = field(default_factory=RetryConfig)
    redact: RedactConfig = field(default_factory=RedactConfig)
    name:   str          = "unnamed"