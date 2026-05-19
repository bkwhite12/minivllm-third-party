# Unity Phase 3 Implementation Report

**Date**: 2026-05-19  
**Scope**: `CANCEL`, `METRICS`, and the first operable Unity panel.

## 1. Updated Unity client API

`MiniVllmClient` now supports:

- `CancelAsync(targetRequestId)`
- `MetricsAsync()`

## 2. Added UI component

Added:

- `Client/MiniVllmRuntimePanel.cs`

The panel expects inspector references for:

- prompt input
- connect button
- generate button
- cancel button
- metrics button
- status text
- output text
- metrics text

## 3. Panel behavior

### Connect

- opens Named Pipe connection
- runs `HELLO`
- runs `HEALTH`
- shows worker/model/backend/kernel-pack state

### Generate

- sends `GENERATE`
- appends every incoming `TOKEN` to output text
- shows terminal `DONE` finish reason

### Cancel

- sends `CANCEL` for the active request id

### Metrics

- requests `METRICS`
- displays:
  - uptime
  - total/completed/failed/active
  - cancelled/eos/max-token counters
  - allocated/reserved VRAM

## 4. Session model added

To make cancellation genuinely usable while generation is still running, Phase 3 also adds:

```csharp
GenerationSession StartGeneration(...)
```

where:

- `RequestId` is available immediately
- token events stream over time
- completion is exposed as a task
- cancel can target a truly active request

`CANCEL` and `METRICS` use short-lived control connections so they can run while the main generation connection is still busy reading tokens.

## 5. Recommended next step

The next architectural refinement should be a longer-lived routed read loop with pending-request state, which will make multiple simultaneous requests cleaner. The current session model is already sufficient for a single active UI conversation.

## 6. Final conclusion

Phase 3 now gives Unity a genuinely operable control surface:

- streaming generation
- live cancellation
- live metrics
