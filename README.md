<div align="center">

# ⚡ MiniVLLM Third Party Windows Runtime

---

**A native Windows runtime wrapper for upstream `minivllm`, built for Unity games, Named Pipe IPC, Protobuf messaging, and prebuilt CUDA kernel delivery.**

[![Repository](https://img.shields.io/badge/GitHub-bkwhite12%2Fminivllm--third--party-181717.svg?logo=github)](https://github.com/bkwhite12/minivllm-third-party)
[![Windows](https://img.shields.io/badge/Windows-Native-0078D6.svg?logo=windows)](#)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg?logo=python)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-cu128-EE4C2C.svg?logo=pytorch)](https://pytorch.org/)
[![CUDA](https://img.shields.io/badge/CUDA-12.8-76B900.svg?logo=nvidia)](https://developer.nvidia.com/cuda-toolkit)
[![Unity](https://img.shields.io/badge/Unity-Client%20Ready-000000.svg?logo=unity)](https://unity.com/)
[![Protobuf](https://img.shields.io/badge/Protocol-Protobuf-4285F4.svg)](https://protobuf.dev/)
[![IPC](https://img.shields.io/badge/IPC-Named%20Pipe-6A5ACD.svg)](#)

<br/>

`Windows` · `Python` · `C#` · `CUDA` · `PyTorch` · `Protobuf` · `Named Pipe` · `Unity` · `minivllm`

</div>

---

## 🌟 Features

- **Windows-native runtime**: no WSL, no virtual machine, and no HTTP service.
- **Game-friendly IPC**: local Named Pipe transport with shared Protobuf messages.
- **Upstream-preserving adapter**: keeps `minivllm` as a third-party submodule and places Windows-specific behavior in `WindowsKernelPack/` and `MiniVLLMWorker/`.
- **Prebuilt CUDA megakernels**: release mode loads packaged `.pyd` extensions first; JIT builds are reserved for development workflows.
- **Multi-architecture kernel packs**:
  - `cp312-cu128-sm86`
  - `cp312-cu128-sm89`
  - `cp312-cu128-sm120`
- **True token streaming**: streams generated text chunks through the pipe protocol.
- **Cancelable generation**: active requests can be cancelled by the client.
- **Runtime metrics**: total, active, completed, failed, cancelled, EOS, max-token counters, and CUDA memory stats.
- **Unity integration foundation**: C# transport, Protobuf bindings, generation, cancellation, and metrics hooks.
- **Dialogue reliability tools**: prompt replay, explicit memory context tests, and readable transcript output.

---

## 🚀 Quick Start

### 1. Clone

```bash
git clone --recurse-submodules https://github.com/bkwhite12/minivllm-third-party.git
cd minivllm-third-party
```

If the submodule was not initialized:

```bash
git submodule update --init --recursive
```

### 2. Prepare Python

Use Python 3.12. The scripts resolve Python in this order:

```text
MINIVLLM_PYTHON
.venv/Scripts/python.exe
Runtime/python/python.exe
PATH python.exe
```

Optional explicit override:

```powershell
$env:MINIVLLM_PYTHON = "<PYTHON_3_12>\python.exe"
```

Install dependencies:

```powershell
python -m pip install -r WindowsKernelPack\requirements-win-cu128.txt
```

### 3. Prepare a model

Place model files under a local runtime model directory, for example:

```text
Runtime/models/Qwen3-0.6B/
```

Then provide or adjust a Windows runtime config:

```powershell
$env:MINIVLLM_CONFIG_PATH = "Runtime\models\qwen3_0_6b_windows.yaml"
$env:MINIVLLM_MODEL_ALIAS = "qwen3-0.6b"
```

`Runtime/` is ignored by Git because it contains local models, caches, build output, and logs.

### 4. Start the worker

```powershell
.\start_minivllm_worker.cmd
```

The launcher derives paths from the repository root, so it should not need machine-specific edits.

### 5. Probe the runtime

```powershell
python -m MiniVLLMWorker.test_client health
python -m MiniVLLMWorker.test_client generate --prompt "Hello from the game runtime."
python -m MiniVLLMWorker.test_client metrics
```

### 6. Build kernel packs

Build a single pack for the current target:

```powershell
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel.ps1
```

Build multiple architecture packs:

```powershell
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel_multiarch.ps1 -Architectures sm86,sm89,sm120
```

Cross-compiled packs can be import/export verified on the build machine. Full on-device kernel smoke tests should be run on GPUs matching the target SM architecture.

---

## 🧱 Architecture

```text
Unity Game
  └─ Named Pipe + Protobuf
      └─ MiniVLLMWorker
          └─ WindowsKernelPack adapter
              └─ upstream minivllm
                  └─ NVIDIA GPU
```

This repository owns the Windows delivery shell. Upstream `minivllm` owns model execution and high-performance kernels.

---

## 📂 Project Structure

```text
.
├─ MiniVLLMWorker/           # Named Pipe server, router, inference service
├─ WindowsKernelPack/        # Windows bootstrap, upstream adapter, prebuilt loader, build scripts
├─ Protocol/                 # Protobuf schema and generated Python/C# bindings
├─ UnityProject/             # Unity-side client assets and sample integration area
├─ minivllm/                 # Upstream minivllm submodule
├─ Runtime/                  # Local runtime cache/log/model/build folder; ignored
├─ installers/               # Local installer cache; ignored
└─ start_minivllm_worker.cmd # Relative-path worker launcher
```

---

## 🧩 Kernel Packs

Prebuilt packs are stored under:

```text
WindowsKernelPack/prebuilt/
├─ cp312-cu128-sm86/
├─ cp312-cu128-sm89/
└─ cp312-cu128-sm120/
```

At runtime, `WindowsKernelPack.prebuilt_loader` selects the matching pack by GPU compute capability:

```text
sm86  -> cp312-cu128-sm86
sm89  -> cp312-cu128-sm89
sm120 -> cp312-cu128-sm120
```

You can override the selection manually:

```powershell
$env:MINIVLLM_KERNEL_PACK_ID = "cp312-cu128-sm89"
```

---

## 🎮 Unity Integration

Unity communicates with `MiniVLLMWorker` through the shared Protobuf contract in:

```text
Protocol/minivllm_runtime.proto
```

The intended player-facing package includes:

- worker runtime
- Python runtime and dependencies
- model files
- matching prebuilt kernel pack
- Unity C# client scripts

Player machines should only need a compatible NVIDIA driver.

---

## 🧪 Reliability Tools

The worker includes Python-side test utilities for runtime and dialogue behavior:

```powershell
python -m MiniVLLMWorker.test_client health
python -m MiniVLLMWorker.test_client generate --prompt "..."
python -m MiniVLLMWorker.dialogue_reliability_runner
python -m MiniVLLMWorker.dialogue_reliability_runner --explicit-memory
```

`minivllm` itself is single-request oriented. Multi-turn behavior is tested by replaying conversation history and explicit game-state memory into each request.

---

## 🛠️ Development Notes

- Keep upstream `minivllm` untouched when possible.
- Put Windows-specific behavior in `WindowsKernelPack/`.
- Put local model files, logs, caches, and temporary build output in `Runtime/`.
- Do not commit local tool state such as `.claude/`.
- `AILog/` is a local notes folder and is intentionally ignored.

---

## 🙏 Acknowledgements

This project builds on top of [BoundlessWindMoon/minivllm](https://github.com/BoundlessWindMoon/minivllm), which provides the lightweight LLM inference engine and high-performance CUDA/Triton kernel work adapted here for Windows-native game runtime delivery.

Thanks also to the PyTorch, CUDA, Triton Windows, Protobuf, and Unity ecosystems for making local AI runtime integration practical.

---

## 🧭 Others

### Current Focus

- Windows-native worker runtime
- Unity local IPC integration
- Multi-architecture prebuilt CUDA kernel packs
- Explicit memory/context experiments for game NPC dialogue reliability

### Known Constraints

- This is not a replacement for upstream `minivllm`; it is a Windows runtime wrapper around it.
- Small models such as Qwen3-0.6B are useful for smoke tests but may not be strong enough for final NPC dialogue quality.
- Cross-compiled kernel packs should be smoke-tested on matching GPU architectures before broad distribution.

### License

Project-specific code is intended to be MIT licensed unless a file states otherwise. Upstream and third-party components retain their own licenses.
