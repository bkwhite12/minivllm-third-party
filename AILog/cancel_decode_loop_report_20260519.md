# Cancel Decode Loop Report

**Date**: 2026-05-19  
**Goal**: Make protobuf `CANCEL` requests interrupt an already-running real decode loop.

## 1. What changed

### 1.1 Active request tracking

`MiniVLLMWorker/inference_service.py` now keeps an active-request registry:

```text
request_id -> threading.Event
```

When a generation starts:

- a cancel event is registered
- the decode loop receives a callback that can observe that event

When generation finishes:

- the request is removed from the active registry

### 1.2 Real cancel routing

`MiniVLLMWorker/request_router.py` now handles:

```text
CANCEL -> CANCEL_REPLY
```

and forwards:

```text
cancel.target_request_id
```

to `InferenceService.cancel(...)`.

### 1.3 Decode loop interruption

`WindowsKernelPack/upstream_adapter.py` now checks cancellation before each decode step.

If a request is cancelled:

- the partial generated text is preserved
- `GenerationCancelledError` is raised
- the worker finishes with:
  - `finish_reason = CANCELLED`

### 1.4 Test client support

Added:

- `MiniVLLMWorker.test_client cancel --target-request-id ...`
- `MiniVLLMWorker.cancel_smoke`

The smoke test opens:

1. one pipe connection for a long-running `GENERATE`
2. a second pipe connection that sends `CANCEL`

## 2. Verification

Test:

```powershell
python -m MiniVLLMWorker.cancel_smoke
```

Observed sequence:

```text
TOKEN
TOKEN
TOKEN
TOKEN
TOKEN
CANCEL_REPLY accepted=true
TOKEN
DONE finish_reason=CANCELLED
```

Representative result:

```text
target_request_id = req-f251a6dd-1a47-4dd8-8af9-17457d9ee446
cancel accepted     = true
generated_tokens    = 6
finish_reason       = CANCELLED
total_latency_ms    = 57
```

## 3. Current behavior

The worker now supports:

```text
GENERATE on connection A
CANCEL on connection B
decode loop stops before the next decode step
DONE returns CANCELLED
```

This is now a real cancellation path, not only a protocol placeholder.

## 4. Important nuance

Cancellation is checked **between decode steps**, not inside a GPU kernel already in flight.

That means:

- one additional token may still arrive after `CANCEL_REPLY`
- cancellation latency is bounded by the current decode step duration

This is the right boundary for the current architecture.

## 5. Recommended next steps

1. Track raw token count separately from emitted visible chunks.
2. Surface active request count in `METRICS`.
3. Add cancellation coverage to the future Unity client.
4. Consider session-level cancellation helpers if one gameplay action may map to multiple model requests.

## 6. Final conclusion

`CANCEL` is now fully wired into the real generation path:

```text
protobuf request
  -> router
  -> active request registry
  -> decode loop cancellation check
  -> DONE(CANCELLED)
```

The worker can now be interrupted while it is genuinely generating.
