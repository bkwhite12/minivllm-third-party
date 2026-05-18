# MiniVLLM 对接分析：模型到底在哪里运行？

**日期**: 2026-05-19  
**问题**: 本项目是如何和 minivllm 对接的？实际推理的模型是在 minivllm 内运行的，还是在当前项目内运行的？

---

## 1. 直接回答

**模型 100% 在 minivllm 内运行**。当前项目（CTest）不包含任何模型架构代码。它是一层**外置的 Windows 运行时适配壳**，负责：

- 环境准备（路径、缓存、import 路径）
- 配置转换（Protobuf → minivllm GlobalConfig）
- 内核加载策略（预编译 .pyd 优先，dev 模式允许 JIT）
- 自定义解码循环（绕过上游 ModelRunner 的 final-text 限制，实现逐 token 流式）
- Named Pipe 传输层

```text
当前项目 CTest 的职责          minivllm 的职责
┌─────────────────────┐      ┌──────────────────────┐
│ Named Pipe 服务      │      │ Qwen3ForCausalLM     │
│ Protobuf 编解码       │      │ Qwen3MegakernelForCausalLM │
│ 消息路由              │ ───→ │ ModelRunner          │
│ 请求计数 / 指标       │      │ Sampler              │
│ 取消注册表            │      │ GlobalConfig         │
│ 模型别名注册表        │      │ load_model()         │
│                      │      │ AWQ GEMM kernels     │
│ Windows 适配 ← 唯一接触面   │ attention kernels    │
│  ├─ config overlay   │      │ megakernel_cuda      │
│  ├─ 预编译 loader     │      │ layer implementations │
│  ├─ dist shim        │      │ tokenizer            │
│  └─ 自定义 decode 循环│      └──────────────────────┘
└─────────────────────┘
```

---

## 2. 调用链路（一次 GENERATE 请求的完整路径）

```
Unity / test_client
  │
  │ Named Pipe (WriteFile)
  │ [4-byte length][protobuf: GENERATE]
  ▼
┌─────────────────────────────────────────────┐
│ pipe_server.py                              │  ← 当前项目
│   read_frame() → decode_message() → Envelope │
│   调用 router.handle(envelope)              │
└────────────┬────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────┐
│ request_router.py                           │  ← 当前项目
│   _generate_stream(request)                 │
│   调用 inference_service.stream_generate()  │
└────────────┬────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────┐
│ inference_service.py                        │  ← 当前项目
│   注册 cancel_event                         │
│   调用 adapter.stream_generate_tokens()     │
└────────────┬────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────┐
│ upstream_adapter.py   ← ★ 关键边界 ★        │  ← 当前项目
│                                             │
│   build_request_config(pb.GenerateRequest)  │
│     → 映射为 minivllm GlobalConfig           │
│                                             │
│   stream_generate_tokens():                 │
│     → 创建 ModelRunner (来自 minivllm)       │
│     → runner.run()      [minivllm prefill]  │
│     → runner.sampler    [minivllm sampler]  │
│     → while loop:                           │
│         runner.run_decode() [minivllm decode]│
│         runner.sampler     [minivllm sample] │
│         tokenizer.decode() [minivllm tokenizer]│
│         yield GeneratedToken  ← 流式产出    │
└────────────┬────────────────────────────────┘
             │ 所有 import 来自 minivllm/
             ▼
┌─────────────────────────────────────────────┐
│ minivllm/engine/model_runner.py             │  ← 上游，不改
│   ModelRunner.run()         → prefill       │
│   ModelRunner.run_decode()  → single decode │
│   ModelRunner.sampler       → greedy/topp   │
└────────────┬────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────┐
│ minivllm/model/qwen3_megakernel.py          │  ← 上游，不改
│   Qwen3MegakernelForCausalLM.forward()      │
│   → 调用 _get_module(variant)               │
│   → 执行 fused CUDA megakernel              │
└────────────┬────────────────────────────────┘
             ▼
┌─────────────────────────────────────────────┐
│ minivllm/kernels/megakernel_cuda/           │  ← 上游，但被拦截
│   _get_module(variant)                      │
│   → 原本：torch.utils.cpp_extension.load()  │
│   → 实际：被 upstream_adapter 替换为        │
│           prebuilt_loader.load_prebuilt()   │
└─────────────────────────────────────────────┘
             │
             ▼
         GPU (RTX 5070)
```

