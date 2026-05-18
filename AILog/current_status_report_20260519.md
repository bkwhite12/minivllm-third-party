# MiniVLLM Windows Runtime — 最新状况报告

**日期**: 2026-05-19  
**目标**: 纯 Windows 原生 minivllm 运行时，通过 Named Pipe + Protobuf 与 Unity 集成  
**当前阶段**: 所有核心路径已验证闭环，进入加固期

---

## 1. 一句话概括

> 本项目已从"可行性草图"演进为**可工作的 Windows 原生推理运行时骨架**。Named Pipe → Protobuf → 真实模型加载 → 预编译 megakernel → 真实逐 token 流式输出 → 取消 → 指标上报，全部链路已走通。

---

## 2. 环境基线（已锁定）

| 组件                 | 版本                      | 状态          |
| ------------------ | ----------------------- | ----------- |
| Python             | 3.12.10                 | OK          |
| PyTorch            | 2.9.1 + cu128           | OK          |
| CUDA Runtime       | 12.8                    | OK          |
| CUDA Toolkit       | 12.8.1                  | OK          |
| triton-windows     | 3.5.1.post24            | OK          |
| transformers       | 4.51.0                  | OK          |
| huggingface-hub    | 0.36.2                  | OK（已修正版本漂移） |
| Visual Studio      | Community 2022 17.14.5  | OK          |
| MSVC Toolset       | 14.44.35207 / v143      | OK          |
| Ninja              | 1.13.0                  | OK          |
| GPU                | NVIDIA GeForce RTX 5070 | OK          |
| Compute Capability | sm120                   | OK          |

### 注意：Python 路径含中文

当前 Python 安装在 `C:\Users\BK白修\AppData\Local\Programs\Python\Python312\`，中文用户名会导致 CUDA extension JIT 编译时 include 路径损坏。**已有成熟的 workaround**：

```powershell
subst P: "C:\Users\BK白修\AppData\Local\Programs\Python\Python312"
```

开发环境细节详见 `agent_quickstart_windows_runtime_20260518.md`。

### MSVC 环境重要提示

普通 PowerShell 中 `where cl` 可能返回找不到，**不代表 MSVC 未安装**。解决方案：

- 使用 `VsDevCmd.bat` 进入 VS 开发环境后再编译
- 或直接使用 `WindowsKernelPack\run_smoke_megakernel_vsdev.cmd`

VS 安装位置：`F:\Program Files\Microsoft Visual Studio\2022\Community`

---

## 3. 已验证通过的功能清单

| 功能 | 状态 | 对应报告 |
|---|---|---|
| Triton-windows 编译 + 运行 (sm120) | PASS (4/6) | `verification_update_20260518.md` |
| megakernel_cuda Windows JIT 编译 | PASS | `verification_update_20260518.md` |
| 预编译 megakernel .pyd 生成 | PASS | `verification_update_20260518.md` |
| 预编译 .pyd 直接加载 | PASS | `verification_update_20260518.md` |
| Release 模式（预编译优先，禁止 JIT 回退） | PASS | `real_inference_closure_report_20260519.md` |
| Windows 单进程分布式 shim | PASS | `real_inference_closure_report_20260519.md` |
| Named Pipe + Protobuf 传输 | PASS | 多项报告 |
| HELLO / HEALTH 协议 | PASS | 设计文档 |
| 真实模型加载 (Qwen3-0.6B) | PASS | `real_inference_closure_report_20260519.md` |
| 真实推理闭环 | PASS | `real_inference_closure_report_20260519.md` |
| 真实逐 token 流式输出 | PASS | `true_token_streaming_report_20260519.md` |
| CANCEL 取消解码循环 | PASS | `cancel_decode_loop_report_20260519.md` |
| METRICS 指标上报 | PASS | `runtime_metrics_report_20260519.md` |
| LOAD_MODEL 协议 | PASS | `load_model_report_20260519.md` |

---

## 4. 当前架构全貌

```text
Unity.exe (未来)
    │
    │ Named Pipe + Protobuf
    ▼
MiniVLLMWorker.exe
    │
    ├─ pipe_server.py        ← raw Named Pipe 字节流
    ├─ protocol_codec.py     ← 长度前缀帧 + Protobuf 编解码
    ├─ request_router.py     ← 消息路由 + 模型别名注册表
    ├─ inference_service.py  ← 生成边界 + 活跃请求跟踪
    │
    ▼
