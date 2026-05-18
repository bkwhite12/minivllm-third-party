# Unity Phase 1 Implementation Report

**Date**: 2026-05-19  
**Scope**: Protocol import, framing, Named Pipe transport, `HELLO`, and `HEALTH`.

## 1. Added Unity assets

Root:

```text
F:\CTest\UnityProject\Mini-vLLM\Assets\MiniVllmRuntime
```

Created:

- `Protocol/minivllm_runtime.proto`
- `Protocol/Generated/MinivllmRuntime.cs`
- `Plugins/Google.Protobuf.dll`
- `Transport/FrameCodec.cs`
- `Transport/NamedPipeRuntimeClient.cs`
- `Client/MiniVllmClient.cs`
- `Client/MiniVllmPhase1Probe.cs`

## 2. Dependency choice

The Unity client uses the official C# protobuf runtime:

- `Google.Protobuf.dll`

and C# code generated from the project proto using the official `protoc` compiler.

## 3. Implemented behavior

### Frame codec

Implements the worker wire format:

```text
[uint32 little-endian length][protobuf payload]
```

### Pipe transport

`NamedPipeRuntimeClient` connects to:

```text
\\.\pipe\minivllm-runtime
```

### First client API

`MiniVllmClient` currently supports:

- `ConnectAsync()`
- `HelloAsync(...)`
- `HealthAsync()`

### Unity probe

`MiniVllmPhase1Probe` exposes a context-menu action:

```text
Run Phase 1 Probe
```

which:

1. connects to the worker
2. sends `HELLO`
3. sends `HEALTH`
4. logs the worker/model/backend/kernel-pack snapshot

## 4. Validation state

The phase-1 code assets are now present and ready for Unity import/compilation.

To run the first in-editor check:

1. start `MiniVLLMWorker`
2. add `MiniVllmPhase1Probe` to any GameObject
3. invoke `Run Phase 1 Probe`

Expected log shape:

```text
MiniVLLM connected: worker=MiniVLLMWorker ..., model=qwen3-0.6b, backend=megakernel_cuda, kernelPack=cp312-cu128-sm120
```

## 5. Next phase

Phase 2 should add:

- request read loop
- `GENERATE`
- multi-`TOKEN` dispatch
- final `DONE`
- a minimal streaming text demo view
