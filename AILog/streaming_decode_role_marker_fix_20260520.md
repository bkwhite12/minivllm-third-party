# Streaming Decode 与 Role Marker 停止策略修复

**Date**: 2026-05-20  
**Changed file**: `WindowsKernelPack/upstream_adapter.py`

## 本次修复

1. 将 `User:` / `Assistant:` / `System:` 等角色标记检测前移到真实 decode loop。
2. 一旦生成内容里出现角色标记，运行时立即停止继续 decode，不再等到 `max_new_tokens=1024`。
3. 修复中文 streaming 中的 `�` 问题：
   - 不再把 tokenizer 临时产生的 U+FFFD replacement char 直接发给客户端；
   - decode loop 会累计 `generated_ids` 后整段 decode；
   - 只把稳定、可见、未被角色标记污染的增量文本发送出去。

## 行为变化

旧行为：

```text
模型生成第一句后继续自演：
User: ...
Assistant: ...
一直跑到 MAX_TOKENS
```

新行为：

```text
模型生成第一句
检测到 \nUser: / \nAssistant: / \nSystem:
立即停止
DONE 返回已清洗的 completion
```

当前 protobuf `FinishReason` 还没有 `ROLE_MARKER_STOP`，所以角色标记停止暂时映射为 `EOS`，表示“运行时主动认为生成已自然结束”。如果后续需要更细指标，可以扩展 proto 增加专门枚举。

## 需要注意

修改发生在 worker 进程内。若 `start_minivllm_worker.cmd` 已经启动，需要关闭旧窗口并重新启动 worker 后才会生效。

建议重新运行：

```powershell
cd F:\CTest
C:\Users\BK白修\AppData\Local\Programs\Python\Python312\python.exe -m MiniVLLMWorker.dialogue_reliability_runner
```

预期变化：

- `token_count` 明显下降，不再接近 1024；
- transcript 中不再出现 `�`；
- `role_leakage` 在日志清洗层仍可能记录为 YES，但应该不再消耗大量 token；
- `max_token_completions` 应明显下降，`eos_completions` 上升。

## Update on 2026-05-20 reliability hardening

After the first runtime stop-marker pass, generation no longer ran to 1024 tokens and `�` disappeared, but the client could still receive a trailing partial role marker such as `User` before `:` arrived.

A second runtime guard was added in `WindowsKernelPack/upstream_adapter.py`:

- hold back trailing partial role-marker prefixes like `\nUser`, `\nAssistant`, `\nSystem`;
- only stream them if later tokens prove they are ordinary text;
- if `:` / `：` arrives and forms a real marker, stop before the marker and never send the prefix.

The reliability runner now defaults to Qwen's tokenizer `chat_template` instead of raw tokenization:

```powershell
C:\Users\BK白修\AppData\Local\Programs\Python\Python312\python.exe -m MiniVLLMWorker.dialogue_reliability_runner
```

For A/B comparison with the previous raw continuation mode:

```powershell
C:\Users\BK白修\AppData\Local\Programs\Python\Python312\python.exe -m MiniVLLMWorker.dialogue_reliability_runner --raw-prompt
```

Reason: Qwen3 is an instruct/chat model. Raw `System/User/Assistant` prompt text makes it behave like a continuation model and encourages self-dialogue. The chat template path is closer to real player-facing usage.

## Update: structured chat-template handoff

The previous reliability run still felt weak because the worker used Qwen's chat template as a single user message wrapper around the whole raw transcript. That meant this text:

```text
System: ...
User: ...
Assistant: ...
User: ...
Assistant:
```

was still being interpreted as one large user message, not as real multi-turn chat history.

`WindowsKernelPack/upstream_adapter.py` now parses tagged prompts into structured chat messages before calling `tokenizer.apply_chat_template`:

```python
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."},
  {"role": "user", "content": "..."},
]
```

The final empty `Assistant:` line is treated as the generation prompt and is not inserted as message content.

This keeps minivllm upstream untouched while making Windows worker behavior closer to real chat/instruct usage.

Restart the worker before testing.
