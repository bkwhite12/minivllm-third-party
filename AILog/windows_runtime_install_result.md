# Windows Runtime 安装结果

## 已完成

| 组件 | 实际状态 |
|---|---|
| Python | 3.12.10 |
| PyTorch | 2.9.1+cu128 |
| CUDA runtime in PyTorch | 12.8 |
| transformers | 4.51.0 |
| triton-windows | 3.5.1.post24 |
| protobuf | 6.33.6 |
| grpcio-tools | 1.80.0 |
| pywin32 | 311 |
| CUDA Toolkit | 12.8.1 |
| Ninja | 1.13.0 |
| Visual Studio | 2022 Community 17.14.5 |
| MSVC Toolset | 14.44.35207 / v143 |

## 验证结果

```text
Python 3.12.10
torch 2.9.1+cu128
torch.version.cuda 12.8
transformers 4.51.0
torch.cuda.is_available() True
GPU NVIDIA GeForce RTX 5070
CUDA Toolkit 12.8.1
Ninja 1.13.0
```

## 说明

- 当前机器原本已经安装 Visual Studio Community 2022 17.14.5，并包含 MSVC v143，因此可以满足构建需求；
- `cl.exe` 在普通终端中通常不会直接出现在 `PATH`，构建 CUDA extension 时应使用 VS Developer Prompt 或显式调用 `VsDevCmd.bat`；
- CUDA Toolkit 已安装到：

```text
C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8
```

- Ninja 已安装到：

```text
C:\Tools\ninja
```
