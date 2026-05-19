# Unity Phase 2 Implementation Report

**Date**: 2026-05-19  
**Scope**: `GENERATE`, streaming `TOKEN`, and terminal `DONE`.

## 1. Added Unity assets

- `Client/GenerationSessionResult.cs`
- `Client/MiniVllmPhase2Probe.cs`

Updated:

- `Client/MiniVllmClient.cs`

## 2. Implemented behavior

`MiniVllmClient` now supports:

```csharp
GenerateAsync(
    string prompt,
    Action<TokenChunk> onToken = null,
    int maxNewTokens = 64,
    CancellationToken cancellationToken = default)
```

Generation behavior:

1. send one `GENERATE` envelope
2. receive zero or more `TOKEN` envelopes
3. invoke `onToken` for each token
4. finish only when `DONE` arrives
5. return `GenerationSessionResult`

## 3. Phase 2 probe

`MiniVllmPhase2Probe` exposes:

```text
Run Phase 2 Generate Probe
```

It:

1. connects to the worker
2. sends a prompt
3. logs each incoming token
4. logs the terminal done summary

Expected console pattern:

```text
TOKEN[0] ' Answer'
TOKEN[1] '!'
TOKEN[2] ' I'
...
DONE: finishReason=MaxTokens, streamed='...', final='...'
```

## 4. Current limitation

This phase still uses one request per dedicated connection and does not yet support:

- `CANCEL`
- multiple simultaneous pending requests
- a long-lived read loop with routed callbacks

Those belong naturally to Phase 3.

## 5. Next phase

Phase 3 should add:

- `CANCEL`
- `METRICS`
- request cancellation from Unity
- first small in-scene UI instead of only console probes
