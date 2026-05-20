# MiniVLLM Third Party Windows Runtime

Repository: [bkwhite12/minivllm-third-party](https://github.com/bkwhite12/minivllm-third-party)

MiniVLLM Third Party Windows Runtime is a native Windows integration layer for running upstream `minivllm` behind a game-friendly IPC boundary. It keeps upstream `minivllm` as a third-party submodule and adds a Windows runtime pack, Named Pipe + Protobuf protocol, Unity-facing client code, and prebuilt CUDA megakernel packages.

The goal is simple: keep upstream updates easy while making the runtime shippable to Windows players without WSL, VM, HTTP, CUDA Toolkit, or Visual Studio Build Tools on player machines.

## Features

- **Windows-native runtime**: no WSL, no virtual machine, no HTTP server.
- **Named Pipe + Protobuf IPC**: designed for local Unity game integration.
- **Upstream-preserving adapter**: Windows behavior is implemented in `WindowsKernelPack/` and `MiniVLLMWorker/` instead of modifying upstream `minivllm` source.
- **Prebuilt CUDA megakernels**: release mode loads packaged `.pyd` files first and only allows JIT in development mode.
- **Multi-architecture kernel packs**:
  - `cp312-cu128-sm86`
  - `cp312-cu128-sm89`
  - `cp312-cu128-sm120`
- **True token streaming**: streamed token chunks over the pipe protocol.
- **Cancellation support**: active generations can be cancelled from the client.
- **Runtime metrics**: active, total, completed, failed, cancelled, EOS, max-token completion counters, plus CUDA memory metrics.
- **Unity client foundation**: C# Named Pipe transport, Protobuf messages, generation, cancellation, and metrics hooks.
- **Dialogue reliability tools**: Python runners for multi-turn prompt replay, explicit memory context testing, and readable transcript logs.

## Repository Layout

```text
.
├─ MiniVLLMWorker/          # Named Pipe server, request router, inference service
├─ WindowsKernelPack/       # Windows bootstrap, upstream adapter, prebuilt loader, build scripts
├─ Protocol/                # Protobuf schema and generated Python/C# bindings
├─ UnityProject/            # Unity-side client assets and sample integration area
├─ minivllm/                # Upstream minivllm submodule
├─ Runtime/                 # Local runtime cache/log/model folder; generated and ignored
├─ installers/              # Local installer cache; ignored
└─ start_minivllm_worker.cmd # Relative-path worker launcher
```

## Quick Start

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

Use Python 3.12. You can either put a virtual environment under `.venv/`, place an embedded runtime under `Runtime/python/`, or point the scripts to your Python executable:

```powershell
$env:MINIVLLM_PYTHON = "<PYTHON_3_12>\python.exe"
```

Install Windows runtime dependencies:

```powershell
python -m pip install -r WindowsKernelPack\requirements-win-cu128.txt
```

### 3. Prepare a model

Place the model files under a local runtime model folder, for example:

```text
Runtime/models/Qwen3-0.6B/
```

Then adjust the runtime YAML under `Runtime/models/` or provide your own config path through:

```powershell
$env:MINIVLLM_CONFIG_PATH = "Runtime\models\qwen3_0_6b_windows.yaml"
$env:MINIVLLM_MODEL_ALIAS = "qwen3-0.6b"
```

`Runtime/` is intentionally ignored by Git because it contains local models, caches, and logs.

### 4. Start the worker

```powershell
.\start_minivllm_worker.cmd
```

The launcher resolves paths relative to the repository root and does not require editing absolute local paths.

### 5. Probe the pipe runtime

In another terminal:

```powershell
python -m MiniVLLMWorker.test_client health
python -m MiniVLLMWorker.test_client generate --prompt "Hello from the game runtime."
python -m MiniVLLMWorker.test_client metrics
```

### 6. Build kernel packs

Build the current machine's default pack:

```powershell
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel.ps1
```

Build multi-architecture packs:

```powershell
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel_multiarch.ps1 -Architectures sm86,sm89,sm120
```

Cross-compiled packs can be import/export verified on the build machine. Full on-device kernel smoke testing should be run on a GPU matching the target SM architecture.

## Unity Integration

Unity communicates with `MiniVLLMWorker` over a local Windows Named Pipe using the shared Protobuf protocol in `Protocol/minivllm_runtime.proto`.

The intended runtime shape is:

```text
Unity Game
  └─ Named Pipe + Protobuf
      └─ MiniVLLMWorker
          └─ WindowsKernelPack adapter
              └─ upstream minivllm
                  └─ NVIDIA GPU
```

For player builds, ship the worker, Python runtime/dependencies, model files, and the matching prebuilt kernel pack. Player machines should only need a compatible NVIDIA driver.

## Development Notes

- Upstream `minivllm` is kept as a submodule.
- Do not patch upstream unless absolutely necessary; prefer adapter code in `WindowsKernelPack/`.
- Generated runtime outputs belong in `Runtime/` and should stay out of Git.
- Local IDE/tool state such as `.claude/` is ignored.
- `AILog/` contains local design and verification notes and is intentionally ignored.

## Acknowledgements

This project builds on top of [BoundlessWindMoon/minivllm](https://github.com/BoundlessWindMoon/minivllm). The upstream project provides the model implementation and high-performance CUDA/Triton work that this repository adapts for Windows-native game runtime delivery.

Thanks also to the PyTorch, CUDA, Triton Windows, Protobuf, and Unity ecosystems that make this style of local game AI runtime possible.

## Others

### Current focus

- Windows-native worker runtime
- Unity local IPC integration
- Multi-architecture prebuilt CUDA kernel packs
- Explicit memory/context experiments for game NPC dialogue reliability

### Known constraints

- `minivllm` itself is single-request oriented; multi-turn behavior is implemented by replaying history and explicit game-state memory into each prompt.
- Small models such as Qwen3-0.6B are useful for smoke tests but may not be reliable enough for final NPC dialogue quality.
- Cross-compiled kernel packs still need on-device smoke validation on matching GPU architectures before broad distribution.

### License

Project-specific code is intended to be MIT licensed unless a file states otherwise. Upstream and third-party components retain their own licenses.
