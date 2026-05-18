# minivllm Windows 原生运行分析方案（按当前项目实际状态更新）

**更新时间**：2026-05-19  
**目标约束**：

- 必须在 **Windows 原生** 运行，不能依赖 WSL / 虚拟机
- 后续要与 **Unity 游戏** 通信并交付给玩家
- 不走 HTTP，本地通信使用 **Named Pipe**
- 尽量不改上游 `minivllm`
- 保留高性能路径，尤其是 Triton kernel 与 `megakernel_cuda`
- 上游后续更新时，维护成本应尽量集中在外部适配层，而不是长期 fork

---

## 1. 当前结论

这条路线已经从“理论可行”推进到了“Windows 原生关键链路已被验证”：

```text
Unity / 未来游戏侧
        |
        | Named Pipe + Protobuf
        v
MiniVLLMWorker
        |
        | WindowsKernelPack
        |  - bootstrap.py
        |  - upstream_adapter.py
        |  - prebuilt_loader.py
        v
原版 minivllm 源码
        |
        |-----------------------------|
        |                             |
        v                             v
triton-windows                  预编译 megakernel .pyd
        |                             |
        +------------- GPU Runtime ---+
```

最终判断：

1. **不需要维护一份长期分叉的 Windows 版 `minivllm`。**
2. 但也不能幻想“完全透明地原样搬运到 Windows”。真正需要维护的是一层外置的 **Windows Runtime Pack**。
3. 当前项目已经证明：
   - Named Pipe + Protobuf 通信链路可用
   - Windows 原生 PyTorch / CUDA / Triton 环境可用
   - `megakernel_cuda` 可以在 Windows 上原生 JIT 编译
   - `megakernel` 预编译 `.pyd` 可以被直接加载

换句话说，现在要解决的已不是“能不能上 Windows”，而是“怎样把已经跑通的链路收束成可交付产品”。

---

## 2. 为什么 WSL 路线被明确放弃

WSL 适合开发机，不适合你这个交付目标。

- 玩家不能被要求安装 WSL、Linux 用户态或虚拟化环境
- Unity 游戏应当携带自己的本地 runtime，安装路径和生命周期都应由游戏控制
- 你要交付的是一个 Windows 游戏组件，而不是一套开发环境

因此，这个项目的唯一正确方向是：

```text
Windows 原生 Worker + Windows 原生 GPU Runtime + Unity 本地 IPC
```

---

## 3. 当前项目已经采用的真实实现方式

### 3.1 通信层：Named Pipe + Protobuf

当前已实现：

- 协议文件：`Protocol/minivllm_runtime.proto`
- Python 生成代码：`Protocol/python_generated/minivllm_runtime_pb2.py`
- 服务端：`MiniVLLMWorker/pipe_server.py`
- 编解码：`MiniVLLMWorker/protocol_codec.py`
- 路由：`MiniVLLMWorker/request_router.py`
- 客户端自测：`MiniVLLMWorker/test_client.py`

实际帧格式：

```text
[uint32 little-endian length][protobuf payload]
```

这样做有三个好处：

1. Unity 侧接入简单，C# 直接使用同一份 `.proto`
2. 避免 JSON 的解析成本与字段歧义
3. Worker 边界稳定，后续推理后端调整不会影响游戏侧契约

### 3.2 Worker 形态

当前 `MiniVLLMWorker/main.py` 已经具备两种运行形态：

```text
未加载真实模型：
  继续提供 echo fallback
  用于通信联调、协议联调、Unity 侧开发

设置 MINIVLLM_CONFIG_PATH：
  通过 upstream_adapter 加载真实 minivllm 模型
  调用真实 ModelRunner.inference()
```

当前外部协议已经按“流式”设计，但由于上游 `ModelRunner.inference()` 暂时只返回最终文本，所以真实推理接线阶段会先以 **单 chunk completion** 的方式工作；真正逐 token streaming 仍需后续在 adapter 外层增加自定义 decode loop，或进一步包装 runner 逻辑。

---

## 4. WindowsKernelPack：当前真正的维护单元

现在项目中已经存在：

```text
WindowsKernelPack/
  ├─ bootstrap.py
  ├─ upstream_adapter.py
  ├─ prebuilt_loader.py
  ├─ requirements-win-cu128.txt
  ├─ warmup_triton.py
  ├─ smoke_megakernel.py
  ├─ run_smoke_megakernel_vsdev.cmd
  └─ prebuilt/
     └─ cp312-cu128-sm120/
        ├─ mini_vllm_mk_default.cp312-win_amd64.pyd
        ├─ mini_vllm_mk_all_combined.cp312-win_amd64.pyd
        └─ kernel_manifest.json
```

这说明项目已经不再停留在“建议维护一个 WindowsKernelPack”，而是已经按这个方向落地。

### `bootstrap.py` 当前职责

- 统一 runtime 根目录
- 建立缓存目录
- 控制：
  - `TRITON_CACHE_DIR`
  - `CUDA_CACHE_PATH`
  - `TORCH_EXTENSIONS_DIR`
  - `HF_HOME`
  - `TRANSFORMERS_CACHE`
- 注入 repo / upstream import path
- 区分 `dev` 与 `release` 模式
- 设置 `MINIVLLM_ALLOW_JIT_BUILD`

### `upstream_adapter.py` 当前职责

- 对上游 `GlobalConfig` 做 Windows overlay
  - `nccl -> gloo`
  - `tcp://localhost:* -> tcp://127.0.0.1:*`
- 初始化 torch / distributed runtime
- 映射 worker 协议请求到上游配置
- 加载真实模型
- 调用真实 `ModelRunner.inference()`

