# Completion Reason Counters — 实现记录

**日期**: 2026-05-19  
**Commit**: `3aaddb3`  
**目的**: 区分 cancelled / EOS / max-token 完成数，替代原来的单一 `completed_requests` 计数器

## 1. 改了哪些文件

| 文件 | 改动 |
|---|---|
| `Protocol/minivllm_runtime.proto` | `RuntimeMetrics` 新增字段 8–10 |
| `Protocol/python_generated/minivllm_runtime_pb2.py` | protoc 重新生成 |
| `MiniVLLMWorker/inference_service.py` | 新增三个计数器 + `mark_completed(finish_reason)` + `metrics_snapshot` 暴露 |
| `MiniVLLMWorker/request_router.py` | `_generate_stream` 传入 finish_reason；`_metrics_reply` 填充新字段 |
| `MiniVLLMWorker/test_client.py` | METRICS 回复改为格式化显示，含三级缩进 |
| `WindowsKernelPack/upstream_adapter.py` | 新增 `last_finish_reason` 属性，decode loop 结束时设置 |

## 2. Proto 新增字段

```proto
message RuntimeMetrics {
  // ... existing fields 1–7 unchanged ...
  uint64 cancelled_requests    = 8;  // CANCELLED finish
  uint64 eos_completions       = 9;  // EOS finish
  uint64 max_token_completions = 10; // MAX_TOKENS finish
}
```

不变量：
```
completed_requests == cancelled_requests + eos_completions + max_token_completions
```

## 3. finish_reason 数据流

```
upstream_adapter.stream_generate_tokens()
  │
  ├─ 正常结束，stopped_by_eos=True
  │    → self._last_finish_reason = pb.EOS
  │
  ├─ 正常结束，达到 max_new_tokens
  │    → self._last_finish_reason = pb.MAX_TOKENS
  │
  └─ 被取消
       → self._last_finish_reason = pb.CANCELLED
       → raise GenerationCancelledError
            │
            ▼
inference_service.stream_generate()
  │
  ├─ except GenerationCancelledError → self._last_finish_reason = pb.CANCELLED
  ├─ else (无异常) → self._last_finish_reason = adapter.last_finish_reason
  │
  └─ echo fallback — 保持默认 pb.MAX_TOKENS
            │
            ▼
request_router._generate_stream()
  │
  ├─ result.finish_reason 来自 complete_generation() → 读取 self._last_finish_reason
  └─ mark_completed(finish_reason=result.finish_reason)
            │
            ▼
inference_service.mark_completed()
  │
  ├─ failed=True → _failed_requests += 1  (不区分 finish_reason)
  └─ failed=False → _completed_requests += 1
       ├─ CANCELLED  → _cancelled_requests += 1
       ├─ EOS        → _eos_completions += 1
       └─ 其他        → _max_token_completions += 1 (含 MAX_TOKENS、echo、UNSPECIFIED)
```

## 4. METRICS 输出格式

```
METRICS:
  process_uptime_ms:     10426
  total_requests:        5
  completed_requests:    4
    cancelled:           1
    eos_completions:     2
    max_token:           1
  failed_requests:       1
  active_requests:       0
  allocated_vram_bytes:  3036311552
  reserved_vram_bytes:   3141533696
```

## 5. 向下兼容

- `completed_requests` 字段保留不变，值是三个子计数器之和
- `failed_requests` 语义不变（未捕获异常才计入）
- 取消的请求计入 `completed_requests` 且单独计入 `cancelled_requests`
- 如果未来有新的 `FinishReason` 值，会被归入 `max_token_completions`（default 分支）

## 6. 补充建议

当前 `metrics_active_smoke.py` 和 `cancel_smoke.py` 使用 `print(reply)` 原样输出 protobuf，不会显示格式化视图。如果后续要在烟雾测试中也显示格式化 METRICS，可改为调用 `test_client._print_metrics()`。
