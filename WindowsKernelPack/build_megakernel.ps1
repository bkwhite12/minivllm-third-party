<# 
.SYNOPSIS
Build and package Windows prebuilt MiniVLLM megakernel extensions.

.DESCRIPTION
This script automates the Windows megakernel prebuild flow:

1. Enters Visual Studio Developer Command Prompt when needed.
2. JIT-compiles selected megakernel variants through torch cpp_extension.
3. Copies generated .pyd extension modules into WindowsKernelPack/prebuilt/<PackId>.
4. Writes kernel_manifest.json with toolchain/source/build metadata.
5. Verifies packaged .pyd files can be imported by prebuilt_loader.

It keeps upstream minivllm untouched. The output is a Windows Kernel Pack that
release-mode runtime can load without requiring CUDA Toolkit / MSVC on player PCs.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel.ps1 -Clean -Variants default,all_combined

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel.ps1 -CompileOnly
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = "",

    [string]$PythonPath = "",

    [string[]]$Variants = @("default", "all_combined"),

    [string]$CudaArchList = "12.0",

    [string]$PackId = "cp312-cu128-sm120",

    [switch]$Clean,

    [switch]$CompileOnly,

    [switch]$SkipSmoke,

    [switch]$SkipVerify,

    [switch]$NoVsDevShell,

    [string]$VsDevCmd = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Info {
    param([string]$Message)
    Write-Host "    $Message" -ForegroundColor DarkGray
}

function Assert-File {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Name not found: $Path"
    }
}

function Resolve-PythonPath {
    param([string]$Requested, [string]$Root)
    if ($Requested) {
        return $Requested
    }
    if ($env:MINIVLLM_PYTHON) {
        return $env:MINIVLLM_PYTHON
    }

    $candidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $Root "Runtime\python\python.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw "Python not found. Set MINIVLLM_PYTHON or pass -PythonPath."
}

function Find-VsDevCmd {
    if ($VsDevCmd -and (Test-Path -LiteralPath $VsDevCmd -PathType Leaf)) {
        return (Resolve-Path -LiteralPath $VsDevCmd).Path
    }

    $vswhereCandidates = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
        "${env:ProgramFiles}\Microsoft Visual Studio\Installer\vswhere.exe"
    )
    foreach ($candidate in $vswhereCandidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $installPath = & $candidate -latest -products * `
                -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
                -property installationPath
            if ($LASTEXITCODE -eq 0 -and $installPath) {
                $devCmd = Join-Path $installPath "Common7\Tools\VsDevCmd.bat"
                if (Test-Path -LiteralPath $devCmd -PathType Leaf) {
                    return $devCmd
                }
            }
        }
    }

    $fallbacks = @(
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat",
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat",
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Professional\Common7\Tools\VsDevCmd.bat",
        "${env:ProgramFiles}\Microsoft Visual Studio\2022\Enterprise\Common7\Tools\VsDevCmd.bat"
    )
    foreach ($fallback in $fallbacks) {
        if (Test-Path -LiteralPath $fallback -PathType Leaf) {
            return $fallback
        }
    }

    return ""
}

function Test-MsvcEnvironment {
    $cl = Get-Command cl.exe -ErrorAction SilentlyContinue
    if (-not $cl) {
        return $false
    }
    return [bool]$env:VCToolsInstallDir
}

function Invoke-InVsDevShellIfNeeded {
    if ($NoVsDevShell -or (Test-MsvcEnvironment)) {
        return
    }

    $devCmd = Find-VsDevCmd
    if (-not $devCmd) {
        throw "MSVC developer shell not found. Install Visual Studio 2022 C++ workload or pass -VsDevCmd."
    }

    Write-Step "Re-launching inside Visual Studio Developer Shell"
    Write-Info $devCmd

    $argList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-ProjectRoot", "`"$ProjectRoot`"",
        "-PythonPath", "`"$PythonPath`"",
        "-Variants", ($Variants -join ","),
        "-CudaArchList", "`"$CudaArchList`"",
        "-PackId", "`"$PackId`"",
        "-NoVsDevShell"
    )
    if ($Clean) { $argList += "-Clean" }
    if ($CompileOnly) { $argList += "-CompileOnly" }
    if ($SkipSmoke) { $argList += "-SkipSmoke" }
    if ($SkipVerify) { $argList += "-SkipVerify" }

    $psExe = Join-Path $PSHOME "powershell.exe"
    $cmd = "call `"$devCmd`" -arch=x64 -host_arch=x64 && `"$psExe`" $($argList -join ' ')"
    & $env:ComSpec /d /c $cmd
    exit $LASTEXITCODE
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$Stage
    )
    Write-Info ("$FilePath " + ($ArgumentList -join " "))
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$Stage failed with exit code $LASTEXITCODE"
    }
}

