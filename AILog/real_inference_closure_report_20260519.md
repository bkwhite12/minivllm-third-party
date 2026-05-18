# Real Inference Closure Report

**Date**: 2026-05-19  
**Goal**: Finish the Windows-native path from `Named Pipe -> MiniVLLMWorker -> upstream minivllm -> prebuilt megakernel -> real model output`.

## 1. What changed

### 1.1 Prebuilt-first megakernel loading

`WindowsKernelPack/upstream_adapter.py` now installs a Windows-specific megakernel loader hook:

- First try:
  - `WindowsKernelPack/prebuilt/cp312-cu128-sm120/*.pyd`
- If a matching prebuilt exists:
  - load it directly
  - expose `kernel_pack_id = cp312-cu128-sm120`
- If a matching prebuilt is missing:
  - `dev` mode may fall back to upstream JIT
  - `release` mode raises an error and refuses player-side JIT compilation

This is the intended product behavior:

```text
release mode = prebuilt required
dev mode     = prebuilt preferred, JIT allowed as fallback
```

### 1.2 Windows single-process distributed shim

Real model loading exposed a Windows-specific issue:

- `gloo` initialization failed on this machine even with `world_size = 1`
- upstream code only needs tensor-parallel rank/size information in this single-GPU path

For `Windows + world_size == 1`, `upstream_adapter.py` now installs a tiny shim:

- `dist.get_rank() -> 0`
- `dist.get_world_size() -> 1`

That avoids unnecessary Gloo startup for the one-process local runtime while preserving the behavior the current model path actually uses.

### 1.3 Runtime environment correction

Loading the real model exposed one package drift:

- `transformers 4.51.0` requires:
  - `huggingface-hub >= 0.30.0, < 1.0`
- model-download troubleshooting had temporarily installed:
  - `huggingface-hub 1.15.0`

The environment was corrected to:

- `huggingface-hub 0.36.2`

## 2. Model used

Local model directory:

```text
F:\CTest\Runtime\models\Qwen3-0.6B
```

Verified files:

- `config.json`
- `generation_config.json`
- `model.safetensors`
- `tokenizer.json`
- `tokenizer_config.json`
- `merges.txt`
- `vocab.json`

Runtime config used for the first closure test:

```text
F:\CTest\Runtime\models\qwen3_0_6b_windows.yaml
```

Key overrides:

- `model_path = F:/CTest/Runtime/models/Qwen3-0.6B/`
- `backend = megakernel_cuda`
- `megakernel_variant = all_combined`
- `max_new_tokens = 16`
- `use_thinking = false`

## 3. Real closure test

Worker launch:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:MINIVLLM_MODE='release'
$env:MINIVLLM_CONFIG_PATH='F:\CTest\Runtime\models\qwen3_0_6b_windows.yaml'
$env:MINIVLLM_MODEL_ALIAS='qwen3-0.6b'
python -m MiniVLLMWorker.main
```

Observed worker startup:

- model weights loaded successfully
- pipe server started successfully
- `kernel_pack_id` reported:
  - `cp312-cu128-sm120`

Health request result:

```text
state: READY
active_model: qwen3-0.6b
backend: megakernel_cuda
kernel_pack_id: cp312-cu128-sm120
```

Generation request:

```powershell
python -m MiniVLLMWorker.test_client generate --prompt "Hello, introduce yourself in one short sentence."
```

Observed result:

- Worker returned:
  - `TOKEN`
  - `DONE`
- Real model text was produced through the full path
- Metrics observed:
  - `ttft_ms = 189`
  - `total_latency_ms = 189`
  - `tokens_per_sec = 5.29`

## 4. Current status

| Item | Status |
|---|---|
| Windows prebuilt-first kernel selection | PASS |
| Release mode refusing player-side JIT | PASS by design |
| Real model loading | PASS |
| Named Pipe -> Worker -> model -> response | PASS |
| Real megakernel inference path | PASS |
| True token-by-token streaming | NOT YET DONE |

## 5. Important observations

### 5.1 The closure is real, but streaming is still coarse

The external protobuf protocol is streaming-capable, but current upstream integration still returns final text from `ModelRunner.inference()`.

So the first true closure currently behaves as:

```text
external transport: streaming protocol
model boundary:     final text
worker response:    one TOKEN chunk + DONE
```

### 5.2 Output quality is not yet a product verdict

The purpose of this test was architectural closure, not generation quality tuning.  
The first prompts produced valid model output through the pipeline, but sampling/prompt shaping should be tuned separately before judging product behavior.

### 5.3 UTF-8 environment matters on Windows

Without:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

the upstream Rich progress UI can fail under legacy GBK console encoding.

## 6. Recommended next steps

1. Move the prebuilt-loader hook from “adapter-installed runtime patch” toward a slightly more explicit kernel-pack selector API.
2. Add a release-mode startup check that validates:
   - Python tag
   - CUDA runtime
   - target arch
   - required megakernel variant
3. Implement true token streaming outside the upstream `ModelRunner.inference()` boundary.
4. Add a deterministic real-model smoke test fixture so future upstream updates can be validated without manual inspection.
5. Start the Unity C# client against the now-proven worker contract.

## 7. Final conclusion

The project has now crossed the decisive line:

```text
Windows native release-mode worker
  -> prebuilt megakernel
  -> real local model
  -> Named Pipe protobuf response
```

This is no longer just a portability plan.  
It is a working Windows-native inference runtime skeleton with the highest-risk path already exercised end to end.
