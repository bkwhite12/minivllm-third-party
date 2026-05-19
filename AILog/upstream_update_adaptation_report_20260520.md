# Upstream Update Adaptation Report

**Date**: 2026-05-20  
**Target**: `F:\CTest\minivllm`  
**Action**: Pull upstream update and re-run the Windows adaptation checks.

## 1. Git update result

Command used:

```powershell
git -c safe.directory=F:/CTest/minivllm -C F:\CTest\minivllm pull --ff-only
```

Result:

```text
6eef241..151da0f  main -> origin/main
Fast-forward
model/qwen3_megakernel.py | 5 ++++-
```

Current upstream commit:

```text
151da0f Merge pull request #3 from BoundlessWindMoon/refactor
```

## 2. Upstream change summary

The update only touched:

```text
model/qwen3_megakernel.py
```

The meaningful change is memory cleanup after megakernel weight extraction:

```python
del base_model
torch.cuda.empty_cache()
```

Interpretation:

- no protobuf change
- no worker protocol change
- no CUDA extension source change
- no megakernel exported ABI change
- no prebuilt `.pyd` rebuild required for this update

## 3. Adaptation checks

### 3.1 Prebuilt loader

Result:

```text
prebuilt_load=PASS
module=mini_vllm_mk_default
exports=PASS
```

### 3.2 Release-mode prebuilt selection

Result:

```text
kernel_pack= cp312-cu128-sm120
module= mini_vllm_mk_all_combined
```

This confirms the Windows adapter still prefers the prebuilt kernel pack in release mode.

### 3.3 Triton warmup

Result:

```text
vec_add: PASS
matmul: FAIL  max_diff=0.062309
silu: PASS
softmax: FAIL max_diff=0.120474
autotune_relu: PASS
bf16_kernel: PASS
```

Interpretation:

- same pattern as before
- Triton compile/runtime path remains functional
- `matmul` and `softmax` failures are still toy-kernel numerical mismatch issues, not evidence of a broken Triton Windows runtime

### 3.4 Worker startup and real model load

Result:

```text
model weights loaded
Named pipe server listening on \\.\pipe\minivllm-runtime
```

### 3.5 Health

Result:

```text
state: READY
active_model: qwen3-0.6b
backend: megakernel_cuda
kernel_pack_id: cp312-cu128-sm120
```

### 3.6 Generate / streaming

Prompt:

```text
Hello
```

Result:

```text
TOKEN x5
DONE finish_reason=MAX_TOKENS
text="Hello Answer! I'm a"
```

### 3.7 LOAD_MODEL

Result:

```text
loaded: true
model_alias: qwen3-0.6b
backend: megakernel_cuda
message: loaded
```

### 3.8 CANCEL

Result:

```text
CANCEL_REPLY accepted=true
DONE finish_reason=CANCELLED
```

### 3.9 METRICS

Result after generate + cancel smoke:

```text
total_requests:      2
completed_requests:  2
cancelled:           1
eos_completions:     0
max_token:           1
failed_requests:     0
active_requests:     0
```

## 4. Notes

One parallel `HEALTH` attempt hit:

```text
ERROR_PIPE_BUSY
```

when multiple Python test clients raced the pipe at the same time. A sequential retry succeeded. This does not indicate an adapter regression; it is a test-client concurrency/race artifact.

## 5. Final verdict

The upstream update is compatible with the current Windows adaptation.

No code changes were required in:

- `WindowsKernelPack`
- `MiniVLLMWorker`
- Unity client
- protobuf protocol
- prebuilt kernel pack

The full native Windows path remains valid:

```text
Named Pipe + Protobuf
  -> MiniVLLMWorker
  -> WindowsKernelPack adapter
  -> prebuilt megakernel cp312-cu128-sm120
  -> Qwen3-0.6B real inference
```