function Get-PythonJson {
    param([string]$Code)
    $output = & $PythonPath -c $Code
    if ($LASTEXITCODE -ne 0) {
        throw "Python metadata query failed."
    }
    $jsonLine = @($output)[-1]
    return ($jsonLine | ConvertFrom-Json)
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function ConvertTo-ProjectRelativePath {
    param([string]$Path)
    if (-not $Path) {
        return ""
    }
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
        $root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
        if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $full.Substring($root.Length)
        }
    } catch {
        return $Path
    }
    return $Path
}

function Get-ToolDisplayName {
    param([string]$Path)
    if (-not $Path) {
        return ""
    }
    try {
        return (Split-Path -Leaf $Path)
    } catch {
        return $Path
    }
}

function Get-GitCommitFromRepo {
    param([string]$RepoRoot)
    $gitDir = Join-Path $RepoRoot ".git"
    if (Test-Path -LiteralPath $gitDir -PathType Leaf) {
        $gitDirText = Get-Content -Raw -Encoding UTF8 $gitDir
        if ($gitDirText -match "gitdir:\s*(.+)") {
            $gitDir = Join-Path $RepoRoot $Matches[1].Trim()
        }
    }
    $headPath = Join-Path $gitDir "HEAD"
    if (-not (Test-Path -LiteralPath $headPath -PathType Leaf)) {
        return ""
    }
    $head = (Get-Content -Raw -Encoding UTF8 $headPath).Trim()
    if ($head.StartsWith("ref:")) {
        $refPath = Join-Path $gitDir $head.Substring(4).Trim()
        if (Test-Path -LiteralPath $refPath -PathType Leaf) {
            return (Get-Content -Raw -Encoding UTF8 $refPath).Trim()
        }
        return ""
    }
    return $head
}

