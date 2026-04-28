# Architecture Design

Policy-driven execution for Python, C++ & Rust. Retry, redaction, and flow control through a single compiled **decorator**/**attribute**. Designed for ease of use, and clean ergonomics.

---

## Project Structure

```
gantry/src/
├── __init__.py       # Public API: load_policy, apply_policy, PolicyError
├── schema.py         # PolicySpec, RetryConfig, RedactConfig
├── compiler.py       # load_policy() i.e. The CompiledPolicy
├── engine.py         # _execute_sync, _execute_async, PolicyError
├── redaction.py      # redact_dict, masking strategies
└── hooks.py          # Observer protocol, built-in logging hook
```

## Core Components

### `PolicySpec` / `RetryConfig` / `RedactConfig`
Frozen dataclasses. Immutable, hashable, safe to share across threads.
These are the **human-facing** config objects - plain, validated **Python**/C++/Rust data.

### `CompiledPolicy`
The **hot-path** object. Built once per policy definition; reused for every
function call. Uses `__slots__` to eliminate `__dict__` overhead. All fields
are pre-resolved:

| Raw spec field          | Compiled form              | Why                         |
|-------------------------|----------------------------|-----------------------------|
| `"TimeoutError"`        | `TimeoutError` (class)     | `isinstance()` needs a class |
| `[500, 502]`            | `frozenset({500, 502})`    | O(1) membership test        |
| `["token", "password"]` | `frozenset({"token", ...})`| O(1) dict key lookup        |

### `PolicyEngine` (interface boundary)
The sync/async execution loops are plain functions today. For the Rust backend,
this becomes a Protocol:

```python
class PolicyEngine(Protocol):
    def execute_sync(self, fn, args, kwargs, policy: CompiledPolicy) -> Any: ...
    async def execute_async(self, fn, args, kwargs, policy: CompiledPolicy) -> Any: ...
```

Swapping in a Rust engine is then a one-line change in `__init__.py`.

---

## Data Flow

```
Decoration time (once):
  load_policy(dict) ──> validate ──> resolve exc classes ──> build frozensets
                                                           └──> CompiledPolicy

Call time (every request):
  wrapper(*args, **kwargs)
    │
    ├─ [if has_redaction] redact_dict(kwargs) ──> notify observer
    │
    └─ execute_sync / execute_async
         │
         ├── attempt 1: fn(*args, **kwargs)
         │     ├── exception? -> _retry_on_exc() -> sleep -> retry
         │     └── result?    -> _retry_on_result() -> sleep -> retry
         │
         ├── attempt N: fn(*args, **kwargs) ──> return result
         │
         └── exhausted ──> raise PolicyError(last_exception=...)
```

**Key invariant:** the original `args` and `kwargs` are **never modified**.
Redaction only touches a shallow copy used for the observer log.

---

## Policy Schema Design

```yaml
# Complete schema with all fields

name: "external_api"          # For logging / tracing

retry:
  max_attempts:   3           # Total attempts (1 means no retry)
  wait_seconds:   0.5         # Fixed sleep between attempts
                              # (jitter/backoff: Will be available in engine v2)
  on_exceptions:              # Retry only on these exception types
    - TimeoutError
    - requests.exceptions.ConnectionError
  on_status_codes:            # Retry if result dict contains any of these status codes
    - 500
    - 502
    - 503

redact:
  full:    [token, password, secret]   # Replaced with "***"
  partial: [email, phone]              # "alice@..." -> "al***"
  hashed:  [user_id, account_id]       # SHA-256[:8] - deterministic but opaque
```

**Schema rules enforced at compile time:**
- `max_attempts >= 1`
- `wait_seconds >= 0`
- Every string in `on_exceptions` must resolve to an `BaseException` subclass
- No overlap between `full`, `partial`, `hashed` sets (warning, not error)

**Extension point - custom retry rule (v2):**
```yaml
retry:
  custom_rule: "myapp.policies.rules.retry_on_quota_error"
```
Compiled as: `importlib.import_module(...).retry_on_quota_error` (a callable).
Called in engine as: `custom_rule(result, exc) -> bool`.

---

## Compilation Step - `load_policy()` in detail

```python
load_policy(spec) -> CompiledPolicy

Step 1: Normalize
  dict  -> RetryConfig + RedactConfig dataclasses
  (Already a PolicySpec? use directly)

Step 2: Validate
  max_attempts >= 1
  wait_seconds >= 0.0

Step 3: Resolve exception types
  "TimeoutError" -> builtins.TimeoutError
  "requests.exceptions.Timeout" -> importlib.import_module(...) + getattr
  Unknown -> raise ValueError at startup, not at runtime

Step 4: Build frozensets
  list["token", "password"] -> frozenset({"token", "password"})
  list[500, 502] -> frozenset({500, 502})
  frozenset is immutable, thread-safe, O(1) lookup

Step 5: Return CompiledPolicy
  All fields are value types or immutable containers.
  Safe to share across threads with no locking.
```

**Cost model:** `load_policy` is O(k) where k = number of policy fields.
It runs once at module import. Per-call cost is zero parsing.

---

## Execution Engine Design

### Retry loop structure

