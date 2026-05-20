@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

if not defined MINIVLLM_PYTHON (
    if exist "%ROOT%\.venv\Scripts\python.exe" (
        set "MINIVLLM_PYTHON=%ROOT%\.venv\Scripts\python.exe"
    ) else if exist "%ROOT%\Runtime\python\python.exe" (
        set "MINIVLLM_PYTHON=%ROOT%\Runtime\python\python.exe"
    ) else (
        set "MINIVLLM_PYTHON=python"
    )
)

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "MINIVLLM_MODE=release"
set "MINIVLLM_CONFIG_PATH=%ROOT%\Runtime\models\qwen3_0_6b_windows.yaml"
set "MINIVLLM_MODEL_ALIAS=qwen3-0.6b"

if not exist "%ROOT%\Runtime\logs" mkdir "%ROOT%\Runtime\logs"

echo Starting MiniVLLMWorker...
echo Python: %MINIVLLM_PYTHON%
echo Log file: %ROOT%\Runtime\logs\minivllm_worker_latest.log
echo.

"%MINIVLLM_PYTHON%" -m MiniVLLMWorker.main > "%ROOT%\Runtime\logs\minivllm_worker_latest.log" 2>&1

type "%ROOT%\Runtime\logs\minivllm_worker_latest.log"

echo.
echo MiniVLLMWorker exited.
pause
