# minivllm 纯 Windows 运行分析方案（合并定稿）

## 1. 结论先行

在“必须纯 Windows、最终随 Unity 游戏交付给玩家、通过 Named Pipe 本地通信、尽量不改上游 `minivllm`、同时尽可能保留高性能内核”的约束下，最合理的最终架构是：

```text
Unity.exe
  ↓ Named Pipe
MiniVLLMWorker.exe
  ↓
WindowsKernelPack / 导入适配层
  ↓
原版 minivllm 源码
  ↓
triton-windows + 预编译 megakernel .pyd
  ↓
Windows NVIDIA Driver + GPU
```

最终判断：

1. 可以不维护长期 fork 版 `minivllm`；
2. 但不可能完全零适配地“透明搬运”到 Windows；
3. 真正需要维护的不是“Windows 版 minivllm”，而是一套外置的 `WindowsKernelPack`。

换句话说：

```text
可以不大改 minivllm 业务代码
但必须处理 Triton / CUDA extension / 编译器 / PyTorch 版本 / GPU 架构兼容
```

---

## 2. 为什么 WSL 方案应废弃

此前“Windows 外壳 + WSL2 内原样运行”的方案适合开发机，不适合玩家交付：

- 玩家不能被要求安装 WSL / Linux / 虚拟化环境；
- 你后续要与 Unity 游戏集成，目标应是随游戏直接分发；
- 所以运行时必须是纯 Windows 原生形态。

因此，WSL 方案在当前约束下直接出局。

---

## 3. 当前仓库的性能核心与 Windows 阻力

### 3.1 高性能路径主要有两类

#### A. Triton kernel

仓库中大量模块依赖 Triton：

- `kernels/awq_gemm.py`
- `kernels/awq_gemm_wt.py`
- `kernels/awq_gemm_wt_fused.py`
- `layers/activation.py`
- `layers/attention.py`

它们承担 AWQ GEMM、fused dequant、激活、KV cache 写入等能力。

Windows 上并非完全无路，`triton-windows` 是保留这条路径的现实方案；但它与 PyTorch、CUDA、GPU 架构高度绑定，因此必须通过版本矩阵管理。

#### B. 自定义 CUDA C++ extension / megakernel

`kernels/megakernel_cuda/__init__.py` 当前会通过 `torch.utils.cpp_extension.load()` 运行时 JIT 编译 `.cu + .cpp`。

Windows 上不是不能编译，但需要：

- Windows 版 PyTorch CUDA；
- CUDA Toolkit；
- `nvcc`；
- Visual Studio / MSVC Build Tools；
- 正确的 CUDA arch 参数。

研发机可以具备这些条件，玩家机不应该承担这些条件。

---

## 4. 真正的矛盾：研发可行 vs 玩家可交付

### 4.1 研发机可以做

- 安装 CUDA Toolkit；
- 安装 MSVC Build Tools；
- 使用 `triton-windows`；
- JIT 编译 megakernel；
- 验证上游源码在 Windows 上能跑。

### 4.2 玩家机不该做

- 不该安装 Python 开发环境；
- 不该安装 CUDA Toolkit；
- 不该安装 VS Build Tools；
- 不该首次启动时现场编译 `.cu`；
- 不该依赖网络补包。

因此：

```text
Triton：可以保留 JIT，但必须锁环境、做 warmup、控制缓存
Megakernel：正式交付版必须预编译，不应让玩家机现场 build
```

---

## 5. 推荐最终架构

```text
Unity Game (C#)
      |
      | Named Pipe + Protobuf
      v
MiniVLLMWorker.exe
      |
      | bootstrap / import adapter
      v
原版 minivllm 源码
      |
      |-------------------------------|
      |                               |
      v                               v
triton-windows                    prebuilt megakernel .pyd
      |                               |
      └────────────── GPU Runtime ────┘
```

### 5.1 为什么 Unity 不直接嵌 Python

- Worker 崩溃不拖死游戏主进程；
- 模型可以常驻；
- IPC 边界清晰；
- 后续切后端、热更新 runtime、做异常恢复都更容易。

