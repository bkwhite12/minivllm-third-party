# Worker Launcher Note

**Date**: 2026-05-19

Created:

```text
F:\CTest\start_minivllm_worker.cmd
```

Purpose:

- start `MiniVLLMWorker` by double-click
- set required UTF-8 and runtime environment variables automatically
- write the latest console log to:
  - `F:\CTest\Runtime\logs\minivllm_worker_latest.log`

Usage:

1. Double-click `start_minivllm_worker.cmd`
2. Wait until the console shows:

```text
Named pipe server listening on \\.\pipe\minivllm-runtime
```

3. Then use the Unity Phase 1 probe or future Unity client features.

Current bound model:

- alias: `qwen3-0.6b`
- config:
  - `F:\CTest\Runtime\models\qwen3_0_6b_windows.yaml`
