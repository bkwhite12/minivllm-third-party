# 多轮对话可靠性验证方案

**日期**：2026-05-20  
**对象**：Windows 原生 `MiniVLLMWorker` + Qwen3-0.6B + Unity Named Pipe 客户端  
**目标**：验证当前模型与 runtime 在多轮对话场景下是否足够稳定，可用于 Unity 游戏内交互原型。

---

## 1. 验证结论口径

本方案不是验证“模型是否聪明”，而是验证：

```text
多轮对话能否稳定跑
上下文是否正确进入模型
流式输出是否可靠
取消/重试是否安全
长时间交互是否不崩
指标是否能解释问题
```

也就是说，本方案验证的是 **runtime + 协议 + 客户端 + 模型组合可靠性**。

---

## 2. 当前重要前提

当前 worker 的 `GENERATE` 请求是单次 prompt 输入。

因此，所谓“多轮对话”需要由 Unity 客户端维护 conversation history，然后每一轮把历史拼成新的 prompt 发给 worker。

推荐首版格式：

```text
System: 你是游戏中的 NPC，请保持角色一致。
User: 第一轮玩家输入
Assistant: 第一轮模型回复
User: 第二轮玩家输入
Assistant:
```

如果使用 `use_chat_template=true`，更理想的长期方案是让 worker 接收结构化 messages；但当前 proto 还没有 messages 字段，所以首轮验证先采用客户端拼接 prompt。

---

## 3. 验证维度

### 3.1 基础多轮一致性

目的：确认模型能记住前几轮的关键事实。

测试样例：

```text
Round 1:
User: 我叫林川，是一名来自北境的铁匠。

Round 2:
User: 我叫什么？我是做什么的？

期望：
Assistant 应提到“林川”和“铁匠”。
```

通过标准：

- 10 组事实记忆测试中，至少 8 组能正确引用前文关键事实
- 不要求措辞完全一致

---

### 3.2 角色一致性

目的：验证游戏 NPC 场景中，模型不会很快跳出角色。

测试样例：

```text
System: 你是一个谨慎、年老的药剂师，不知道现代科技。
User: 你是谁？
Assistant: ...
User: 你能给我写一段 Python 吗？
```

期望：

- 模型应尽量保持“药剂师”角色
- 可以拒绝或用角色口吻解释不懂现代科技

通过标准：

- 20 轮对话内，不应无故切换身份
- 不应主动暴露“我是 AI 模型”之类元身份，除非 prompt 要求

---

### 3.3 长上下文稳定性

目的：确认多轮 prompt 逐渐变长后，worker 不崩、延迟可接受、输出仍可用。

测试方法：

```text
连续 30 轮
每轮 user 输入 20~80 字
每轮 max_new_tokens = 128 或 256
```

记录：

- 每轮 `ttft_ms`
- 每轮 `total_latency_ms`
- 每轮 `tokens_per_sec`
- 是否出现 ERROR
- 是否出现空输出
- 是否出现明显重复循环

通过标准：

- 30 轮内无 worker 崩溃
- 无 pipe 断连
- ERROR 数为 0
- 平均延迟趋势可解释，不出现无故指数级恶化

---

### 3.4 取消与继续对话

目的：确认玩家打断 NPC 后，下一轮还能继续正常对话。

测试方法：

```text
Round 1:
发起长回答
生成中点击 Cancel
确认收到 DONE(CANCELLED)

Round 2:
继续发起一个新问题
确认能正常 TOKEN -> DONE
```

通过标准：

- CANCEL_REPLY accepted=true
- 原请求最终 DONE(CANCELLED)
- 下一轮请求正常完成
- metrics 中 cancelled_requests 增加

---

### 3.5 重复快速请求

目的：验证 Unity 侧不会因为玩家快速点击导致状态错乱。

测试方法：

```text
快速点击 Generate
快速点击 Cancel
Cancel 后立刻 Generate
```

通过标准：

- UI 不应重复启动多个不可控请求
- active_requests 最终回到 0
- worker 不应卡死
- Unity 不应出现未处理异常

---

### 3.6 输出流式完整性

