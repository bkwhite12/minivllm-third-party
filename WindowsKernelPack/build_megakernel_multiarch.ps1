<#
.SYNOPSIS
Build multiple Windows megakernel prebuilt packs.

.DESCRIPTION
Cross-compiles MiniVLLM megakernel .pyd artifacts for multiple NVIDIA SM
architectures and packages each one under:

    WindowsKernelPack/prebuilt/cp312-cu128-smXX/

This script currently targets Ampere sm86 and Ada sm89 by default. It delegates
the actual build/package/manifest/import verification to build_megakernel.ps1.

On-device smoke execution is only enabled for the architecture matching the
current GPU unless -ForceSmokeAll is passed. Cross-compiled packs are still
verified at import/export level.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel_multiarch.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\WindowsKernelPack\build_megakernel_multiarch.ps1 -Architectures sm86,sm89 -Clean
#>

[CmdletBinding()]
param(
    [string]$ProjectRoot = "",

    [string]$PythonPath = "",

    [string[]]$Architectures = @("sm86", "sm89"),

    [string[]]$Variants = @("default", "all_combined"),

    [switch]$Clean,

    [switch]$SkipVerify,

    [switch]$ForceSmokeAll,

    [string]$VsDevCmd = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-List {
    param([string[]]$Items)
    $out = @()
    foreach ($item in $Items) {
        foreach ($part in ($item -split ",")) {
            $trimmed = $part.Trim()
            if ($trimmed) { $out += $trimmed }
        }
    }
    return @($out | Select-Object -Unique)
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

function Get-CurrentSm {
    param([string]$Python)
    $code = @'
import torch
if torch.cuda.is_available():
    major, minor = torch.cuda.get_device_capability(0)
    print(f'sm{major}{minor}')
else:
    print('')
'@
    $sm = & $Python -c $code
    if ($LASTEXITCODE -ne 0) { return "" }
    return (@($sm)[-1]).Trim()
}

function Resolve-ArchSpec {
    param([string]$Arch)
    $normalized = $Arch.Trim().ToLowerInvariant()
    switch ($normalized) {
        "sm86" { return @{ PackId = "cp312-cu128-sm86"; CudaArchList = "8.6" } }
        "86"   { return @{ PackId = "cp312-cu128-sm86"; CudaArchList = "8.6" } }
        "8.6"  { return @{ PackId = "cp312-cu128-sm86"; CudaArchList = "8.6" } }
        "sm89" { return @{ PackId = "cp312-cu128-sm89"; CudaArchList = "8.9" } }
        "89"   { return @{ PackId = "cp312-cu128-sm89"; CudaArchList = "8.9" } }
        "8.9"  { return @{ PackId = "cp312-cu128-sm89"; CudaArchList = "8.9" } }
        "sm120" { return @{ PackId = "cp312-cu128-sm120"; CudaArchList = "12.0" } }
        "120"   { return @{ PackId = "cp312-cu128-sm120"; CudaArchList = "12.0" } }
        "12.0"  { return @{ PackId = "cp312-cu128-sm120"; CudaArchList = "12.0" } }
        default { throw "Unsupported architecture '$Arch'. Supported: sm86, sm89, sm120." }
    }
}

function ConvertTo-ProjectRelativePath {
    param([string]$Path, [string]$Root)
    if (-not $Path) {
        return ""
    }
    try {
        $full = [System.IO.Path]::GetFullPath($Path)
        $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd([char[]]@('\', '/')) + [System.IO.Path]::DirectorySeparatorChar
        if ($full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $full.Substring($rootFull.Length)
        }
    } catch {
        return $Path
    }
    return $Path
}

$ScriptRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $ScriptRoot "..")).Path
}

$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
$PythonPath = Resolve-PythonPath -Requested $PythonPath -Root $ProjectRoot
$Architectures = ConvertTo-List $Architectures
$Variants = ConvertTo-List $Variants
$BuildScript = Join-Path $ScriptRoot "build_megakernel.ps1"
$CurrentSm = Get-CurrentSm $PythonPath
$Summary = @()

Write-Host ""
Write-Host "==> Multi-architecture megakernel build" -ForegroundColor Cyan
Write-Host "    ProjectRoot   = $ProjectRoot" -ForegroundColor DarkGray
Write-Host "    Architectures = $($Architectures -join ', ')" -ForegroundColor DarkGray
Write-Host "    Variants      = $($Variants -join ', ')" -ForegroundColor DarkGray
Write-Host "    Current GPU   = $CurrentSm" -ForegroundColor DarkGray

foreach ($arch in $Architectures) {
    $spec = Resolve-ArchSpec $arch
    $packId = $spec.PackId
    $cudaArch = $spec.CudaArchList
    $targetSm = ($packId -replace "^.*-", "")
    $canSmoke = $ForceSmokeAll -or ($CurrentSm -and $CurrentSm -eq $targetSm)

    Write-Host ""
    Write-Host "==> Building $packId / TORCH_CUDA_ARCH_LIST=$cudaArch" -ForegroundColor Cyan
    if (-not $canSmoke) {
        Write-Host "    Cross-compile mode: skipping on-device smoke for $targetSm on current GPU $CurrentSm" -ForegroundColor Yellow
    }

    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$BuildScript`"",
        "-ProjectRoot", "`"$ProjectRoot`"",
        "-PythonPath", "`"$PythonPath`"",
        "-Variants", ($Variants -join ","),
        "-CudaArchList", "`"$cudaArch`"",
        "-PackId", "`"$packId`""
    )
    if ($Clean) { $args += "-Clean" }
    if (-not $canSmoke) { $args += "-CompileOnly" }
    if ($SkipVerify) { $args += "-SkipVerify" }
    if ($VsDevCmd) {
        $args += "-VsDevCmd"
        $args += "`"$VsDevCmd`""
    }

    $psExe = Join-Path $PSHOME "powershell.exe"
    & $psExe @args
    $exit = $LASTEXITCODE
    if ($exit -ne 0) {
        throw "Build failed for $packId with exit code $exit"
    }

    $manifestPath = Join-Path $ProjectRoot "WindowsKernelPack\prebuilt\$packId\kernel_manifest.json"
    $Summary += [ordered]@{
        architecture = $targetSm
        pack_id = $packId
        cuda_arch_list = $cudaArch
        smoke_mode = if ($canSmoke) { "on-device" } else { "compile/import-only" }
        manifest = ConvertTo-ProjectRelativePath -Path $manifestPath -Root $ProjectRoot
    }
}

$summaryPath = Join-Path $ProjectRoot "Runtime\logs\megakernel_build\multiarch_summary.json"
New-Item -ItemType Directory -Force -Path (Split-Path $summaryPath -Parent) | Out-Null
$Summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding UTF8

Write-Host ""
Write-Host "==> Multi-architecture megakernel build completed" -ForegroundColor Green
Write-Host "Summary: $summaryPath" -ForegroundColor Green
foreach ($item in $Summary) {
    Write-Host "  $($item.pack_id) [$($item.smoke_mode)]" -ForegroundColor Green
}
