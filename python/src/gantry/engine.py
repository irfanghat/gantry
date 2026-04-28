from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from gantry.compiler import *
from gantry.redaction import *
from gantry.schema import RetryConfig, RedactConfig, PolicySpec


# ------------------------------------------------------------
# NOTE
#
# [Execution Engine]
#
# Contains sync & async, as well as unified retry logic.
# ------------------------------------------------------------


class PolicyError(Exception):
    """All retry attempts exhausted. last_exception holds the final cause."""

    def __init__(self, message: str, last_exception: BaseException | None = None):
        super().__init__(message)
        self.last_exception = last_exception


def _retry_on_exc(exc: BaseException, policy: CompiledPolicy) -> bool:
    return bool(policy.exc_types) and isinstance(exc, policy.exc_types)


def _retry_on_result(result: Any, policy: CompiledPolicy) -> bool:
    """Check result dict for a status/status_code field against configured codes."""
    if not policy.status_codes or not isinstance(result, dict):
        return False
    code = result.get("status_code") or result.get("status")
    return code in policy.status_codes


def _notify(policy: CompiledPolicy, event: str, data: dict) -> None:
    """Fire observer; swallows exceptions — observers must never affect execution."""
    if policy.observer is not None:
        try:
            policy.observer(event, data)
        except Exception:
            pass


def _execute_sync(
    fn: Callable, args: tuple, kwargs: dict, policy: CompiledPolicy
) -> Any:
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = fn(*args, **kwargs)
            if _retry_on_result(result, policy):
                _notify(policy, "retry.result", {"attempt": attempt})
                if attempt < policy.max_attempts:
                    if policy.wait_seconds:
                        time.sleep(policy.wait_seconds)
                    continue
                raise PolicyError(f"[{policy.name}] result-based retry exhausted")
            _notify(policy, "success", {"attempt": attempt})
            return result
        except PolicyError:
            raise
        except BaseException as exc:
            last_exc = exc
            if _retry_on_exc(exc, policy) and attempt < policy.max_attempts:
                _notify(
                    policy, "retry.exception", {"attempt": attempt, "exc": repr(exc)}
                )
                if policy.wait_seconds:
                    time.sleep(policy.wait_seconds)
                continue
            raise
    raise PolicyError(f"[{policy.name}] retry exhausted", last_exc)


async def _execute_async(
    fn: Callable, args: tuple, kwargs: dict, policy: CompiledPolicy
) -> Any:
    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            result = await fn(*args, **kwargs)
            if _retry_on_result(result, policy):
                _notify(policy, "retry.result", {"attempt": attempt})
                if attempt < policy.max_attempts:
                    if policy.wait_seconds:
                        await asyncio.sleep(policy.wait_seconds)
                    continue
                raise PolicyError(f"[{policy.name}] result-based retry exhausted")
            _notify(policy, "success", {"attempt": attempt})
            return result
        except PolicyError:
            raise
        except BaseException as exc:
            last_exc = exc
            if _retry_on_exc(exc, policy) and attempt < policy.max_attempts:
                _notify(
                    policy, "retry.exception", {"attempt": attempt, "exc": repr(exc)}
                )
                if policy.wait_seconds:
                    await asyncio.sleep(policy.wait_seconds)
                continue
            raise
    raise PolicyError(f"[{policy.name}] retry exhausted", last_exc)


# --------------------------------------------------------------
# NOTE
#
# [Public Decorator]
#
# apply_policy()
#
# Detects sync vs async at decoration time, not per call.
# Redaction applied to kwargs before logging, never modifies the real call.
# --------------------------------------------------------------


def apply_policy(policy: CompiledPolicy) -> Callable:
    """
    Single unified decorator. Works transparently for sync and async functions.
    Redacts kwargs for the observer log only; the actual function receives
    the original unmodified arguments.

    Usage:
        policy = load_policy({...})

        @apply_policy(policy)
        def call_api(url, token): ...

        @apply_policy(policy)
        async def fetch(url, token): ...
    """

    def decorator(fn: Callable) -> Callable:
        is_async = asyncio.iscoroutinefunction(fn)

        if is_async:

            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                if policy.has_redaction and kwargs:
                    _notify(
                        policy,
                        "call",
                        {"fn": fn.__name__, "kwargs": redact_dict(kwargs, policy)},
                    )
                else:
                    _notify(policy, "call", {"fn": fn.__name__})
                return await _execute_async(fn, args, kwargs, policy)

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            if policy.has_redaction and kwargs:
                _notify(
                    policy,
                    "call",
                    {"fn": fn.__name__, "kwargs": redact_dict(kwargs, policy)},
                )
            else:
                _notify(policy, "call", {"fn": fn.__name__})
            return _execute_sync(fn, args, kwargs, policy)

        return sync_wrapper

    return decorator