目的：验证 Unity 里看到的逐 token 文本，与最终 DONE 文本一致或可解释。

测试方法：

- 收集所有 `TOKEN.text`
- 拼接为 `streamedText`
- 对比 `DONE.text`

注意：

当前 `DONE.text` 包含 prompt + completion，而 Unity 的 streamed text 只应显示 completion。

通过标准：

```text
DONE.text 应以当前完整 prompt 开头
DONE.text 去掉 prompt 后，应接近 streamedText
```

允许因 tokenizer 空白、chat template 或 special token 产生轻微差异，但不能完全不一致。

---

## 4. 推荐测试集

### 4.1 事实记忆

| 编号 | 内容 |
|---|---|
| F01 | 玩家姓名、职业 |
| F02 | 玩家携带物品 |
| F03 | 玩家任务目标 |
| F04 | NPC 曾给出的警告 |
| F05 | 地点与方向 |

### 4.2 角色扮演

| 编号 | 角色 |
|---|---|
| R01 | 药剂师 |
| R02 | 城门守卫 |
| R03 | 地下商人 |
| R04 | 古代学者 |
| R05 | 受伤士兵 |

### 4.3 压力场景

| 编号 | 场景 |
|---|---|
| S01 | 30 轮短对话 |
| S02 | 10 轮长回答 |
| S03 | 每轮都取消 |
| S04 | 中英混合输入 |
| S05 | 玩家输入空字符串、极短字符串、超长字符串 |

---

## 5. 建议记录格式

每轮记录一行 JSONL：

```json
{
  "session_id": "test-001",
  "round": 3,
  "prompt_chars": 582,
  "max_new_tokens": 128,
  "finish_reason": "MAX_TOKENS",
  "ttft_ms": 42,
  "total_latency_ms": 870,
  "tokens_per_sec": 48.2,
  "cancelled": false,
  "error": "",
  "quality_note": "remembered player name"
}
```

建议保存到：

```text
F:\CTest\Runtime\logs\dialogue_reliability\
```

---

## 6. 推荐通过标准

首轮可用标准：

```text
基础连通：100% 通过
30 轮连续对话：无崩溃
CANCEL 后继续生成：100% 通过
事实记忆：>= 80%
角色一致性：>= 80%
ERROR：0
active_requests 最终归零
```

如果用于正式游戏 demo，建议再加：

```text
连续运行 30 分钟
至少 100 次 GENERATE
至少 20 次 CANCEL
failed_requests = 0
显存无持续单调增长
```

---

## 7. 需要特别观察的问题

### 7.1 Qwen3-0.6B 能力边界

0.6B 模型很轻，适合验证 runtime 和交互链路，但不要期待它在复杂长角色对话上表现得像大模型。

如果多轮质量不够，优先判断：

```text
是模型能力不足
还是上下文拼接方式有问题
还是 max_new_tokens 太低
还是采样参数不合适
```

不要直接把质量问题归因到 pipe 或 megakernel。

### 7.2 `MAX_TOKENS` 不一定是错误

如果回答被截断，说明：

```text
max_new_tokens 太低
```

Unity 侧应把它显示为“回答达到长度上限”，而不是“失败”。

### 7.3 CANCEL 后可能多一个 token

当前取消在 decode step 边界生效，所以：

```text
CANCEL_REPLY 后仍可能再收到 1 个 TOKEN
然后 DONE(CANCELLED)
```

这是当前架构允许的正常现象。

---

## 8. 建议下一步实现

为了让验证更自动化，建议补一个 Unity 或 Python 测试器：

```text
DialogueReliabilityRunner
  - 输入测试脚本
  - 自动维护 conversation history
  - 自动发 GENERATE
  - 自动记录 TOKEN / DONE / METRICS
  - 输出 JSONL 报告
```

优先用 Python 做第一版更快；等验证逻辑稳定后，再搬到 Unity PlayMode Test。

---

## 9. 最终判断

当前项目已经具备开始多轮对话可靠性验证的条件。

但验证重点应放在：

```text
上下文管理
流式完整性
取消恢复
长会话稳定性
指标闭环
```

而不是单纯看模型某一句回答是否聪明。
