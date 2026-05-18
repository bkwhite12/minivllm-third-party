# Agent 快速上手说明：Windows Runtime 验证

## 1. 先看这里

`verification_handover_20260518.md` 中关于 **“Visual Studio Build Tools / MSVC 未安装”** 的判断已过时。

### 当前真实状态

- Visual Studio 已安装：

```text
Visual Studio Community 2022
Version 17.14.5
Path: F:\Program Files\Microsoft Visual Studio\2022\Community
```

- MSVC 已安装：

```text
MSVC Toolset: 14.44.35207 / v143
cl.exe:
F:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe
```

### 为什么前一个 agent 会误判

普通 PowerShell 中：

```powershell
where.exe cl
```

可能返回找不到。

这不代表 MSVC 未安装，只代表 **当前终端没有加载 Visual Studio 开发环境变量**。

## 2. 正确的环境发现方式

### 2.1 查 Visual Studio

```powershell
& 'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe' -products * -format json
```

### 2.2 查 `cl.exe`

```powershell
Get-ChildItem 'F:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC' -Recurse -Filter cl.exe
```

### 2.3 开启可用的 VS 构建环境

运行：

```powershell
cmd /c '"F:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64 && set'
```

或者直接使用：

```text
x64 Native Tools Command Prompt for VS 2022
```

后续跑 CUDA extension 编译时，务必在这种环境下进行，或在命令前显式调用 `VsDevCmd.bat`。

## 3. 当前已确认环境

```text
Python                  3.12.10
PyTorch                 2.9.1+cu128
CUDA runtime            12.8
CUDA Toolkit            12.8.1
triton-windows          3.5.1
transformers            4.51.0
Ninja                   1.13.0
GPU                     RTX 5070
Compute Capability      sm120
```

## 4. 当前验证状态

### 已完成

- `triton-windows` warmup 已完成；
- Python / PyTorch / CUDA / Ninja 环境已完成；
- Visual Studio / MSVC 已确认存在。

### 现在应继续做

1. 在 VS 开发环境中运行：

```powershell
python WindowsKernelPack\smoke_megakernel.py
```

2. 若 JIT 成功：
   - 从 `TORCH_EXTENSIONS_DIR` 中提取 `.pyd`
   - 整理到：

```text
WindowsKernelPack\prebuilt\cp312-cu128-sm120\
```

3. 再补：
   - `prebuilt_loader.py`
   - 预编译 `.pyd` 独立加载验证

## 5. 关键文件

```text
WindowsKernelPack\warmup_triton.py
WindowsKernelPack\smoke_megakernel.py
WindowsKernelPack\bootstrap.py
WindowsKernelPack\upstream_adapter.py
AILog\verification_handover_20260518.md
```

## 6. 给后续 agent 的一句话

> 这台机器不是“没装 MSVC”，而是“普通 shell 默认没加载 MSVC”。先用 `vswhere` 找实例，再用 `VsDevCmd.bat` 进开发环境，不要再用 `where cl` 单独下结论。
