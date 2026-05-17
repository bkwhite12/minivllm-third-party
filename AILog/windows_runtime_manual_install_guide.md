# Windows Runtime 保姆式手动安装说明

## 0. 目标环境

这份说明用于复刻本项目首版固定开发环境：

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

目标显卡：

- RTX 50 系列；
- 当前开发机：RTX 5070 / `sm120`。

---

## 1. 安装前检查

### 1.1 检查显卡与驱动

打开终端，执行：

```powershell
nvidia-smi
```

确认能看到：

- 显卡名称；
- 驱动版本；
- CUDA Version 字样。

当前项目开发机的参考值：

```text
NVIDIA GeForce RTX 5070
Driver 596.21
Compute Capability sm120
```

### 1.2 建议新开一个干净工作目录

例如：

```text
F:\CTest
```

---

## 2. 安装 Python 3.12.10

### 去哪里找

进入 **Python 官方网站**：

- 访问 `python.org`
- 打开 `Downloads`
- 进入 Python 3.12.10 的 release 页面
- 选择 `Windows installer (64-bit)`

### 安装时怎么选

安装界面中：

1. 勾选 `Add python.exe to PATH`
2. 选择 `Customize installation`
3. 保持常用组件默认勾选
4. 选择当前用户安装即可

### 安装后验证

```powershell
python --version
```

应输出：

```text
Python 3.12.10
```

---

## 3. 安装 Visual Studio Build Tools 2022

### 去哪里找

进入 **Microsoft 官方 Visual Studio 下载页面**：

- 访问 `visualstudio.microsoft.com`
- 找到 `Tools for Visual Studio`
- 下载 `Build Tools for Visual Studio 2022`

### 安装时勾选什么

至少勾选：

- `Desktop development with C++`

右侧组件里确认包含：

- MSVC v143 C++ build tools
- Windows 10/11 SDK
- C++ CMake tools for Windows

### 版本要求

项目首版固定：

```text
Visual Studio Build Tools 2022 17.14.x
MSVC Toolset v143
```

### 安装后验证

打开 **x64 Native Tools Command Prompt for VS 2022**，执行：

```bat
cl
```

能看到 MSVC 版本信息即表示编译器已就位。

---

## 4. 安装 CUDA Toolkit 12.8.1

### 去哪里找

进入 **NVIDIA 官方 CUDA Toolkit Archive**：

- 访问 `developer.nvidia.com`
- 搜索 `CUDA Toolkit Archive`
- 选择 `CUDA Toolkit 12.8.1`
- 平台选择：
  - Operating System: Windows
  - Architecture: x86_64
  - Version: 你的 Windows 版本
  - Installer Type: exe (local) 或 exe (network)

### 安装建议

如果网络稳定：

- `network installer` 更省下载；

如果要做离线留档：

- 用 `local installer`。

安装时保持：

- CUDA Toolkit
- Visual Studio Integration

### 安装后验证

```powershell
nvcc --version
```

应能看到：

```text
release 12.8
```

---

## 5. 安装 Ninja 1.13.0

### 去哪里找

进入 **ninja-build 官方 GitHub Releases**：

- 访问 `github.com`
- 搜索 `ninja-build/ninja`
- 进入 `Releases`
- 找到 `v1.13.0`
- 下载 `ninja-win.zip`

### 怎么放

推荐解压到：

```text
C:\Tools\ninja
```

并把该目录加入 `PATH`。

### 验证

```powershell
ninja --version
```

应输出：

```text
1.13.0
```

---

## 6. 安装 Python 依赖

### 6.1 进入项目目录

```powershell
cd F:\CTest
```

### 6.2 安装固定依赖

```powershell
python -m pip install -r .\WindowsKernelPack\requirements-win-cu128.txt
```

这个文件已经固定：

- `torch==2.9.1`
- `transformers==4.51.0`
- `triton-windows==3.5.1.post24`
- `protobuf==6.33.6`
- `grpcio-tools==1.80.0`
- `pywin32==311`

### 6.3 验证 Python 包

```powershell
python -c "import torch, transformers, triton; print(torch.__version__); print(torch.version.cuda); print(transformers.__version__); print(torch.cuda.is_available())"
```

目标输出应满足：

```text
2.9.1+cu128
12.8
4.51.0
True
```

---

## 7. 验证完整构建链

### 7.1 验证 CUDA / 编译器 / Ninja

```powershell
where.exe nvcc
where.exe cl
where.exe ninja
```

### 7.2 验证 Python CUDA

```powershell
python -c "import torch; print(torch.cuda.get_device_name(0)); print(torch.cuda.get_device_capability(0))"
```

当前 RTX 5070 应看到接近：

```text
NVIDIA GeForce RTX 5070
(12, 0)
```

---

## 8. 常见坑

### 8.1 `torch.cuda.is_available()` 是 False

优先检查：

1. 显卡驱动；
2. 是否装成 CPU 版 PyTorch；
3. 是否使用了 `cu128` wheel。

### 8.2 `nvcc` 找不到

说明：

- CUDA Toolkit 没装；
- 或环境变量没刷新。

先重开终端，再试。

### 8.3 `cl` 找不到

说明：

- VS Build Tools 没装；
- 或你不在 VS Developer Prompt 中。

### 8.4 Triton 报架构不支持

RTX 50 系列需要：

- CUDA 12.8+
- PyTorch 2.7+
- Triton 3.3+

本项目固定组合已经满足这一点；若仍报错，优先核对是否装偏版本。

---

## 9. 建议留档

安装完成后，把以下输出保存到项目日志：

```powershell
python --version
python -c "import torch, transformers; print(torch.__version__); print(torch.version.cuda); print(transformers.__version__)"
nvcc --version
ninja --version
nvidia-smi
```

这样以后重装、换机、排错时，不会再靠记忆考古。
