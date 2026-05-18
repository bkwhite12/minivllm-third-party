# Windows Runtime Verification Update

**Date**: 2026-05-18  
**Machine**: NVIDIA GeForce RTX 5070 / sm120 / Driver 596.21  
**Purpose**: Reconcile the handoff note with the machine's actual state and record the next three verification results.

## 1. Correction to the previous handoff

The earlier handoff file said **Visual Studio Build Tools / MSVC were not installed**.  
That conclusion is stale.

Current machine state:

- Visual Studio Community 2022 is installed at:
  - `F:\Program Files\Microsoft Visual Studio\2022\Community`
- Version:
  - `17.14.5`
- MSVC toolset:
  - `14.44.35207`
- `cl.exe` exists at:
  - `F:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe`
- `VsDevCmd.bat` exists at:
  - `F:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat`

Why another agent may have missed it:

- `where cl` in a normal terminal can fail even when MSVC is installed.
- `cl.exe` becomes available after entering the Visual Studio developer environment.
- For repeatable verification, use:
  - `WindowsKernelPack\run_smoke_megakernel_vsdev.cmd`

See also:

- `AILog\agent_quickstart_windows_runtime_20260518.md`

## 2. Verification results completed today

### A. Triton warmup

Command:

```powershell
$env:TRITON_CACHE_DIR='F:\CTest\Runtime\cache\triton'
python .\WindowsKernelPack\warmup_triton.py
```

Observed result:

| Test | Result |
|---|---|
| vec_add | PASS |
| matmul | FAIL, numeric mismatch in the toy kernel |
| silu | PASS |
| softmax | FAIL, numeric mismatch in the toy kernel |
| autotune_relu | PASS |
| bf16_kernel | PASS |

Conclusion:

- Triton compilation and runtime execution on RTX 5070 / sm120 are working.
- The two failing cases are current test-kernel quality issues, not evidence that the Triton toolchain is broken.

### B. Megakernel CUDA JIT compile

Two environment corrections were required:

1. The target architecture had to be changed from `9.0` to `12.0` because this machine is `sm120`.
2. The Python install path contains non-ASCII characters, which caused broken include paths during C++ extension compilation.  
   Workaround used:

```powershell
subst P: "C:\Users\BK白修\AppData\Local\Programs\Python\Python312"
```

Then compile through the VS developer environment:

```powershell
cmd.exe /c F:\CTest\WindowsKernelPack\run_smoke_megakernel_vsdev.cmd
```

Observed result:

- `nvcc` compiled `decode_ldg.cu`
- `cl.exe` compiled `decode_wrapper.cpp`
- `link.exe` generated:
  - `F:\CTest\Runtime\cache\torch_extensions\mini_vllm_mk_default\mini_vllm_mk_default.pyd`

Conclusion:

- The Windows native JIT toolchain is functional.
- The later dummy smoke decode path did not complete reliably and should not yet be treated as a successful runtime inference validation.

### C. Prebuilt `.pyd` extraction

Extracted artifact:

- Source:
  - `F:\CTest\Runtime\cache\torch_extensions\mini_vllm_mk_default\mini_vllm_mk_default.pyd`
- Copied to:
  - `F:\CTest\WindowsKernelPack\prebuilt\cp312-cu128-sm120\mini_vllm_mk_default.cp312-win_amd64.pyd`

Manifest created:

- `F:\CTest\WindowsKernelPack\prebuilt\cp312-cu128-sm120\kernel_manifest.json`

Conclusion:

- The first prebuilt Windows megakernel artifacts now exist and are available for non-JIT loading work.

Additional result:

- `all_combined` was also compiled in `--compile-only` mode and extracted to:
  - `F:\CTest\WindowsKernelPack\prebuilt\cp312-cu128-sm120\mini_vllm_mk_all_combined.cp312-win_amd64.pyd`

### D. Prebuilt direct import

Command:

```powershell
python .\WindowsKernelPack\prebuilt_loader.py
```

Observed result:

```text
prebuilt_load=PASS
module=mini_vllm_mk_default
exports=PASS
```

One implementation note:

- Standalone import required adding the PyTorch `lib` directory to the Windows DLL search path before loading the `.pyd`.

## 3. Current state

| Item | Status |
|---|---|
| Triton warmup chain | PASS enough to proceed |
| Native Windows CUDA JIT compile | PASS |
| Default megakernel prebuilt artifact | PASS |
| all_combined megakernel prebuilt artifact | PASS |
| Prebuilt direct import validation | PASS |
| Real-model decode validation | NOT YET DONE |

## 4. Next recommended steps

1. Replace the synthetic smoke decode with a real model-backed or fixture-backed verification path.
2. Wire `upstream_adapter.py` to prefer prebuilt loading on Windows and fall back to JIT only in developer mode.
3. Validate a real `ModelRunner.inference()` path through the Named Pipe worker.
