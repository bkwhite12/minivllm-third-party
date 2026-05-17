# WindowsKernelPack 首版骨架说明

## 新增文件

- `WindowsKernelPack/bootstrap.py`
- `WindowsKernelPack/upstream_adapter.py`

## bootstrap.py 当前负责

- 统一 runtime 目录；
- 创建 cache / logs / models 目录；
- 设置：
  - `TRITON_CACHE_DIR`
  - `CUDA_CACHE_PATH`
  - `TORCH_EXTENSIONS_DIR`
  - `HF_HOME`
  - `TRANSFORMERS_CACHE`
  - `TOKENIZERS_PARALLELISM`
- 把 repo 根目录与上游 `minivllm` 路径放入 `sys.path`；
- 用 `dev/release` 模式控制 `MINIVLLM_ALLOW_JIT_BUILD`。

## upstream_adapter.py 当前负责

- 作为 Worker 与上游 `minivllm` 的窄门；
- 用原版 `GlobalConfig` + `load_model()` 加载模型；
- 缓存已加载模型句柄；
- 提供健康状态快照；
- 先把 Protobuf `GenerateRequest` 归一化为上游友好的 dict。

## 还没有做的事

- 预编译 megakernel 选择；
- 正式接管 `torch.utils.cpp_extension.load()`；
- 真实 generate / stream_generate；
- Windows 特有 config overlay；
- kernel pack manifest 校验。

这些将是下一轮真正把 echo 服务换成模型服务时的核心工作。