### 5.2 什么叫“本地导入适配”

不改上游仓库，而在外部维护：

- `bootstrap.py`
- 运行时环境变量与缓存路径；
- Windows 特有配置覆盖；
- 预编译 megakernel 优先加载逻辑；
- 必要时对 `torch.utils.cpp_extension.load()` 做 import redirect / monkey patch；
- Worker 生命周期与协议层。

---

## 6. 推荐维护单元：WindowsKernelPack

```text
ThirdParty/minivllm/
  原版上游仓库，尽量不改

WindowsKernelPack/
  ├─ requirements-win-cu128.txt
  ├─ bootstrap.py
  ├─ upstream_adapter.py
  ├─ build_megakernel.ps1
  ├─ patches/
  ├─ prebuilt/
  │  ├─ cp312-cu128-sm86/
  │  ├─ cp312-cu128-sm89/
  │  └─ cp312-cu128-sm120/
  ├─ smoke_tests/
  └─ compatibility_matrix.md
```

你的长期维护对象，应是 `WindowsKernelPack`，不是 `ThirdParty/minivllm`。

---

## 7. 对 Triton 与 Megakernel 的最终判断

### Triton

`triton-windows` 是保留 AWQ / Triton 高性能路径的现实路线。

它的价值：

- 上游 Triton kernel 源码可尽量不动；
- 只在 Windows Runtime Pack 中替换依赖与环境；
- 能保留更多原项目已有能力。

它的代价：

- 版本必须锁死；
- GPU 架构要分级支持；
- 首次 warmup 与 cache 目录要可控；
- 关键 kernel 必须全部做 smoke test。

### Megakernel

megakernel 是最值得保留的性能路径之一。

最终策略：

- 开发机可以 JIT；
- 正式交付版必须优先加载预编译 `.pyd`；
- 玩家端缺少兼容模块时应明确报错，而不是退回现场编译。

---

## 8. 产品分期建议

### 长期目标

```text
Windows 原生 + triton-windows + prebuilt megakernel + Unity Named Pipe
```

### 首版产品建议

```text
优先支持：
- Windows 10/11
- NVIDIA GPU
- 固定模型族
- 非量化模型
- megakernel_cuda
- Unity Named Pipe

把 AWQ / Triton 量化路径作为增强项推进，而不是阻塞首发
```

原因不是否定 Triton，而是把“首版最稳路径”和“最终完整版图”分层处理。

---

## 9. 首版固定版本矩阵

| 组件 | 固定版本 |
|---|---|
| Python | 3.12.10 |
| PyTorch | 2.9.1 + cu128 |
| CUDA Toolkit | 12.8.1 |
| triton-windows | 3.5.1.post24 |
| transformers | 4.51.0 |
| Visual Studio Build Tools | 2022 17.14.x |
| MSVC Toolset | v143 |
| Ninja | 1.13.0 |

这组版本专门面向首版 Windows 开发基线，不追求“最新”，追求“可重复”。

---

## 10. 现实难点

### 难点 1：版本锁定

你必须固定：

- Python；
- PyTorch CUDA wheel；
- `triton-windows`；
- CUDA Toolkit；
- MSVC / Build Tools；
- GPU arch；
- 上游 `minivllm` commit。

### 难点 2：GPU 架构分包

至少要考虑：

- `sm86`
- `sm89`
- `sm120`

### 难点 3：当前上游功能组合并非全兼容

现版本中，`megakernel_cuda` 与 `use_quantized_model == true` 是互斥的。

---

## 11. 最终定稿

### 最终技术路线

```text
原版 minivllm + 外置 WindowsKernelPack + MiniVLLMWorker.exe + Unity Named Pipe
```

### 最终工程原则

```text
- 不维护长期 fork
- 玩家端不现场编译 megakernel
- Triton 路线保留，但受版本与架构矩阵约束
- 首版优先打通最稳的高性能路径
- 上游变化集中在外置适配层吸收
```

> 这不是把 Linux 项目“简单搬到 Windows”，而是在 Windows 上为它建一套可交付的 GPU 运行时地基。
