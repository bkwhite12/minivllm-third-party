# Load Model Report

**Date**: 2026-05-19  
**Goal**: Turn protobuf `LOAD_MODEL` from a schema placeholder into a real runtime operation.

## 1. What changed

### 1.1 Alias registry

`MiniVLLMWorker/request_router.py` now owns a narrow model registry:

```text
model_alias -> config_path
```

The worker entrypoint registers the startup model automatically when:

- `MINIVLLM_CONFIG_PATH`
- `MINIVLLM_MODEL_ALIAS`

are provided.

### 1.2 Real `LOAD_MODEL` routing

`RequestRouter` now handles:

```text
LOAD_MODEL -> LOAD_MODEL_REPLY
```

Behavior:

- known alias:
  - calls `adapter.load_model_from_config(...)`
  - updates worker runtime info
  - returns `loaded = true`
- unknown alias:
  - returns `loaded = false`
  - returns a clear message

### 1.3 Test client support

Added:

```powershell
python -m MiniVLLMWorker.test_client load-model --model-alias qwen3-0.6b
```

## 2. Verification

### Known alias

Observed:

```text
type: LOAD_MODEL_REPLY
loaded: true
model_alias: "qwen3-0.6b"
backend: "megakernel_cuda"
message: "loaded"
```

### Unknown alias

Observed:

```text
type: LOAD_MODEL_REPLY
model_alias: "unknown-model"
message: "unknown model alias: unknown-model"
```

### Health after load

Observed:

```text
active_model: "qwen3-0.6b"
backend: "megakernel_cuda"
kernel_pack_id: "cp312-cu128-sm120"
```

## 3. Current scope

This is the first real runtime loading shape:

- it proves the protocol path
- it proves the worker can load on command
- it intentionally keeps registration narrow and explicit

What it does **not** yet provide:

- arbitrary path-based loading from the wire
- unload / swap policy
- concurrent request drain before reload
- multiple pre-registered aliases from a manifest

## 4. Recommended next steps

1. Add a model registry manifest on disk.
2. Reject or defer `LOAD_MODEL` while active generations are running.
3. Add explicit reload semantics:
   - same alias no-op
   - different alias replace current model
4. Add warmup behavior for `load_model.warmup = true`.

## 5. Final conclusion

`LOAD_MODEL` is now a real worker capability, not just a future-looking protocol field.  
The next layer is policy, not plumbing.
