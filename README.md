# Gantry

![Logo](https://github.com/irfanghat/gantry/blob/main/docs/images/logo-transparent.png)

**Policy-driven execution for Python, C++, C#, Go, Node (JS) and Rust.**
Add retries, redaction, and flow control to any function using a single decorator/attribute.

Built for:

* **Minimal overhead in the hot path**
* **Clear, declarative policies**
* **Cross-language consistency**


## Why Gantry?

Instead of scattering retry logic, logging, and masking across your codebase, Gantry lets you define everything in one place:

```yaml
retry:
  max_attempts: 3
  wait_seconds: 0.5
  on_exceptions:
    - TimeoutError

redact:
  full: [token, password]
```

Apply it once:

```python
@apply_policy(policy)
def call_api(...):
    ...
```

That’s it, retry, redaction & observability handled.


## Core Idea

Gantry separates **configuration** from **execution**:

1. **Define policy** (human-friendly)
2. **Compile once** (optimized, immutable)
3. **Execute many times** (zero parsing, minimal overhead)


## How It Works

### 1. Compile (Once at startup)

```python
policy = load_policy(spec)
```

* Validates config
* Resolves exception types
* Converts lists -> `frozenset` (fast lookups)
* Produces a **CompiledPolicy** (immutable, thread-safe)


### 2. Apply (Decorate your function)

```python
@apply_policy(policy)
def fn(...):
    ...
```


### 3. Execute (Every call)

At runtime Gantry:

1. Optionally **redacts inputs** (for logging only)
2. Calls your function
3. Retries if needed:

   * on exceptions
   * on result (e.g. status codes)
4. Emits observer events
5. Returns result or raises `PolicyError`


## Example

```python
policy = load_policy({
    "retry": {
        "max_attempts": 3,
        "wait_seconds": 0.5,
        "on_exceptions": ["TimeoutError"]
    },
    "redact": {
        "full": ["password"]
    }
})

@apply_policy(policy)
def login(username, password):
    ...
```


## Key Features

### Retry Control

* Retry on **exceptions**
* Retry on **result values** (e.g. HTTP 500)
* Deterministic, simple loop (no hidden magic)

### Redaction

* `full` -> `"***"`
* `partial` -> `"al***"`
* `hashed` -> deterministic short hash

Only affects **logs**, never your actual data.

### Zero-Cost Abstractions

* No parsing at runtime
* No reflection (`inspect`) per call
* No deep copies
* Fast O(1) lookups via `frozenset`


## Performance

Designed for hot paths:

* **< 500 ns** overhead (no retry, no redaction)
* **< 2 µs** with redaction (~10 fields)

Key optimizations:

* Compile once
* Immutable structures (`frozenset`, `__slots__`)
* Separate sync/async paths (no branching)


## Extensibility

### Observers (logging, metrics, tracing)

```python
def observer(event, data):
    ...

policy = load_policy(spec, observer=observer)
```

Events:

* `call`
* `retry.exception`
* `retry.result`
* `success`


### Custom Retry Logic

```python
def retry_on_quota(result, exc):
    return ...

policy = load_policy({
    "retry": {
        "max_attempts": 5,
        "custom_rule": retry_on_quota
    }
})
```


## Design Principles

* **Fail fast** -> invalid configs crash at startup
* **Immutable by default** -> safe across threads
* **Explicit over magic** -> simple retry loop
* **Pay for what you use** -> no redaction = zero cost
* **Cross-language parity** -> same model in Python, C++, Rust


## When to Use

Use Gantry when you need:

* Reliable external API calls
* Centralized retry policies
* Safe logging (PII masking)
* Consistent behavior across services/languages


## When Not to Use

* Complex workflow orchestration (use a job system)
* Stateful retries or distributed coordination (Might be worth looking into)
* Cases needing dynamic per-call policy changes


## Summary

Gantry gives you:

* **One place** to define behavior
* **One decorator** to apply it
* **Minimal runtime overhead**

Clean, and predictable.
