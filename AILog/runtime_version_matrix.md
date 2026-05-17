# Windows Runtime 版本矩阵（首版锁定）

## 目标机器

- GPU：NVIDIA GeForce RTX 5070
- Compute Capability：`sm120`
- 驱动：596.21（当前开发机）

## 首版固定组合

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
| protobuf | 6.33.6 |
| grpcio-tools | 1.80.0 |
| pywin32 | 311 |

## 为什么锁成这组

1. RTX 50 系列 / `sm120` 需要 CUDA 12.8 及以上；
2. `triton-windows` 的兼容表中，PyTorch 2.9 对应 Triton 3.5；
3. 上游 `minivllm` README 已经按 PyTorch 2.9 组织；
4. CUDA 12.8.1 与 Visual Studio 2022 组合可用于 Windows CUDA 构建；
5. 首版优先减少变量，不追最新支线。

## 安装策略

### 研发机

需要安装：

- Python 3.12.10
- Visual Studio Build Tools 2022 17.14.x
- CUDA Toolkit 12.8.1
- Ninja 1.13.0
- Python 依赖

### 玩家机

不要求安装：

- Python
- CUDA Toolkit
- Visual Studio Build Tools
- Ninja

玩家机只应需要：

- Windows
- NVIDIA Driver
- 满足支持矩阵的 GPU

## 备注

- 这是一份**首版固定矩阵**，不是“永远最新”矩阵；
- 后续升级应通过 `compatibility_matrix.md` 单独记录，不直接覆盖已验证组合；
- 任何一个组件升级，都应重新跑 correctness / benchmark / clean-machine smoke test。
