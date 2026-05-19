# minivllm-third-party
MiniVLLM Windows Runtime — 纯 Windows 原生 LLM 推理运行时。通过 Named Pipe + Protobuf 与 Unity 游戏引擎集成，在不修改上游 minivllm 源码的前提下，构建可随游戏交付给玩家的 GPU 推理外壳。内置预编译 CUDA megakernel、真实逐 token 流式输出、取消与指标上报，目标 GPU 为 NVIDIA RTX 5070 (sm120)。
