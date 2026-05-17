# request_router.py 与 main.py 设计说明

## 位置

- `MiniVLLMWorker/request_router.py`
- `MiniVLLMWorker/main.py`
- `Protocol/python_generated/minivllm_runtime_pb2.py`

## 当前已完成

### 1. 生成 Python Protobuf 模块

由：

- `Protocol/minivllm_runtime.proto`

生成：

- `Protocol/python_generated/minivllm_runtime_pb2.py`

### 2. 初版路由

当前支持：

- `HELLO -> HELLO_REPLY`
- `HEALTH -> HEALTH_REPLY`
- `GENERATE -> TOKEN* + DONE`

### 3. GENERATE 当前行为

当前 `GENERATE` 还没有接真实模型，而是先做确定性的 echo stream：

```text
prompt = "你好"
  -> TOKEN("你")
  -> TOKEN("好")
  -> DONE("你好")
```

这样可以先验证：

- Named Pipe
- 长度前缀
- Protobuf
- 流式多回复
- Unity 侧消费模型

全部闭环。

## 为什么先这样做

在真正接推理前，先把 transport 与 protocol 独立跑通，可以把后续故障面切得很干净：

- 如果 echo 都不通，问题在协议 / 管道；
- 如果 echo 通、模型不通，问题才在 inference_service。

## 下一步

1. 生成一个最小 Python 客户端，用于在没有 Unity 的情况下自测；
2. 运行端到端 `HELLO / HEALTH / GENERATE`；
3. 开始实现 `inference_service.py`，把 echo stream 换成真实生成。