function Find-BuiltPyd {
    param(
        [string]$BuildRoot,
        [string]$Variant
    )
    $module = "mini_vllm_mk_$Variant"
    $pydMatches = @(Get-ChildItem -LiteralPath $BuildRoot -Recurse -Filter "$module*.pyd" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    if (-not $pydMatches -or $pydMatches.Count -eq 0) {
        throw "Built .pyd not found for variant '$Variant' under $BuildRoot"
    }
    return $pydMatches[0].FullName
}

function ConvertTo-VariantArray {
    param([string[]]$InputVariants)
    $items = @()
    foreach ($item in $InputVariants) {
        foreach ($part in ($item -split ",")) {
            $trimmed = $part.Trim()
            if ($trimmed) {
                $items += $trimmed
            }
        }
    }
    return @($items | Select-Object -Unique)
}

$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PythonPath = Resolve-PythonPath -Requested $PythonPath -Root $ProjectRoot

Invoke-InVsDevShellIfNeeded

$KernelPackRoot = Join-Path $ProjectRoot "WindowsKernelPack"
$UpstreamRoot = Join-Path $ProjectRoot "minivllm"
$BuildRoot = Join-Path $ProjectRoot "Runtime\build\megakernel_torch_extensions\$PackId"
$PrebuiltRoot = Join-Path $KernelPackRoot "prebuilt\$PackId"
$LogRoot = Join-Path $ProjectRoot "Runtime\logs\megakernel_build"
$Variants = ConvertTo-VariantArray $Variants

Assert-File -Path $PythonPath -Name "Python 3.12"
if (-not (Test-Path -LiteralPath $UpstreamRoot -PathType Container)) {
    throw "minivllm upstream root not found: $UpstreamRoot"
}
if (-not $Variants -or $Variants.Count -eq 0) {
    throw "No megakernel variants specified."
}

Write-Step "Build configuration"
Write-Info "ProjectRoot      = $ProjectRoot"
Write-Info "PythonPath       = $PythonPath"
Write-Info "Variants         = $($Variants -join ', ')"
Write-Info "CudaArchList     = $CudaArchList"
Write-Info "PackId           = $PackId"
Write-Info "BuildRoot        = $BuildRoot"
Write-Info "PrebuiltRoot     = $PrebuiltRoot"
Write-Info "MSVC cl.exe      = $((Get-Command cl.exe -ErrorAction SilentlyContinue).Source)"

if ($Clean) {
    Write-Step "Cleaning previous build output"
    if (Test-Path -LiteralPath $BuildRoot) {
        Remove-Item -LiteralPath $BuildRoot -Recurse -Force
    }
}

New-Item -ItemType Directory -Force -Path $BuildRoot, $PrebuiltRoot, $LogRoot | Out-Null

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:VSLANG = "1033"
$env:TORCH_CUDA_ARCH_LIST = $CudaArchList
$env:TORCH_EXTENSIONS_DIR = $BuildRoot
$env:MINIVLLM_MODE = "dev"
$env:MINIVLLM_ALLOW_JIT_BUILD = "1"
$env:MINIVLLM_KERNEL_PACK_ID = $PackId
$env:MINI_VLLM_MK_VARIANT = ""
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$ProjectRoot;$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $ProjectRoot
}

Write-Step "Collecting toolchain metadata"
$metaCode = @'
import json, platform, shutil, sys
import torch
try:
    import triton
    triton_version = triton.__version__
except Exception:
    triton_version = ''
print(json.dumps({
    'python': sys.version.split()[0],
    'python_executable': sys.executable,
    'platform': platform.platform(),
    'torch': torch.__version__,
    'torch_cuda': torch.version.cuda,
    'cuda_available': torch.cuda.is_available(),
    'gpu_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else '',
    'gpu_capability': '%d.%d' % torch.cuda.get_device_capability(0) if torch.cuda.is_available() else '',
    'triton': triton_version,
    'nvcc': shutil.which('nvcc') or '',
    'cl': shutil.which('cl') or '',
    'ninja': shutil.which('ninja') or '',
}, ensure_ascii=False))
'@
$toolchain = Get-PythonJson $metaCode
if (-not $toolchain.cuda_available) {
    throw "torch.cuda.is_available() is false. Cannot build CUDA megakernel."
}

Write-Info "Python          = $($toolchain.python)"
Write-Info "PyTorch         = $($toolchain.torch)"
Write-Info "Torch CUDA      = $($toolchain.torch_cuda)"
Write-Info "GPU             = $($toolchain.gpu_name) / sm$($toolchain.gpu_capability -replace '\\.', '')"
Write-Info "nvcc            = $($toolchain.nvcc)"
Write-Info "cl              = $($toolchain.cl)"
Write-Info "ninja           = $($toolchain.ninja)"

