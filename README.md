# MiniVLLM Windows Runtime

纯 Windows 原生 LLM 推理运行时，通过 Named Pipe + Protobuf 与 Unity 游戏引擎集成，最终随游戏一起交付给玩家。

## 项目定位

在不修改上游 [minivllm](https://github.com/BoundlessWindMoon/minivllm) 源码的前提下，构建一套 Windows 可交付的 GPU 推理运行时外壳。上游负责模型架构与高性能内核，本项目负责 Windows 适配、IPC 通信、Unity 客户端 SDK 以及玩家交付打包。

```
Unity Game (C#)
    │
    │ Named Pipe + Protobuf
    ▼
MiniVLLMWorker.exe
    │
    ├─ WindowsKernelPack/     ← Windows 适配层
    ├─ MiniVLLMWorker/        ← IPC 服务 + 推理调度
    ├─ Protocol/              ← 协议定义（Python + C# 共享）
    └─ minivllm/              ← 上游 submodule（不改动）
    │
    ▼
NVIDIA GPU (RTX 5070 / sm120)
```

## 当前状态

所有核心路径已验证闭环：

- 真实模型加载与推理（Qwen3-0.6B）
- 预编译 megakernel .pyd（玩家机无需 CUDA Toolkit）
- 真实逐 token 流式输出
- 取消正在运行的生成
- 实时指标上报（含分类完成计数器）
- Unity C# 客户端 SDK（NamedPipe + Protobuf）

## 上游引用

本项目基于 [BoundlessWindMoon/minivllm](https://github.com/BoundlessWindMoon/minivllm)，以 Git submodule 形式引入。

> **上游 minivllm 源码一行未改。** 所有 Windows 适配通过外置 `WindowsKernelPack/` 实现，包括：内核加载拦截、分布式 shim、配置覆盖、流式解码循环。

## 环境要求（开发机）

| 组件 | 版本 |
|---|---|
| Python | 3.12.10 |
| PyTorch | 2.9.1 + cu128 |
| CUDA Toolkit | 12.8.1 |
| triton-windows | 3.5.1.post24 |
| transformers | 4.51.0 |
| Visual Studio | 2022 17.14.x（含 MSVC v143） |
| Ninja | 1.13.0 |
| GPU | NVIDIA RTX 50 系列 (sm120) |

## 快速开始

### 1. 克隆仓库

```bash
git clone --recurse-submodules <your-repo-url>
```

### 2. 安装依赖

```powershell
python -m pip install -r WindowsKernelPack\requirements-win-cu128.txt
```

### 3. 下载模型

将 Qwen3-0.6B 模型文件放入 `Runtime\models\Qwen3-0.6B\`。

### 4. 启动 Worker

```powershell
# 或直接运行
start_minivllm_worker.cmd
```

### 5. 测试连接

```powershell
python -m MiniVLLMWorker.test_client health
python -m MiniVLLMWorker.test_client generate --prompt "你好，请介绍一下你自己。"
python -m MiniVLLMWorker.test_client metrics
```

## 仓库结构

```
f:/CTest/
├── AILog/                  ← 设计文档与验证报告
├── MiniVLLMWorker/         ← Worker 进程（IPC + 推理调度）
├── WindowsKernelPack/      ← Windows 适配层 + 预编译内核
├── Protocol/               ← Protobuf 协议定义 + Python/C# 生成代码
├── UnityProject/           ← Unity 客户端 SDK 与示例场景
├── minivllm/               ← 上游 submodule
├── Runtime/                ← 运行时缓存、日志、模型
└── start_minivllm_worker.cmd  ← 一键启动脚本
```

## 许可证

本项目代码遵循 MIT License。

上游 minivllm 的许可证见 [minivllm 仓库](https://github.com/BoundlessWindMoon/minivllm)。

第三方资源：
- 阿里巴巴普惠体 3.0（45 Light）遵循 SIL Open Font License 1.1
- TextMesh Pro 为 Unity 官方资源包
