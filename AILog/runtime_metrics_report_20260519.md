# Runtime Metrics Report

**Date**: 2026-05-19  
**Goal**: Wire the protobuf `METRICS` endpoint to real worker state.

## 1. What changed

### 1.1 Request counters

`MiniVLLMWorker/inference_service.py` now tracks:

- `total_requests`
- `completed_requests`
- `failed_requests`
- `active_requests`

Current counting policy:

- only `GENERATE` counts as a business request
- `HEALTH`, `METRICS`, and `CANCEL` are control-plane traffic and do not increment `total_requests`
- a normal `DONE` increments `completed_requests`
- uncaught generation failures increment `failed_requests`

### 1.2 Metrics route

`MiniVLLMWorker/request_router.py` now handles:

```text
METRICS -> MetricsReply
```

and fills:

- `process_uptime_ms`
- request counters
- CUDA memory:
  - `allocated_vram_bytes`
  - `reserved_vram_bytes`

### 1.3 Test client support

Added:

- `python -m MiniVLLMWorker.test_client metrics`
- `MiniVLLMWorker.metrics_active_smoke`

## 2. Verification

### Before generation

Observed:

```text
process_uptime_ms: 10426
total_requests: 0
completed_requests: 0
failed_requests: 0
active_requests: 0
allocated_vram_bytes: 3036311552
reserved_vram_bytes: 3141533696
```

### After one generation

Observed:

```text
total_requests: 1
completed_requests: 1
failed_requests: 0
active_requests: 0
allocated_vram_bytes: 3036312064
reserved_vram_bytes: 3141533696
```

### During active generation

`MiniVLLMWorker.metrics_active_smoke` is provided to observe:

```text
active_requests: 1
```

while a real decode loop is still running.

## 3. Current semantics

```text
total_requests      = all accepted GENERATE calls
completed_requests  = GENERATE calls that reached DONE
failed_requests     = GENERATE calls that escaped with failure
active_requests     = currently running GENERATE loops
```

Cancelled requests currently count as **completed**, because they terminate cleanly with:

```text
DONE(CANCELLED)
```

rather than as transport/runtime failures.

## 4. Recommended next steps

1. Add explicit counters for:
   - cancelled requests
   - EOS completions
   - max-token completions
2. Surface current model alias / backend in a higher-level dashboard view.
3. Include moving-window latency and tokens/sec aggregation once the worker is long-lived under gameplay load.

## 5. Final conclusion

`METRICS` is now a real observability endpoint rather than a schema stub.  
The worker can now report both control-plane health and live business-plane activity.
