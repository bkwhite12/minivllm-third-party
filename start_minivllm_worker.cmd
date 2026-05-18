@echo off
setlocal

cd /d F:\CTest

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set MINIVLLM_MODE=release
set MINIVLLM_CONFIG_PATH=F:\CTest\Runtime\models\qwen3_0_6b_windows.yaml
set MINIVLLM_MODEL_ALIAS=qwen3-0.6b

if not exist F:\CTest\Runtime\logs mkdir F:\CTest\Runtime\logs

echo Starting MiniVLLMWorker...
echo Log file: F:\CTest\Runtime\logs\minivllm_worker_latest.log
echo.

"C:\Users\BK°×ÐÞ\AppData\Local\Programs\Python\Python312\python.exe" -m MiniVLLMWorker.main > F:\CTest\Runtime\logs\minivllm_worker_latest.log 2>&1

type F:\CTest\Runtime\logs\minivllm_worker_latest.log

echo.
echo MiniVLLMWorker exited.
pause
