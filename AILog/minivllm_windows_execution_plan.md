# minivllm 纯 Windows 运行执行方案（合并定稿）

## 0. 总体目标

构建一套可随 Unity 游戏一起交付给玩家的纯 Windows 运行时，实现：

- Unity 通过 Named Pipe 与本地推理进程通信；
- 上游 `minivllm` 仓库尽量保持原样；
- 保留高性能 kernel 能力；
- 玩家机器不依赖 WSL、Python 开发环境、CUDA Toolkit、VS Build Tools；
- 后续上游更新时，维护成本主要集中在外置 `WindowsKernelPack`。

推荐结构：

```text
ThirdParty/
  └─ minivllm/

WindowsKernelPack/
  ├─ bootstrap.py
  ├─ upstream_adapter.py
  ├─ build_megakernel.ps1
  ├─ prebuilt/
  ├─ smoke_tests/
  └─ compatibility_matrix.md

MiniVLLMWorker/
  ├─ protocol_codec.py
  ├─ pipe_server.py
  ├─ request_router.py
  ├─ inference_service.py
  └─ main.py

Protocol/
  └─ minivllm_runtime.proto
```

---

## 阶段 1：纯 Windows 可行性验证

目标：先在研发机上确认 Windows 原生路线的真实边界。

步骤：

1. 准备 Windows 研发环境；
   - Python 3.12.10
   - PyTorch 2.9.1 + cu128
   - CUDA Toolkit 12.8.1
   - triton-windows 3.5.1.post24
   - Visual Studio Build Tools 2022 17.14.x
   - MSVC v143
   - Ninja 1.13.0
2. 克隆原版 `minivllm`，保持源码不改；
3. 跑通：
   - `default backend`
   - `megakernel_cuda backend`
4. 分别验证：
   - Triton kernel；
   - Windows 下 CUDA extension JIT；
5. 建立基线：
   - TTFT；
   - tokens/s；
   - 首次启动耗时；
   - warmup 时间；
   - 显存占用。

退出条件：

- Windows 开发机上 `megakernel_cuda + 非量化模型` 稳定跑通；
- `triton-windows` 至少完成关键 smoke test。

---

## 阶段 2：产品边界与支持矩阵收口

固定最终架构：

```text
Unity.exe
  -> Named Pipe + Protobuf
MiniVLLMWorker.exe
  -> WindowsKernelPack
原版 minivllm
  -> triton-windows + prebuilt megakernel
GPU
```

首版支持范围：

- Windows 10/11；
- NVIDIA GPU；
- 固定模型族；
- 单机单 GPU；
- `generate` / `stream_generate` / `cancel` / `health`；
- 首版主推 `megakernel_cuda + 非量化模型`。

---

## 阶段 3：建立 WindowsKernelPack

目标：把所有 Windows 特有适配收进一个长期维护单元。

必须包含：

- `bootstrap.py`
- `upstream_adapter.py`
- `build_megakernel.ps1`
- `prebuilt/`
- `smoke_tests/`
- `compatibility_matrix.md`

当前首版职责：

- 环境变量；
- cache 目录；
- `nccl -> gloo`；
- Windows 路径；
- 上游导入边界；
- 后续预编译 kernel 接入点。

---

## 阶段 4：构建预编译 megakernel 发布链

目标：保留高性能，同时把玩家端现场 JIT 从产品路径中移除。

步骤：

1. 在 Windows 构建机上编译目标 variant；
2. 为目标架构生成：

```text
prebuilt/
  cp312-cu128-sm86/
  cp312-cu128-sm89/
  cp312-cu128-sm120/
```

3. 生成 `kernel_manifest.json`；
4. release 模式只加载预编译模块；
5. dev 模式可允许 JIT。

退出条件：

- 干净机无需 CUDA Toolkit / Build Tools 也能加载 megakernel。

---

## 阶段 5：Triton 运行时稳定化

目标：尽可能保留 Triton 高性能路径，同时让风险可控。

步骤：

1. 锁版本；
2. 固定：
   - `TRITON_CACHE_DIR`
   - `CUDA_CACHE_PATH`
3. 做 warmup；
4. 建 smoke tests；
5. 由数据决定 Triton 是否进入首版。

---

## 阶段 6：实现 MiniVLLMWorker.exe

Worker 负责：

- 模型常驻；
- 请求队列；
- 流式输出；
- 取消；
- 超时；
- 错误映射；
- 指标上报。

生命周期：

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

---

## 阶段 7：设计 Unity Named Pipe + Protobuf 协议与 SDK

协议原则：

- Named Pipe 做本地传输；
- Protobuf 做消息体；
- `.proto` 是 Python 与 C# 的唯一协议真源；
- 使用长度前缀帧；
- 字段只新增，不复用 tag。

核心消息：

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

---

## 阶段 8：玩家交付打包

玩家包包含：

- Unity 游戏本体；
- `MiniVLLMWorker.exe`；
- embedded Python；
- PyTorch runtime；
- `triton-windows` runtime；
- 预编译 megakernel；
- 模型；
- 配置；
- 许可文件。

干净机验证要求：

- 无 Python；
- 无 CUDA Toolkit；
- 无 VS Build Tools；
- 仅有目标 NVIDIA Driver。

---

## 阶段 9：上游更新与长期维护

升级流程：

```text
1. 拉取上游新 commit
2. 跑 WindowsKernelPack 兼容检查
3. 重建预编译 megakernel
4. 跑 Triton smoke
5. 跑 correctness
6. 跑 benchmark diff
7. 跑干净机 smoke
8. 更新 compatibility_matrix.md
9. 发布 runtime 包
```

红线：

- Unity 协议尽量不变；
- Worker 对外 API 尽量不变；
- 上游变化优先在 `WindowsKernelPack` 吸收；
- 不轻易 fork 上游。

---

## 推荐推进顺序

```text
P0  Windows 可行性验证
P1  产品边界与支持矩阵
P2  WindowsKernelPack
P3  预编译 megakernel
P4  Triton 稳定化
P5  MiniVLLMWorker
P6  Unity Named Pipe
P7  玩家交付打包
P8  升级机制
```

---

## 首版与终局的关系

### 首版最稳承诺

```text
- 纯 Windows
- Unity Named Pipe
- 固定模型族
- 非量化模型
- megakernel_cuda
- NVIDIA GPU
```

### 终局能力版图

```text
- 纯 Windows
- Unity Named Pipe
- triton-windows
- AWQ / Triton 量化路径
- 预编译 megakernel
- 多架构 kernel pack
- 可升级 runtime
```

> 玩家该拿到的是已经锻好的运行时，而不是一套等待他们机器现场炼成的工具链。
