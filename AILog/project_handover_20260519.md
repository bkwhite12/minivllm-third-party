# Project Handover

**Date**: 2026-05-19  
**Project goal**: Run upstream `minivllm` natively on Windows for future Unity integration, with Named Pipe IPC, Protobuf protocol, minimal upstream modification, and retained high-performance kernels.

## 1. Current state in one sentence

The project now has a working Windows-native runtime skeleton:

```text
Named Pipe + Protobuf
  -> real model loading
  -> prebuilt Windows megakernel
  -> true token streaming
  -> cancellation
  -> live metrics
```

## 2. Verified environment baseline

| Component | Version |
|---|---|
| Python | 3.12.10 |
| PyTorch | 2.9.1 + cu128 |
| CUDA Runtime | 12.8 |
| CUDA Toolkit | 12.8.1 |
| triton-windows | 3.5.1.post24 |
| transformers | 4.51.0 |
| huggingface-hub | 0.36.2 |
| Visual Studio | Community 2022 17.14.5 |
| MSVC | 14.44.35207 / v143 |
| Ninja | 1.13.0 |
| Verified GPU | RTX 5070 / sm120 |

## 3. Implemented modules

### Protocol

- `Protocol/minivllm_runtime.proto`
- `Protocol/python_generated/minivllm_runtime_pb2.py`

### Worker

- `MiniVLLMWorker/main.py`
- `MiniVLLMWorker/pipe_server.py`
- `MiniVLLMWorker/protocol_codec.py`
- `MiniVLLMWorker/request_router.py`
- `MiniVLLMWorker/inference_service.py`
- `MiniVLLMWorker/test_client.py`
- `MiniVLLMWorker/cancel_smoke.py`
- `MiniVLLMWorker/metrics_active_smoke.py`

### Windows runtime adaptation

- `WindowsKernelPack/bootstrap.py`
- `WindowsKernelPack/upstream_adapter.py`
- `WindowsKernelPack/prebuilt_loader.py`
- `WindowsKernelPack/warmup_triton.py`
- `WindowsKernelPack/smoke_megakernel.py`
- `WindowsKernelPack/run_smoke_megakernel_vsdev.cmd`

### Prebuilt kernel artifacts

```text
WindowsKernelPack/prebuilt/cp312-cu128-sm120/
  ├─ mini_vllm_mk_default.cp312-win_amd64.pyd
  ├─ mini_vllm_mk_all_combined.cp312-win_amd64.pyd
  └─ kernel_manifest.json
```

## 4. What is already proven

### IPC

- Raw Windows Named Pipe works
- Framing is:
  - `[uint32 little-endian length][protobuf payload]`
- Python test client already exercises:
  - `HELLO`
  - `HEALTH`
  - `GENERATE`
  - `CANCEL`
  - `METRICS`

### Kernel/runtime

- Triton compiles and runs on `sm120`
- Windows CUDA JIT compile works
- Prebuilt megakernel `.pyd` direct loading works
- Release mode prefers prebuilt and forbids player-side JIT fallback

### Real inference

- Qwen3-0.6B loads from:
  - `F:\CTest\Runtime\models\Qwen3-0.6B`
- Real model inference works end to end
- True token-by-token streaming works
- `CANCEL` can interrupt an active decode loop
- `METRICS` returns live request counters and CUDA memory state

## 5. Current runtime behavior

### Release mode

```text
prebuilt megakernel required
JIT fallback forbidden
```

### Dev mode

```text
prebuilt preferred
JIT allowed only when needed
```

### Single-GPU Windows path

For `world_size == 1`, `upstream_adapter.py` installs a tiny rank/size shim instead of bringing up fragile Gloo initialization.

## 6. Known sharp edges

1. Progress/UI code from upstream is not Windows-console-safe without UTF-8 env:
   - `PYTHONUTF8=1`
   - `PYTHONIOENCODING=utf-8`
2. Cancellation is checked between decode steps, so one extra token may arrive after `CANCEL_REPLY`.
3. Current real-model support has been verified on `sm120`; `sm86` / `sm89` still need validation.
4. Current generation quality has not been tuned; architecture closure is proven, product behavior is not yet tuned.
5. `LOAD_MODEL` is being wired now; current model config registration is alias-based and intentionally narrow.

## 7. Important documents

- `minivllm_windows_analysis.md`
- `real_inference_closure_report_20260519.md`
- `true_token_streaming_report_20260519.md`
- `cancel_decode_loop_report_20260519.md`
- `runtime_metrics_report_20260519.md`
- `verification_update_20260518.md`
- `agent_quickstart_windows_runtime_20260518.md`

## 8. Recommended next steps

1. Finish and harden runtime `LOAD_MODEL`
2. Add unload / reload semantics and reject model switches while requests are active
3. Add explicit counters for cancelled vs EOS vs max-token completions
4. Build the Unity C# client against the protobuf contract
5. Validate additional GPU packs:
   - `sm86`
   - `sm89`
6. Package a release-style runtime tree for player delivery

## 9. Practical launch command

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:MINIVLLM_MODE='release'
$env:MINIVLLM_CONFIG_PATH='F:\CTest\Runtime\models\qwen3_0_6b_windows.yaml'
$env:MINIVLLM_MODEL_ALIAS='qwen3-0.6b'
python -m MiniVLLMWorker.main
```

## 10. Final note

This project is no longer a feasibility sketch.  
It is now a Windows-native runtime under active hardening, with the highest-risk path already traversed end to end.