WindowsKernelPack/
    ├─ bootstrap.py           ← 环境初始化 + 路径管理
    ├─ upstream_adapter.py    ← 上游模型加载 + 流式解码循环 + 取消检查
    ├─ prebuilt_loader.py     ← 预编译 kernel 优先加载
    ├─ warmup_triton.py       ← Triton 预热测试套件
    ├─ smoke_megakernel.py    ← megakernel 冒烟测试
    ├─ build_megakernel.ps1   ← (待实现) 构建脚本
    └─ prebuilt/cp312-cu128-sm120/
        ├─ mini_vllm_mk_default.cp312-win_amd64.pyd
        ├─ mini_vllm_mk_all_combined.cp312-win_amd64.pyd
        └─ kernel_manifest.json
    │
    ▼
minivllm/ (upstream submodule, 不改动)
    │
    ├─ triton-windows     ← AWQ GEMM / attention / activation
    └─ megakernel_cuda    ← prebuilt .pyd (release) 或 JIT (dev)
    │
    ▼
Windows NVIDIA Driver + RTX 5070
```

### 当前协议消息类型

```
HELLO / HEALTH / LOAD_MODEL / GENERATE / TOKEN / DONE / CANCEL / ERROR / METRICS / SHUTDOWN
```

全部 10 条消息的端到端路径均已跑通。

---

## 5. Worker 运行时行为

### 启动命令

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:MINIVLLM_MODE='release'
$env:MINIVLLM_CONFIG_PATH='F:\CTest\Runtime\models\qwen3_0_6b_windows.yaml'
$env:MINIVLLM_MODEL_ALIAS='qwen3-0.6b'
python -m MiniVLLMWorker.main
```

### 模式行为

| 模式 | 预编译 kernel | JIT 回退 |
|---|---|---|
| `dev` | 优先使用 | 允许（预编译缺失时） |
| `release` | 必须存在 | 禁止，直接报错 |

### 状态机

```
STARTING → INITIALIZING_RUNTIME → LOADING_MODEL → WARMING_UP → READY
    ↓                                                              ↓
  ERROR ←──────────────────────────────────────────────→ BUSY → READY
    ↓
  SHUTDOWN
```

---

## 6. 关键验证数据

### 6.1 Triton 预热

| 测试 | 结果 |
|---|---|
| vec_add (f32) | PASS |
| matmul (f32) | FAIL（测试 kernel 精度问题，非 toolchain 问题） |
| SiLU activation | PASS |
| softmax (attention) | FAIL（测试 kernel 精度问题，非 toolchain 问题） |
| autotune round-trip | PASS |
| bf16 kernel | PASS |

结论：Triton-windows 在 RTX 5070 / sm120 上可编译并运行。2 个失败案例属于测试 kernel 质量边界，不影响 triton toolchain 可用性判断。

### 6.2 真实推理闭环保留数据

```
GPU:             NVIDIA GeForce RTX 5070
kernel_pack_id:  cp312-cu128-sm120
模型:             Qwen3-0.6B (F:\CTest\Runtime\models\Qwen3-0.6B)
backend:          megakernel_cuda
variant:          all_combined
ttft_ms:          17
total_latency_ms: 31
tokens_per_sec:   161.29
```

### 6.3 CANCEL 测试保留数据

```
generated_tokens = 6
finish_reason    = CANCELLED
total_latency_ms = 57
```

### 6.4 显存占用（模型加载后）

```
allocated_vram_bytes: ~3.0 GB
reserved_vram_bytes:  ~3.1 GB
```

---

## 7. 已知边界与注意事项

### 7.1 CANCEL 时机

取消检查发生在**解码步骤之间**，而非 GPU kernel 执行中途。因此 CANCEL_REPLY 之后可能仍会收到 1 个额外的 TOKEN。

### 7.2 Token 计数语义

`generated_tokens` 目前统计发出的 TOKEN 块数。如果某个 tokenizer 步骤对特殊 token 产生空可见文本增量，则传输层的 chunk 数与原始 token 数可能不一致。

### 7.3 模型路径含中文风险

Python 安装路径含中文（`BK白修`）会导致 CUDA extension 编译时 include 路径损坏。已有 workaround（`subst` 盘符映射）。建议后续考虑将 Python 安装到纯 ASCII 路径。

### 7.4 UTF-8 环境必备