### `prebuilt_loader.py` 当前职责

- 加载预编译 `.pyd`
- 在加载前把 `torch/lib` 加入 DLL 搜索路径
- 验证预编译模块导出是否完整

---

## 5. 高性能内核路线：当前事实，不再只是预估

### 5.1 Triton 路线

当前固定版本环境下，`triton-windows` 已在 RTX 5070 / `sm120` 上完成 warmup 验证。

当前 warmup 结果：

| 项目 | 结果 |
|---|---|
| vec_add | PASS |
| silu | PASS |
| autotune_relu | PASS |
| bf16_kernel | PASS |
| matmul | FAIL，属于当前测试 kernel 数值问题 |
| softmax | FAIL，属于当前测试 kernel 数值问题 |

分析结论：

- Triton 的 **编译链路** 与 **运行链路** 在当前机器上已经成立
- `autotune`、BF16 等关键能力可以工作
- 现阶段还不能据此宣称“所有上游 Triton kernel 已完全验证”，后续仍需补真实 AWQ / attention kernel 的 smoke test

### 5.2 Megakernel 路线

当前已验证：

- Windows 原生 CUDA JIT 编译成功
- `default` variant 编译成功
- `all_combined` variant 编译成功
- 预编译 `.pyd` 已生成
- `.pyd` 可在不触发 JIT 的情况下独立加载

当前已有产物：

```text
WindowsKernelPack/prebuilt/cp312-cu128-sm120/
  ├─ mini_vllm_mk_default.cp312-win_amd64.pyd
  ├─ mini_vllm_mk_all_combined.cp312-win_amd64.pyd
  └─ kernel_manifest.json
```

重要现实约束：

- 开发机可以 JIT
- 玩家机不应 JIT
- 玩家机交付版应优先加载 prebuilt `.pyd`
- 若缺失匹配产物，正式版应明确报错，而不是让玩家安装 CUDA Toolkit / MSVC 现场编译

---

## 6. 当前已经确认的环境基线

| 组件 | 当前固定版本 |
|---|---|
| Python | 3.12.10 |
| PyTorch | 2.9.1 + cu128 |
| CUDA Runtime | 12.8 |
| CUDA Toolkit | 12.8.1 |
| triton-windows | 3.5.1.post24 |
| transformers | 4.51.0 |
| Visual Studio | Community 2022 17.14.5 |
| MSVC Toolset | 14.44.35207 / v143 |
| Ninja | 1.13.0 |
| 当前验证 GPU | RTX 5070 / sm120 |

这组版本现在不是“建议值”，而是已经被本机验证过的首版基线。

---

## 7. 当前路线的关键设计判断

### 7.1 不 fork 上游，但也不假装零适配

最合理的边界是：

```text
上游 minivllm：
  尽量不改

WindowsKernelPack：
  吸收 Windows 运行差异
  管理版本矩阵
  管理缓存
  管理预编译内核
  管理 import / runtime overlay
```

### 7.2 Unity 不直接嵌 Python

继续保留独立 worker 更稳：

- Worker 崩溃不会直接拖死游戏主进程
- 模型可常驻
- IPC 边界清晰
- 后续换模型、换 runtime、热更新 Worker 都更自由

### 7.3 Protobuf 比 JSON 更适合这条路

当前项目已经从 JSON 方案切到了 Protobuf，这个决定是正确的：

- 跨语言契约更稳
- C# / Python 代码生成成熟
- 二进制体积更小
- 更适合高频本地 IPC

---

## 8. 当前仍未完成的部分

现在真正还没闭环的是这些：

1. **`upstream_adapter.py` 还没有正式接上“Windows 优先 prebuilt、开发态才 JIT”的内核选择逻辑**
2. **真实模型推理闭环还没完成**
   - 已能接到 `ModelRunner.inference()`
   - 但还需要真实模型与真实输出验证
3. **真正逐 token streaming 还没实现**
   - 目前外部协议支持 streaming
   - 上游模型边界暂时仍是 final text
4. **GPU 支持矩阵还只在 `sm120` 上有实测**
   - 后续若要面向更多玩家，需要继续验证 `sm86` / `sm89`
5. **Triton 真实上游 kernel smoke test 仍需补齐**

---

## 9. 当前最合理的产品化顺序

```text
阶段 1：先把 release 路线钉死
  - worker 默认优先加载 prebuilt megakernel
  - release 模式禁止 JIT
  - 缺少匹配 kernel pack 时给出明确错误

阶段 2：打通真实推理闭环
  - 指定真实模型 config
  - 通过 Named Pipe 发起真实 GENERATE
  - 返回真实 completion

阶段 3：补强高性能验证
  - 上游 Triton kernel smoke test
  - real-model warmup
  - 更多 GPU 架构验证

阶段 4：再做产品体验层
  - Unity C# 客户端
  - 进程守护与异常恢复
  - 安装包 / 首启 warmup / 日志与诊断
```

---

## 10. 最终定稿

当前项目的正确描述，不再是：

```text
“想办法把 Linux 项目搬到 Windows”
```

而是：

```text
“在不长期 fork 上游的前提下，为 minivllm 建一套可交付的 Windows 原生 GPU Runtime。”
```

这套 runtime 现在已经有了骨架，也已经有了几块最硬的骨头：

- Windows 原生通信边界
- Windows 原生 CUDA 编译链
- Triton 可运行性
- megakernel 预编译与加载能力

接下来的工作重点，是把这些已经点亮的节点编织成一条玩家机器上也能稳定走通的路。