---

## 3. 对接面的四个拦截点

上游 minivllm 源码**一行都没改**。所有 Windows 适配通过四个拦截点实现：

### 拦截点 1：内核加载（最核心）

**位置**: `upstream_adapter.py::_install_windows_megakernel_loader()`

```python
# 在 Adapter 构造时，monkey-patch 掉 minivllm 的 _get_module 函数
megakernel_cuda._get_module = _get_module_windows_prefer_prebuilt
```

替换后的行为：

| 模式 | 有预编译 .pyd | 无预编译 .pyd |
|---|---|---|
| `release` | 直接 `importlib` 加载 | **报错，禁止 JIT** |
| `dev` | 直接加载 | 回退到上游 JIT (`torch.utils.cpp_extension.load`) |

这个拦截确保了**玩家机不需要 CUDA Toolkit / MSVC 就能用 megakernel**。

### 拦截点 2：分布式初始化

**位置**: `upstream_adapter.py::_install_single_process_dist_shim()`

```python
# 单 GPU Windows 下，绕过 Gloo 初始化（Gloo 在 Windows 上不稳定）
dist.get_rank = lambda: 0
dist.get_world_size = lambda: 1
```

上游 minivllm 的 `ModelRunner` 和模型代码只调 `get_rank()` / `get_world_size()` 获取张量并行信息。单进程场景下这两个值恒为 0 和 1，不需要真正的分布式后端。

### 拦截点 3：Config 覆盖

**位置**: `upstream_adapter.py::apply_windows_overlay()`

```python
cfg.env.distributed.backend = "gloo"        # 原值: nccl (Windows 不支持)
cfg.env.distributed.init_method = "tcp://127.0.0.1:..."  # 原值: localhost
```

这发生在 `load_model()` 之前，确保给 minivllm 传入 Windows 兼容的配置。

### 拦截点 4：自定义解码循环

**位置**: `upstream_adapter.py::stream_generate_tokens()`

这是最大的"绕过"——**没有调用上游 `ModelRunner.inference()`**，而是自己重写了 prefill → decode 循环：

```python
# 不使用: runner.inference()  ← 它返回完整文本后才暴露结果

# 而是直接调用底层 primitives:
logits = runner.run(input_ids, position_ids)          # prefill (上游代码)
next_token = runner.sampler.sample(logits)             # sample (上游代码)
# ... 循环 ...
logits = runner.run_decode(next_token, past_len)       # decode (上游代码)
next_token = runner.sampler.sample(logits)             # sample (上游代码)
text = runner.tokenizer.decode(generated_ids)          # decode (上游代码)
yield GeneratedToken(text=delta, token_id=..., index=...)  # ← 流式产出
```

为什么要这样做？因为上游 `ModelRunner.inference()` 只返回最终的完整文本，不暴露中间的 token 回调。要支持真正的逐 token 流式输出，必须在 adapter 层自己写解码循环。

**循环中每一步调用的仍然是 minivllm 的代码**：
- `runner.run()` → `model.forward()` → megakernel CUDA
- `runner.run_decode()` → `model.forward()` → megakernel CUDA
- `runner.sampler.sample()` → greedy / topp sampler
- `runner.tokenizer.decode()` → HuggingFace tokenizer

---

## 4. 谁拥有什么

### minivllm (上游 submodule) 拥有：

