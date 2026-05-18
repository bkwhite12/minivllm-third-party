# Unity 客户端实施方案

**日期**：2026-05-19  
**目标**：为当前 Windows 原生 `MiniVLLMWorker` 编写 Unity 客户端，实现 Unity 游戏与本地 LLM Runtime 的稳定通信、流式渲染、取消、模型加载与运行态观测。

---

## 1. 结论先行

现在已经可以开始编写 Unity 项目。

当前 worker 已具备 Unity 客户端所需的关键协议面：

- `HELLO`
- `HEALTH`
- `LOAD_MODEL`
- `GENERATE`
- `TOKEN`
- `DONE`
- `CANCEL`
- `METRICS`

同时已经具备：

- Windows Named Pipe
- Protobuf 协议
- 真正逐 token streaming
- 真实模型推理闭环
- active request 取消
- completion reason counters
- runtime metrics

因此，Unity 侧可以立即进入开发，不必等待 Python 侧完全产品化。

---

## 2. Unity 客户端的设计目标

### 2.1 必须做到

1. 与本地 Worker 建立 Named Pipe 连接
2. 使用和 Worker 同一份 `.proto`
3. 支持请求 / 响应 envelope
4. 支持流式文本增量渲染
5. 支持主动取消生成
6. 支持加载模型
7. 支持健康检查与指标查询
8. 能在 Worker 暂时不可用时给出可恢复的错误

### 2.2 暂时不必一开始就做完

- 复杂重连策略
- 多模型管理 UI
- 游戏内完整聊天系统
- 多会话并发
- 玩家安装器
- 大型可观测性面板

首版 Unity 客户端应该像一个**可靠的控制台**：先把边界做稳，再把体验做美。

---

## 3. 建议目录结构

后续如果开始实施，建议在：

```text
F:\CTest\UnityProject\Mini-vLLM\Assets
```

下建立：

```text
Assets/
  MiniVllmRuntime/
    Protocol/
      minivllm_runtime.proto
      Generated/
    Transport/
      NamedPipeClient.cs
      FrameCodec.cs
    Client/
      MiniVllmClient.cs
      PendingRequest.cs
      RuntimeState.cs
    Models/
      WorkerModels.cs
    Services/
      WorkerProcessService.cs
      WorkerHealthService.cs
    UI/
      Demo/
        MiniVllmDemoController.cs
        StreamingTextView.cs
        MetricsPanelView.cs
    Tests/
      EditMode/
      PlayMode/
```

### 目录职责

| 目录 | 职责 |
|---|---|
| `Protocol` | 保存 `.proto` 与生成的 C# 协议代码 |
| `Transport` | 只关心 pipe 连接、frame 编解码 |
| `Client` | 只关心请求分发、pending request、事件回调 |
| `Services` | Worker 进程、健康检查、生命周期 |
| `UI/Demo` | 首个演示场景，不污染底层 |
| `Tests` | 验证 framing、协议、取消、断线等 |

---

## 4. 推荐分层

```text
UI / Game Logic
      |
      v
MiniVllmClient
      |
      v
NamedPipeClient + FrameCodec
      |
      v
Windows Named Pipe
      |
      v
MiniVLLMWorker
```

### 4.1 `FrameCodec`

职责：

- 写入：
  - `[uint32 little-endian length]`
  - `[protobuf bytes]`
- 读取：
  - 先读 4 字节长度
  - 再精确读取 payload
- 不理解业务类型

### 4.2 `NamedPipeClient`

职责：

- 连接 `\\.\pipe\minivllm-runtime`
- 提供 async read / write
- 处理断开连接
- 不理解 `GENERATE`、`TOKEN` 这些语义

### 4.3 `MiniVllmClient`

职责：

- 生成 `request_id`
- 管理 pending requests
- 把 envelope 路由到：
  - hello callback
  - health callback
  - token stream callback
  - done callback
  - cancel callback
  - metrics callback
- 维护当前 active request

### 4.4 `WorkerProcessService`

职责：

- 后续负责：
  - 启动 worker
  - 监控 worker
  - 退出时清理
- 首版可以先只做“连接已有 worker”，不必立刻绑死进程拉起逻辑

---

## 5. 首版功能清单

### Phase 1：协议与连通

- 导入 `.proto`
- 生成 C# classes
- 实现 `FrameCodec`
- 实现 `NamedPipeClient`
- 完成：
  - `HELLO`
  - `HEALTH`

**验收标准**：

- Unity Play Mode 下可以成功连接 pipe
- 能显示 worker 名称、版本、当前 active model

### Phase 2：真实生成

- 实现 `GENERATE`
- 处理多条 `TOKEN`
- 最终处理 `DONE`
- 做一个最小 Demo UI：
  - 输入框
  - 发送按钮
  - 输出文本框

**验收标准**：

- 输入 prompt 后，文本能逐 token 出现在 UI 上
- 最终能收到 `DONE`

### Phase 3：中断与观测

- 实现 `CANCEL`
- 实现 `METRICS`
- UI 增加：
  - 停止按钮
  - metrics 展示

