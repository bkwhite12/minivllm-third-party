# WindowsKernelPack 实现设计说明（Protobuf 定稿）

## 1. 文档目标

本文承接：

- `minivllm_windows_analysis.md`
- `minivllm_windows_execution_plan.md`

它回答的不是“该不该做”，而是“第一版具体怎么做”。

目标系统：

```text
Unity.exe
  ↓ Named Pipe
MiniVLLMWorker.exe
  ↓
WindowsKernelPack
  ↓
原版 minivllm
  ↓
triton-windows + prebuilt megakernel
  ↓
GPU
```

设计原则：

1. 上游 `minivllm` 尽量不改；
2. Windows 特有逻辑全部外置；
3. 玩家端不做 megakernel 现场编译；
4. Unity 与 Worker 使用 Named Pipe 传输、Protobuf 消息体；
5. Triton 路线保留，但受支持矩阵约束；
6. 上游升级时，尽量只改 `WindowsKernelPack`。

---

## 2. 推荐仓库布局

```text
repo-root/
├─ ThirdParty/
│  └─ minivllm/
│
├─ WindowsKernelPack/
│  ├─ bootstrap.py
│  ├─ runtime_env.py
│  ├─ upstream_adapter.py
│  ├─ prebuilt_loader.py
│  ├─ torch_extension_redirect.py
│  ├─ kernel_manifest.py
│  ├─ runtime_config.py
│  ├─ requirements-win-cu128.txt
│  ├─ build_megakernel.ps1
│  ├─ warmup_triton.py
│  ├─ smoke_tests/
│  ├─ prebuilt/
│  │  ├─ cp312-cu128-sm86/
│  │  ├─ cp312-cu128-sm89/
│  │  └─ cp312-cu128-sm120/
│  ├─ patches/
│  └─ docs/
│
├─ MiniVLLMWorker/
│  ├─ main.py
│  ├─ pipe_server.py
│  ├─ request_router.py
│  ├─ inference_service.py
│  ├─ model_registry.py
│  ├─ worker_state.py
│  ├─ telemetry.py
│  ├─ errors.py
│  └─ config/
│
├─ Protocol/
│  ├─ minivllm_runtime.proto
│  ├─ python_generated/
│  └─ csharp_generated/
│
└─ UnityBridge/
   ├─ RuntimeClient/
   └─ Samples/
```

---

## 3. 分层职责

```text
UnityBridge
  负责游戏侧调用、流式展示、取消与重连

MiniVLLMWorker
  负责进程生命周期、Named Pipe、模型常驻、推理调度

WindowsKernelPack
  负责 Windows 环境、预编译 kernel、上游导入适配、兼容矩阵

ThirdParty/minivllm
  保持原版业务逻辑与高性能实现
```

---

## 4. WindowsKernelPack 设计

### 4.1 `bootstrap.py`

职责：

- 配置环境变量；
- 选择当前机器可用的 kernel pack；
- 校验 manifest；
- 注册预编译 megakernel；
- 根据 `dev/release` 模式决定是否允许 JIT；
- 最后再导入上游模块。

伪代码：

```python
def initialize(runtime_root: Path, mode: str = "release"):
    configure_env(runtime_root)
    pack = select_kernel_pack(runtime_root)
    validate_kernel_pack(pack)
    register_prebuilt_modules(pack)
    install_torch_extension_policy(allow_jit=(mode == "dev"), pack=pack)
    return pack
```

### 4.2 `runtime_env.py`

统一管理：

- `TRITON_CACHE_DIR`
- `CUDA_CACHE_PATH`
- `TORCH_EXTENSIONS_DIR`
- `HF_HOME`
- `TRANSFORMERS_CACHE`
- `TOKENIZERS_PARALLELISM=false`

推荐目录：

```text
runtime_root/
  cache/
    triton/
    cuda/
    torch_extensions/
    hf/
  logs/
  models/
```

### 4.3 `kernel_manifest.json`

