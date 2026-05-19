# 显式记忆上下文测试结果

**Date**: 2026-05-20  
**Runner**: `MiniVLLMWorker/dialogue_reliability_runner.py --explicit-memory`  
**Output**:

- `Runtime/logs/dialogue_reliability/explicit_memory_20260520.jsonl`
- `Runtime/logs/dialogue_reliability/explicit_memory_20260520.txt`

## 本次新增能力

`DialogueReliabilityRunner` 增加 `--explicit-memory` 参数。开启后，每轮 prompt 会额外注入场景侧显式记忆：

- 玩家姓名：林川
- 玩家身份：来自北境的铁匠
- NPC 风格：简洁、自然、像游戏内同伴
- 当前任务：前往城堡
- 最近事件：玩家要求讲夜城故事并会中途打断
- 第 5 轮当前目标：继续夜城故事
- 禁止事项：不要回到旧的城堡建议

运行命令：

```powershell
cd F:\CTest
C:\Users\BK白修\AppData\Local\Programs\Python\Python312\python.exe -m MiniVLLMWorker.dialogue_reliability_runner --explicit-memory --output F:\CTest\Runtime\logs\dialogue_reliability\explicit_memory_20260520.jsonl --transcript F:\CTest\Runtime\logs\dialogue_reliability\explicit_memory_20260520.txt
```

## 结果摘要

```text
rounds: 5
finish: EOS x4, CANCELLED x1
role_leakage: 0 / 5
MAX_TOKENS: 0
token_count: [13, 13, 12, 6, 27]
failed_requests: 0
active_requests: 0
```

## 质量观察

显式记忆明显改善了第 5 轮：

```text
夜城故事中，林川望着远方的灯火，轻声说道：“夜城的尽头，是通往城堡的路。”
```

这比之前第 5 轮反复回到“去城堡前检查工具/装备”的表现更符合目标，说明显式记忆对 `Qwen3-0.6B` 是有效的。

但第 4 轮仍然暴露了模型弱点：用户要求讲夜城故事，模型仍先生成了“请先前往北境城...”，说明即使有显式记忆，0.6B 在多目标上下文里仍容易被最近的“城堡任务”牵引。

## 结论

显式记忆有效，但不能完全弥补 `Qwen3-0.6B` 的多轮规划能力不足。

推荐架构：

```text
Unity 游戏状态
  ↓
显式记忆层 / 当前目标层 / 禁止事项层
  ↓
MiniVLLMWorker
  ↓
模型生成
```

对于交付玩家的 NPC 对话，建议：

1. 0.6B 继续作为工程烟测模型。
2. 游戏实际体验至少 A/B 测 Qwen3-1.7B 或更高。
3. Unity 侧不要只传聊天历史，必须传结构化状态：玩家身份、当前任务、最近事件、当前回复目标、禁止重复内容。
4. 对“被打断后继续”这类场景，要显式传入 `上一轮未完成事件` 和 `当前目标`。