| 组件 | 文件 |
|---|---|
| 模型架构 | `model/qwen3.py`, `model/qwen3_megakernel.py` |
| 权重提取 | `model/megakernel_weights.py` |
| 推理引擎 | `engine/model_runner.py`, `engine/sampler.py` |
| 模型加载 | `engine/loader.py` |
| 配置系统 | `utils/config.py` |
| Triton 内核 | `kernels/awq_gemm.py`, `layers/activation.py`, `layers/attention.py` |
| CUDA 内核源码 | `kernels/megakernel_cuda/decode_ldg.cu` 等 |
| JIT 编译逻辑 | `kernels/megakernel_cuda/__init__.py` |
| 分词器 | HuggingFace `AutoTokenizer` |

### 当前项目 (CTest) 拥有：

| 组件 | 文件 | 本质 |
|---|---|---|
| IPC 传输 | `pipe_server.py`, `protocol_codec.py` | 新增 |
| 消息路由 | `request_router.py` | 新增 |
| 请求生命周期 | `inference_service.py` | 新增 |
| 环境初始化 | `bootstrap.py` | 新增 |
| 上游适配 | `upstream_adapter.py` | 新增，最核心 |
| 预编译加载 | `prebuilt_loader.py` | 新增 |
| 协议定义 | `minivllm_runtime.proto` | 新增 |
| 预编译内核 | `prebuilt/*.pyd` | 从 JIT 产物提取 |

---

## 5. 模型权重在哪里

```
F:\CTest\Runtime\models\Qwen3-0.6B\   ← 当前项目管理的路径
  ├── model.safetensors                 (1.5GB, gitignored)
  ├── config.json
  ├── tokenizer.json
  ├── merges.txt / vocab.json
  └── ...

由 minivllm/utils/model_loader.py → AutoTokenizer + AutoConfig + safetensors 加载
```

权重文件存放在当前项目的 `Runtime/models/` 下，但**加载逻辑全部来自 minivllm**（HuggingFace `AutoTokenizer.from_pretrained` + `ModelLoader` + `safetensors`）。

---

## 6. 一个精确的比喻

把 minivllm 想象成一台**发动机**：

```
minivllm = 发动机 (模型架构 + 推理逻辑 + CUDA 内核)
CTest     = 底盘 + 方向盘 + 油门 + 仪表盘
```

- 发动机是 minivllm 原装的，没改装过
- 底盘（Named Pipe）、方向盘（消息路由）、油门（请求调度）、仪表盘（METRICS）都是 CTest 造的
- `upstream_adapter.py` 是发动机与底盘之间的**转接板**：发动机是 Linux 规格的接口，转接板把它对到 Windows 底盘上
- 只有两处做了"绕过"：启动电机（dist shim）和油门拉线（自定义 decode 循环），但发动机本体完全没动

---

## 7. 升级影响分析

当 minivllm 上游更新时，需要检查 CTest 侧的四个拦截点是否仍然兼容：

| 拦截点 | 触碰的上游 API | 稳定性判断 |
|---|---|---|
| 内核加载 | `kernels.megakernel_cuda._get_module` | **低风险** — 只要函数签名不变，patch 就有效 |
| dist shim | `dist.get_rank`, `dist.get_world_size` | **零风险** — Python 标准库 API |
| config overlay | `GlobalConfig` 的字段名 | **低风险** — dataclass 字段，上游增加字段不影响 |
| 自定义 decode | `ModelRunner.run()`, `.run_decode()`, `.sampler`, `tokenizer.decode()` | **中风险** — 这些是核心推理 API，上游改动需重点验证 |

上游升级后最需要验证的是第 4 点——解码循环中调用的 primitives 是否签名一致、行为一致。

---

## 8. 结论

```
模型在哪里运行？ → 在 minivllm 内，100%
模型推理用的是谁的代码？ → minivllm 的原版代码，一行没改
当前项目做了什么？ → 给 minivllm 加了 Windows 运行时外壳 + IPC 通道 + 流式适配
```

> minivllm 负责"怎么算"，CTest 负责"在 Windows 上以什么方式让它算，以及算的结果怎么送出去"。