```
for attempt in range(1, max_attempts + 1):
    try:
        result = fn(...)            # or: await fn(...)

        if _retry_on_result(result):   # status_code check - O(1)
            if attempt < max_attempts:
                sleep(wait_seconds)
                continue
            raise PolicyError(...)

        notify("success", ...)
        return result

    except PolicyError:
        raise                          # never swallow gantry's errors

    except BaseException as exc:
        if _retry_on_exc(exc) and attempt < max_attempts:
            notify("retry.exception", ...)
            sleep(wait_seconds)
            continue
        raise                          # propagate non-retryable exceptions
```

### Why `BaseException` instead of `Exception`?
`KeyboardInterrupt` and `SystemExit` should not be silently swallowed.
We catch `BaseException` only to check `_retry_on_exc()`, then re-raise
immediately if it doesn't match.

### Async is identical logic, `await asyncio.sleep` instead of `time.sleep`
Both loops are hand-written, not shared via template, to avoid any per-call
branching or `inspect` overhead in the hot path.

---

## Redaction Engine Design

### Strategy: one shallow copy, with in-place mutation

```
redact_dict(data, policy):
  ① if not has_redaction: return data        ← zero-cost fast path
  ② out = data.copy()                        ← ONE allocation, O(n) keys
  ③ _redact_node(out, policy)                ← mutate in place
  ④ return out

_redact_node(obj, policy):
  for key, val in obj.items():
    if key in full_fields:    obj[key] = "***"         ← O(1) frozenset
    elif key in partial_fields: obj[key] = mask_partial(val)
    elif key in hashed_fields:  obj[key] = sha256[:8]
    elif isinstance(val, dict): recurse(_redact_node)
    elif isinstance(val, list): recurse(_redact_list)
```

**No `copy.deepcopy`.** Deep copy is O(n × depth) and triggers `__deepcopy__`
hooks on every object. Our approach is O(n) with a single allocation.

**No regex.** Field names are matched with `in frozenset` - 40ns vs 400ns for
a compiled regex match.

### Masking strategies

| Strategy | Output | Use case |
|----------|--------|----------|
| `full`   | `***`  | Credentials, tokens - no info leaked |
| `partial`| `al***`| PII where first chars help debugging (email, phone) |
| `hashed` | `a3f2b1c8` | IDs - consistent across log lines, non-reversible |

---

## Performance Considerations

| Concern | Solution |
|---------|----------|
| Repeated string parsing | Compile once in `load_policy` |
| Exception type checks | `isinstance(exc, tuple_of_types)` |
| Field name lookups | `frozenset` - O(1) hash table |
| Dict copying | Shallow copy only at top level |
| No-redaction path | `has_redaction` property short-circuits everything |
| Per-call overhead | Zero: no `inspect`, no parsing, no lambda eval |
| Async detection | Done at decoration time via `iscoroutinefunction`, not per call |
| `__slots__` | `CompiledPolicy` has no `__dict__` - faster attribute access, smaller memory |
| Observer calls | Guarded by `if policy.observer is not None` - branch predictor-friendly |

**Benchmark target:** < 500 ns overhead per call with no retries and no redaction.
With redaction on a 10-key dict: < 2 µs.

---

## Extensibility Hooks (WIP)

### Observer protocol
```python
def my_observer(event: str, data: dict) -> None:
    ...

policy = load_policy(spec, observer=my_observer)
```

Events emitted:
- `"call"` - function invoked; `data = {fn, kwargs (redacted)}`
- `"retry.exception"` - retrying after exception; `data = {attempt, exc}`
- `"retry.result"` - retrying after result check; `data = {attempt}`
- `"success"` - completed; `data = {attempt}`

Built-in observers (in `hooks.py`):
```python
structured_log_observer   # JSON lines to stdlib logging
opentelemetry_observer    # span attributes & events
statsd_observer           # counters & histograms
```

### Custom retry rule
```python
def retry_on_quota(result, exc) -> bool:
    return isinstance(exc, QuotaExceededError) or (
        isinstance(result, dict) and result.get("code") == "QUOTA_EXCEEDED"
    )

policy = load_policy({
    "retry": {"max_attempts": 5, "custom_rule": retry_on_quota}
})
```

---

## FastAPI Integration Pattern

```python
# ----------------------------------------
# Define once at app startup
# ----------------------------------------
auth_policy = load_policy(yaml.safe_load(open("policies/auth.yaml")))

router = APIRouter()

@router.post("/login")
@apply_policy(auth_policy)
async def login(body: LoginRequest):
    return await auth_service.authenticate(body.username, body.password)
```

**Middleware variant** (apply policy to all routes):
```python
class PolicyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, policy: CompiledPolicy):
        super().__init__(app)
        self._policy = policy

    async def dispatch(self, request, call_next):
        return await _execute_async(call_next, (request,), {}, self._policy)
```

---

## Key Design Tradeoffs

| Decision | Chosen | Alternative | Why |
|----------|--------|-------------|-----|
| Compile step | Explicit `load_policy()` | Lazy on first call | Fail at startup |
| Retry loop | Hand-written sync & async | Shared template | Avoids per-call branching |
| Wait strategy | Fixed sleep | Exponential & jitter | Jitter is a one-line extension, keep core simple |
| Redaction copy | Shallow top-level | Deep copy | Faster, nested dicts rarely need isolation |
| Field matching | `frozenset` | Compiled regex | Names are exact matches, not patterns |
| Async detection | At decoration time | Per call | Zero overhead in hot path |
| Observer | Optional callable | Mandatory | Non-observing paths pay zero cost |