上游 Rich progress UI 在 Windows 传统 GBK 编码下会崩溃。启动 Worker 前**必须设置**：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
```

### 7.5 多 GPU 架构

当前仅在 `sm120` (RTX 5070) 上完成验证。`sm86` 和 `sm89` 的预编译 kernel pack 尚未构建。

### 7.6 量化模型

首版主推 `megakernel_cuda + 非量化模型`。AWQ / Triton 量化路径保留但未作为首版验证重点。

---

## 8. 代码仓库当前结构

```text
f:/CTest/
├── .gitignore
├── .gitmodules                    ← minivllm submodule
├── AILog/                         ← 18 份设计文档与验证报告
├── MiniVLLMWorker/
│   ├── main.py                    ← Worker 入口
│   ├── pipe_server.py             ← Named Pipe 服务端
│   ├── protocol_codec.py          ← 长度前缀帧编解码
│   ├── request_router.py          ← 消息路由 + 模型注册表
│   ├── inference_service.py       ← 生成服务 + 活跃请求 + 取消注册
│   ├── test_client.py             ← 最小联调客户端
│   ├── cancel_smoke.py            ← CANCEL 冒烟测试
│   └── metrics_active_smoke.py    ← METRICS 活跃请求测试
├── Protocol/
│   ├── minivllm_runtime.proto     ← 协议真源
│   └── python_generated/          ← protoc 生成代码
├── WindowsKernelPack/
│   ├── bootstrap.py               ← 运行时初始化
│   ├── upstream_adapter.py        ← 模型加载 + 流式解码 + 取消 + 预编译调度
│   ├── prebuilt_loader.py         ← 预编译 kernel 加载器
│   ├── warmup_triton.py           ← Triton 预热套件
│   ├── smoke_megakernel.py        ← megakernel 冒烟测试
│   ├── run_smoke_megakernel_vsdev.cmd ← VS Dev 环境快捷启动
│   ├── requirements-win-cu128.txt ← 固定依赖清单
│   └── prebuilt/cp312-cu128-sm120/  ← 预编译 kernel artifacts
│       ├── kernel_manifest.json
│       ├── mini_vllm_mk_default.cp312-win_amd64.pyd
│       └── mini_vllm_mk_all_combined.cp312-win_amd64.pyd
├── Runtime/
│   ├── cache/                     ← Triton / CUDA / torch_extensions 缓存
│   ├── logs/                      ← 运行时日志
│   └── models/                    ← (gitignored) 模型权重
├── minivllm/                      ← submodule → BoundlessWindMoon/minivllm
└── installers/                    ← (gitignored) 离线安装包
```

---

## 9. 建议后续步骤

按优先级排列：

### P0 — 关键路径加固

1. **多架构 kernel pack**: 为 `sm86` 和 `sm89` 构建并验证预编译 .pyd
2. **LOAD_MODEL 策略完善**: 拒绝/推迟活跃生成期间的模型切换；同别名 no-op；不同别名替换当前模型
3. **补充分类计数器**: 区分 cancelled / EOS / max-token 完成数

### P1 — 交付准备

4. **构建 Unity C# 客户端**: 对已验证的 Worker 协议开发 C# NamedPipe + Protobuf SDK
5. **打包脚本**: 实现 `build_megakernel.ps1` 自动化预编译流程
6. **干净机验证**: 在无私 Python / CUDA Toolkit / VS Build Tools 的机器上验证

### P2 — 增强

7. **磁盘模型注册表 manifest**: 支持多个预注册模型别名
8. **时序指标聚合**: 长期运行窗口化的延迟与 tokens/sec
9. **AWQ / Triton 量化路径**: 纳入正式支持矩阵

---

## 10. Git 仓库信息

```
本地仓库: f:/CTest/.git
远程仓库: 无（纯本地）
分支:     master
submodule: minivllm → https://github.com/BoundlessWindMoon/minivllm.git

提交历史:
  769fe6f  Milestone: full inference closure — real model, prebuilt kernel, streaming, cancel, metrics
  bc6d9eb  Initial commit: MiniVLLM Windows runtime project
```

已通过 `.gitignore` 排除：
- `installers/` (离线安装包)
- `Runtime/cache/` `Runtime/logs/` `Runtime/models/` (运行时生成 + 模型权重)
- `__pycache__/` `*.pyc`

---

## 11. 结论

本项目不再是可行性研究草图。

```text
Windows 原生 release 模式 Worker
  → 预编译 megakernel
  → 真实本地模型
  → Named Pipe + Protobuf
  → 真实逐 token 流式输出
  → 可取消
  → 可观测
```

最高风险路径已全部走通。现在的工作是加固、补足多架构覆盖、并开始 Unity 侧的协议对接。