```json
{
  "pack_id": "cp312-cu128-sm89",
  "python_tag": "cp312",
  "torch_version": "2.8.0+cu128",
  "cuda_runtime": "12.8",
  "target_arch": "sm89",
  "minivllm_commit": "...",
  "variants": {
    "default": "mini_vllm_mk_default.cp312-win_amd64.pyd",
    "all_combined": "mini_vllm_mk_all_combined.cp312-win_amd64.pyd"
  },
  "sha256": {}
}
```

校验项：

- Python tag；
- PyTorch/CUDA ABI；
- GPU compute capability；
- `minivllm_commit`；
- 文件 hash。

### 4.4 `prebuilt_loader.py`

职责：根据 variant 加载 `.pyd`，并注册到 `sys.modules`，让上游继续按原模块名使用。

### 4.5 `torch_extension_redirect.py`

策略：

```text
release:
  只允许加载预编译模块
  缺失即报错

dev:
  可允许 torch cpp_extension JIT
  构建成功后可回收为新的 prebuilt pack
```

### 4.6 `upstream_adapter.py`

只暴露高层接口：

```python
class UpstreamMiniVllmAdapter:
    def load_model(self, model_alias: str): ...
    def generate(self, request): ...
    def stream_generate(self, request): ...
    def reset(self): ...
```

这样上游更新后，变化优先在这里吸收。

---

## 5. `build_megakernel.ps1`

流程：

```text
1. 校验 Python / Torch / CUDA / MSVC / Ninja
2. 设置 TORCH_CUDA_ARCH_LIST
3. 切到指定 minivllm commit
4. 对目标 variant 触发构建
5. 复制 .pyd 到 prebuilt/<pack_id>/
6. 计算 SHA256
7. 生成 kernel_manifest.json
8. 运行 smoke_megakernel.py
```

示例：

```powershell
./build_megakernel.ps1 `
  -PythonTag cp312 `
  -TorchVersion 2.9.1+cu128 `
  -CudaVersion 12.8.1 `
  -Arch sm120 `
  -Variants default,all_combined `
  -MiniVllmCommit <sha>
```

首版固定矩阵：

```text
Python                 3.12.10
PyTorch                2.9.1 + cu128
CUDA Toolkit           12.8.1
triton-windows         3.5.1.post24
Visual Studio Build Tools 2022 17.14.x
MSVC Toolset           v143
Ninja                  1.13.0
```

---

## 6. Triton 运行时设计

首版策略：

- 保留 `triton-windows` 路线；
- 锁定版本；
- 控制 cache；
- 做 warmup；
- 是否进入正式首发，由支持矩阵决定。

`warmup_triton.py` 至少覆盖：

- AWQ GEMM；
- WT fused GEMM；
- activation；
- attention/KV cache；
- 目标 shape。

---

## 7. MiniVLLMWorker 设计

状态机：

```text
STARTING
  -> INITIALIZING_RUNTIME
  -> LOADING_MODEL
  -> WARMING_UP
  -> READY
  -> BUSY
  -> READY
  -> ERROR
  -> SHUTDOWN
```

核心模块：

- `main.py`
- `pipe_server.py`
- `request_router.py`
- `inference_service.py`
- `telemetry.py`

Worker 负责：

- 模型常驻；
- 请求队列；
- 流式输出；
- 取消；
- 超时；
- 错误映射；
- 指标上报。

---

## 8. Named Pipe + Protobuf 协议设计

### 8.1 传输层

- Named Pipe；
- 双工；
- 长度前缀帧；
- 消息体使用 Protobuf；
- `.proto` 文件作为 Python 与 C# 的唯一协议真源；
- 文本字段统一 UTF-8。

### 8.2 消息类型

```text
HELLO
HEALTH
LOAD_MODEL
GENERATE
TOKEN
DONE
CANCEL
ERROR
METRICS
SHUTDOWN
```

### 8.3 推荐 `.proto`

