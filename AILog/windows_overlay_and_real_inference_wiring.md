# Windows overlay 与真实推理接线说明

## 本轮完成

### 1. Windows config overlay

`WindowsKernelPack/upstream_adapter.py` 现在会：

- 复制原始 `GlobalConfig`；
- 在 Windows 下把 `nccl` 改为 `gloo`；
- 把 `tcp://localhost:*` 规范化为 `tcp://127.0.0.1:*`；
- 在加载模型前初始化 torch 默认 dtype / device 与 distributed runtime。

### 2. 请求级配置映射

`build_request_config()` 会把 `GenerateRequest` 映射到上游 `GlobalConfig`：

- prompt
- max_new_tokens
- stop_on_eos
- use_chat_template
- use_thinking
- sampling method / temperature / topk / topp

### 3. InferenceService 已接入 adapter

`InferenceService` 现在支持两种模式：

```text
adapter 已加载真实模型
  -> 调用真实 minivllm ModelRunner.inference()
  -> 当前以单个 completion chunk 返回

adapter 未加载模型
  -> 保持 echo fallback
  -> 继续服务协议联调
```

### 4. main.py 已支持环境变量加载真实模型

```text
MINIVLLM_CONFIG_PATH
MINIVLLM_MODEL_ALIAS
MINIVLLM_MODE
```

如果设置 `MINIVLLM_CONFIG_PATH`，worker 启动时就会走真实模型加载路径。

## 当前重要边界

现阶段“真实调用”已经接上，但“真实逐 token 流式”还没有接上。原因是当前上游 `ModelRunner.inference()` 返回最终文本，并没有暴露 token callback。

因此首个真实接线形态会是：

```text
worker 外部协议：仍然是 streaming
上游模型边界：当前先是 final text
```

后续若要真正逐 token 流式，需要在 adapter 外层增加自定义 decode loop，或在不改上游仓库的前提下复制/包装一小段 runner 逻辑。

## 下一步建议

1. 安装并验证 Windows 版 PyTorch / Transformers 依赖；
2. 指定真实模型路径与配置，跑第一条真实 generate；
3. 再决定是：
   - 先接受“单 chunk completion”；
   - 还是直接投入做外置 streaming runner。