$artifacts = @()
foreach ($variant in $Variants) {
    Write-Step "Compiling megakernel variant '$variant'"
    $smokeFlag = if ($CompileOnly -or $SkipSmoke) { "False" } else { "True" }
    $variantLog = Join-Path $LogRoot "$variant.log"
    $codeTemplate = @'
import json
from WindowsKernelPack.smoke_megakernel import test_megakernel_jit
result = test_megakernel_jit('__VARIANT__', smoke=__SMOKE__)
print(json.dumps(result, ensure_ascii=False))
if not result.get('jit_success'):
    raise SystemExit(10)
if result.get('smoke_pass') is False:
    raise SystemExit(11)
'@
    $code = $codeTemplate.Replace("__VARIANT__", $variant).Replace("__SMOKE__", $smokeFlag)
    Write-Info "log = $variantLog"
    $variantScript = Join-Path $LogRoot "build_$variant.py"
    $code | Set-Content -LiteralPath $variantScript -Encoding UTF8
    $compileCmd = "`"$PythonPath`" `"$variantScript`" > `"$variantLog`" 2>&1"
    & $env:ComSpec /d /c $compileCmd
    $compileExitCode = $LASTEXITCODE
    Get-Content -LiteralPath $variantLog -Tail 40 -ErrorAction SilentlyContinue
    if ($compileExitCode -ne 0) {
        throw "Compile/smoke failed for variant '$variant'. See $variantLog"
    }

    $builtPyd = Find-BuiltPyd -BuildRoot $BuildRoot -Variant $variant
    $destName = "mini_vllm_mk_$variant.cp312-win_amd64.pyd"
    $destPath = Join-Path $PrebuiltRoot $destName
    Copy-Item -LiteralPath $builtPyd -Destination $destPath -Force
    Write-Info "packaged $destName"

    $artifacts += [ordered]@{
        variant = $variant
        file = $destName
        size_bytes = (Get-Item -LiteralPath $destPath).Length
        sha256 = Get-FileSha256 $destPath
        source_pyd = ConvertTo-ProjectRelativePath $builtPyd
    }
}

Write-Step "Writing kernel manifest"
$gitCommit = Get-GitCommitFromRepo $UpstreamRoot

$manifest = [ordered]@{
    pack_id = $PackId
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    project_root = "."
    upstream_root = "minivllm"
    upstream_commit = $gitCommit
    torch_cuda_arch_list = $CudaArchList
    python = $toolchain.python
    python_executable = Get-ToolDisplayName $toolchain.python_executable
    platform = $toolchain.platform
    torch = $toolchain.torch
    torch_cuda = $toolchain.torch_cuda
    triton = $toolchain.triton
    gpu_name = $toolchain.gpu_name
    gpu_capability = $toolchain.gpu_capability
    nvcc = Get-ToolDisplayName $toolchain.nvcc
    cl = Get-ToolDisplayName $toolchain.cl
    ninja = Get-ToolDisplayName $toolchain.ninja
    path_policy = "project paths are relative; external toolchain paths are recorded by executable name only"
    variants = $artifacts
}
$manifestPath = Join-Path $PrebuiltRoot "kernel_manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Info "manifest = $manifestPath"

if (-not $SkipVerify) {
    Write-Step "Verifying packaged prebuilt modules"
    foreach ($variant in $Variants) {
        $verifyTemplate = @'
from WindowsKernelPack.prebuilt_loader import load_prebuilt
module = load_prebuilt('__VARIANT__', pack_id='__PACK_ID__')
required = ['decode', 'decode_with_logits', 'init_profiler', 'reset_profiler', 'export_profiler', 'destroy_profiler']
missing = [name for name in required if not hasattr(module, name)]
if missing:
    raise SystemExit('missing exports: ' + ', '.join(missing))
print('prebuilt_load=PASS variant=__VARIANT__ module=' + module.__name__)
'@
        $verifyCode = $verifyTemplate.Replace("__VARIANT__", $variant).Replace("__PACK_ID__", $PackId)
        $verifyScript = Join-Path $LogRoot "verify_$variant.py"
        $verifyCode | Set-Content -LiteralPath $verifyScript -Encoding UTF8
        Invoke-Checked -FilePath $PythonPath -ArgumentList @($verifyScript) -Stage "Prebuilt verification for $variant"
    }
}

Write-Step "Megakernel prebuild completed"
Write-Host "Prebuilt pack: $PrebuiltRoot" -ForegroundColor Green
Write-Host "Manifest:      $manifestPath" -ForegroundColor Green
Write-Host "Variants:      $($Variants -join ', ')" -ForegroundColor Green
