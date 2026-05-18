@echo off
call "F:\Program Files\Microsoft Visual Studio\2022\Community\Common7\Tools\VsDevCmd.bat" -arch=x64
set TORCH_EXTENSIONS_DIR=F:\CTest\Runtime\cache\torch_extensions
P:\python.exe F:\CTest\WindowsKernelPack\smoke_megakernel.py %*