**验收标准**：

- 生成中点击取消后，worker 返回 `DONE(CANCELLED)`
- UI 可展示：
  - active requests
  - total requests
  - completed / failed
  - cancelled / eos / max-token
  - allocated / reserved VRAM

### Phase 4：模型控制

- 实现 `LOAD_MODEL`
- 首版先支持 alias
- UI 中显示：
  - 当前模型
  - 当前 backend
  - kernel pack id

**验收标准**：

- Unity 能发起 `LOAD_MODEL`
- 加载后 `HEALTH` 结果更新

---

## 6. 建议的数据流设计

### 6.1 发送生成请求

```text
UI submit
  -> MiniVllmClient.GenerateAsync()
  -> create request_id
  -> send GENERATE envelope
  -> register callbacks
```

### 6.2 收到 token

```text
read loop
  -> decode envelope
  -> if TOKEN:
       find pending request
       append chunk.text
       dispatch OnToken
```

### 6.3 收到 done

```text
if DONE:
  -> mark request complete
  -> dispatch OnCompleted
  -> remove pending request
```

### 6.4 取消

```text
Cancel button
  -> send CANCEL(target_request_id)
  -> worker returns CANCEL_REPLY
  -> original GENERATE later returns DONE(CANCELLED)
```

注意：  
`CANCEL_REPLY accepted=true` 不等于“立刻没有后续 token”。当前 worker 在 decode step 边界取消，所以有可能 `CANCEL_REPLY` 后再到达一个 token，然后才是 `DONE(CANCELLED)`。

---

## 7. 首版 UI 建议

不需要先做成最终游戏 UI。建议先做一个开发态 Demo 面板：

```text
┌──────────────────────────────┐
│ Worker: READY                │
│ Model: qwen3-0.6b            │
│ Backend: megakernel_cuda     │
│ Kernel Pack: cp312-cu128...  │
├──────────────────────────────┤
│ Prompt 输入框                │
│ [Send] [Cancel] [Load Model] │
├──────────────────────────────┤
│ Streaming Output             │
│ ...                          │
├──────────────────────────────┤
│ Metrics                      │
│ active / total / done / ...  │
└──────────────────────────────┘
```

这块 UI 的意义不是好看，而是**尽快暴露客户端真实需求**。

---

## 8. 必须提前考虑的工程问题

### 8.1 Unity 主线程与后台读循环

Named Pipe 读取不应阻塞主线程。  
建议：

- 后台 Task 负责 read loop
- 通过线程安全队列把事件投递回主线程
- MonoBehaviour 在 `Update()` 中 drain queue

### 8.2 断线恢复

首版可以先做到：

- 连接失败时显示 disconnected
- 提供手动 reconnect

后续再做：

- 自动重连
- Worker 进程自动拉起

### 8.3 Pending request 映射

至少要维护：

```text
request_id -> request state
```

否则：

- token 无法正确归属
- cancel 无法命中原请求
- 多请求扩展时会立即乱套

### 8.4 不要把协议逻辑散落在 UI 里

UI 只订阅事件，不直接拼 protobuf。

这件事越早守住，后面游戏逻辑越干净。

---

## 9. 当前 Worker 对 Unity 侧的可依赖契约

Unity 现在可以安全依赖：

- 1 条 request 会有唯一 `request_id`
- 生成请求的返回序列为：
  - `TOKEN*`
  - `DONE`
- 取消请求的返回序列为：
  - `CANCEL_REPLY`
  - 原请求稍后 `DONE(CANCELLED)`
- `HEALTH` 可用来读取：
  - active model
  - backend
  - kernel pack id
- `METRICS` 可用来读取：
  - 请求计数
  - 完成原因计数
  - 显存使用

---

## 10. 仍应并行推进的 Worker 侧工作

Unity 可以开工，但 Python 侧建议继续并行做：

1. `LOAD_MODEL` 的 manifest 化
2. 模型切换与 active request 的冲突策略
3. `warmup=true` 的语义
4. 更完整的 GPU 支持矩阵
5. release runtime 打包

这些不是 Unity 开工的前置条件，但会影响最终产品形状。

---

## 11. 建议执行顺序

```text
1. 复制 proto 到 Unity 项目
2. 生成 C# 协议代码
3. 写 FrameCodec
4. 写 NamedPipeClient
5. 写 MiniVllmClient
6. 做 HELLO / HEALTH
7. 做 GENERATE / TOKEN / DONE
8. 做 CANCEL
9. 做 METRICS
10. 做 LOAD_MODEL
11. 做 Demo Scene
12. 再决定 Worker 进程托管方式
```

---

## 12. 最终判断

可以开始 Unity 项目，而且现在开始是最合适的时机。

因为底层协议已经足够稳定，继续只在 Python 侧打磨会开始产生边际递减；  
而 Unity 接入会立刻告诉我们哪些协议、状态机和错误路径还不够贴近真实游戏。

接下来真正有价值的，不只是“把它做出来”，而是让游戏世界第一次真正碰到这套 runtime。
