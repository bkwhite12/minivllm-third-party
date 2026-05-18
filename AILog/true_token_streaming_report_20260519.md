# True Token Streaming Report

**Date**: 2026-05-19  
**Goal**: Replace the previous one-chunk completion bridge with real token-by-token streaming.

## 1. What changed

### 1.1 Adapter-side streaming loop

`WindowsKernelPack/upstream_adapter.py` now exposes:

```python
stream_generate_tokens(...)
```

Instead of calling upstream `ModelRunner.inference()` and waiting for final text, the adapter now reuses upstream primitives directly:

- prefill
- sampler
- `run_decode(...)`
- EOS detection

and yields `GeneratedToken` items as each token becomes available.

### 1.2 Worker now forwards real token chunks

`MiniVLLMWorker/inference_service.py` no longer wraps the final completion into one synthetic chunk when a real model is loaded.

It now emits one protobuf `TOKEN` reply per generated token:

- `text`
- `token_id`
- `index`
- `is_special`

## 2. Verification

Worker was launched in release mode with:

- real local model
- prebuilt megakernel
- `kernel_pack_id = cp312-cu128-sm120`

Test command:

```powershell
python -m MiniVLLMWorker.test_client generate --prompt "Hello"
```

Observed reply sequence:

```text
TOKEN 0: " Answer"
TOKEN 1: "!"
TOKEN 2: " I"
TOKEN 3: "'m"
TOKEN 4: " a"
DONE
```

Observed metrics:

- `generated_tokens = 5`
- `ttft_ms = 17`
- `total_latency_ms = 31`
- `tokens_per_sec = 161.29`

## 3. Current architecture

```text
Named Pipe request
  -> RequestRouter
  -> InferenceService.stream_generate()
  -> UpstreamMiniVllmAdapter.stream_generate_tokens()
  -> prefill + iterative decode
  -> one TOKEN protobuf per generated token
  -> DONE
```

## 4. Important notes

### 4.1 This is now real streaming

The previous path behaved as:

```text
model generates everything
worker sends one TOKEN chunk
worker sends DONE
```

The new path behaves as:

```text
model generates token N
worker immediately sends TOKEN N
repeat until stop
worker sends DONE
```

### 4.2 Text emission uses incremental decode deltas

The adapter decodes the growing token list and emits only the text delta since the previous step.  
This avoids sending repeated prefixes while still handling tokenizer behavior correctly enough for the current model path.

### 4.3 One subtlety remains

`generated_tokens` currently counts emitted chunks.  
If a future tokenizer step yields an empty visible-text delta for a special token, transport-visible chunk count and raw token count may diverge. That is acceptable for the current closure test, but worth tightening before production metrics are finalized.

## 5. Recommended next steps

1. Add cancellation support so a `CANCEL` request can interrupt the decode loop.
2. Separate:
   - raw generated token count
   - emitted visible chunk count
3. Add a Unicode regression test for:
   - Chinese
   - emoji
   - partial-byte / merged-token boundaries
4. Add a Unity-side incremental rendering test so the game UI paints each arriving token as intended.

## 6. Final conclusion

The worker now supports **true token-by-token streaming** over:

```text
Windows Named Pipe + Protobuf + real model inference
```

This removes the last major semantic mismatch between the external protocol and the actual model execution path.
