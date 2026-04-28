import asyncio
from gantry.compiler import *
from gantry.engine import *
from gantry.redaction import *
from gantry.schema import RetryConfig, RedactConfig, PolicySpec

import logging

log = logging.getLogger(__name__)


if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    def demo_observer(event: str, data: dict) -> None:
        log.info("[observer] %-20s %s", event, data)

    # -------------------------------------------------
    # Defined & compiled once at startup
    # -------------------------------------------------
    api_policy = load_policy(
        {
            "name": "external_api",
            "retry": {
                "max_attempts": 3,
                "wait_seconds": 0.05,
                "on_exceptions": ["TimeoutError", "ConnectionError"],
                "on_status_codes": [500, 502, 503],
            },
            "redact": {
                "full": ["token", "password"],
                "partial": ["email"],
                "hashed": ["user_id"],
            },
        },
        observer=demo_observer,
    )

    # -------------------------------------------
    # Sync example: retry on exception
    # -------------------------------------------
    call_count = 0

    @apply_policy(api_policy)
    def call_external_api(url: str, token: str, email: str) -> dict:
        global call_count
        call_count += 1
        if call_count < 3:
            raise TimeoutError("upstream timeout")
        return {"status_code": 200, "data": "ok"}

    print("\n=== Sync retry on TimeoutError ===")
    result = call_external_api(
        url="https://api.example.com/data",
        token="super-secret-jwt",
        email="alice@example.com",
    )
    print(f"Result: {result}  (took {call_count} attempts)\n")

    # -------------------------------------------
    # Sync example: result-based retry
    # -------------------------------------------
    flaky_count = 0

    @apply_policy(api_policy)
    def flaky_upstream(payload: dict) -> dict:
        global flaky_count
        flaky_count += 1
        return (
            {"status_code": 500}
            if flaky_count < 2
            else {"status_code": 200, "data": "recovered"}
        )

    print("=== Sync retry on status_code 500 ===")
    result = flaky_upstream(payload={"user_id": "u-12345", "password": "s3cr3t"})
    print(f"Result: {result}\n")

    # -------------------------------------------
    # Redaction test
    # -------------------------------------------
    print("=== Redaction ===")
    raw = {
        "token": "eyJhbGciOiJIUzI1NiJ9",
        "email": "alice@example.com",
        "user_id": "u-99887766",
        "password": "hunter2",
        "meta": {"token": "nested-token", "safe": "visible"},
    }
    redacted = redact_dict(raw, api_policy)
    for k, v in redacted.items():
        print(f"  {k:12s}: {v}")

    # -------------------------------------------
    # Async example
    # -------------------------------------------
    async def async_demo():
        async_count = 0

        @apply_policy(api_policy)
        async def async_fetch(url: str, token: str) -> dict:
            nonlocal async_count
            async_count += 1
            if async_count < 2:
                raise ConnectionError("connection refused")
            return {"status_code": 200, "body": "async ok"}

        print("\n=== Async retry on ConnectionError ===")
        r = await async_fetch(url="https://api.example.com", token="bearer-abc123")
        print(f"Result: {r}  (took {async_count} attempts)\n")

    asyncio.run(async_demo())