```proto
syntax = "proto3";
package minivllm.runtime.v1;

enum MessageType {
  MESSAGE_TYPE_UNSPECIFIED = 0;
  HELLO = 1;
  HEALTH = 2;
  LOAD_MODEL = 3;
  GENERATE = 4;
  TOKEN = 5;
  DONE = 6;
  CANCEL = 7;
  ERROR = 8;
  METRICS = 9;
  SHUTDOWN = 10;
}

message Envelope {
  uint32 protocol_version = 1;
  MessageType type = 2;
  string request_id = 3;
  string session_id = 4;
  string trace_id = 5;
  uint64 timestamp_ms = 6;

  oneof payload {
    GenerateRequest generate = 10;
    TokenChunk token = 11;
    DoneReply done = 12;
    ErrorReply error = 13;
    HealthReply health = 14;
    CancelRequest cancel = 15;
  }
}

message SamplingConfig {
  string method = 1;
  float temperature = 2;
  uint32 topk = 3;
  float topp = 4;
}

message GenerateRequest {
  string model = 1;
  string prompt = 2;
  uint32 max_new_tokens = 3;
  bool stream = 4;
  SamplingConfig sampling = 5;
}

message TokenChunk {
  string text = 1;
  int32 token_id = 2;
  uint32 index = 3;
}

message Metrics {
  uint32 ttft_ms = 1;
  float tokens_per_sec = 2;
}

message DoneReply {
  string text = 1;
  string finish_reason = 2;
  Metrics metrics = 3;
}

message ErrorReply {
  string code = 1;
  string message = 2;
  bool recoverable = 3;
}
```

### 8.4 代码生成原则

- Python Worker 与 Unity C# 端都从同一份 `.proto` 生成代码；
- 不允许两端手写重复 DTO；
- `.proto` 版本变化要纳入兼容矩阵；
- 字段只新增，不重排，不复用 tag。

### 8.5 建议错误码

```text
PROTOCOL_VERSION_UNSUPPORTED
GPU_UNSUPPORTED
INSUFFICIENT_VRAM
MODEL_NOT_FOUND
MODEL_LOAD_FAILED
MISSING_PREBUILT_KERNEL
KERNEL_ABI_MISMATCH
TRITON_WARMUP_FAILED
REQUEST_CANCELLED
REQUEST_TIMEOUT
INTERNAL_ERROR
```

---

## 9. UnityBridge SDK 设计

```csharp
public sealed class MiniVllmClient
{
    Task ConnectAsync();
    Task<HealthReply> HealthAsync();
    Task<string> GenerateAsync(GenerateRequest request, CancellationToken ct);
    IAsyncEnumerable<TokenChunk> StreamGenerateAsync(GenerateRequest request, CancellationToken ct);
    Task CancelAsync(string requestId);
}
```

建议：

- 游戏启动先 `HealthAsync`；
- 加载界面期间 warmup；
- NPC 对话用流式接口；
- 切场景时取消未完成生成；
- Worker 崩溃时给明确降级文案。

---

## 10. 玩家交付包布局

```text
GameRoot/
├─ Game.exe
├─ MiniVLLMWorker/
│  ├─ MiniVLLMWorker.exe
│  ├─ python/
│  ├─ site-packages/
│  ├─ WindowsKernelPack/
│  ├─ models/
│  ├─ cache/
│  └─ logs/
└─ data/
```

玩家只需要：

- Windows；
- NVIDIA Driver；
- 满足支持矩阵的 GPU。

---

## 11. 最小开发顺序

```text
1. Windows 研发机跑通 megakernel
2. 预编译 .pyd
3. 完成 bootstrap + prebuilt_loader
4. Worker CLI 跑通
5. Named Pipe + Protobuf 跑通
6. Unity SDK 跑通
7. 干净机测试
8. 再把 Triton/AWQ 纳入正式支持矩阵
```

---

## 12. 验收标准

功能：

- Unity 可发起推理；
- 可流式收 token；
- 可取消；
- Worker 可重启；
- 缺少兼容 pack 时错误明确。

交付：

- 干净机无开发工具也能运行；
- 不需要 WSL；
- 不需要联网补依赖；
- 版本矩阵可追踪。

---

## 13. 最终判断

把协议从 JSON 换成 Protobuf，不只是“更快一点”，而是让这条边界真正长成工程边界：

- 二进制更紧凑；
- 跨语言类型更稳；
- `.proto` 可以成为唯一真源；
- 版本演进更可控。

> 上游负责继续进化，Runtime Pack 负责让它在 Windows 世界里活得体面，Protobuf 则让 Unity 与 Worker 之间说同一种不会慢慢走形的语言。
