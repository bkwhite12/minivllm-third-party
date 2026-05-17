# inference_service.py 与 test_client.py 设计说明

## 新增文件

- `MiniVLLMWorker/inference_service.py`
- `MiniVLLMWorker/test_client.py`

## inference_service.py

`InferenceService` 现在是独立边界，当前先实现 echo generation：

```text
GenerateRequest
  -> TokenChunk*
  -> GenerationResult
```

这么拆以后，后续接真实 `minivllm` 时只需要替换 service 内部，不需要再动：

- `pipe_server.py`
- `protocol_codec.py`
- `request_router.py`
- Unity SDK

## test_client.py

这是没有 Unity 时的最小联调客户端，支持：

```text
hello
health
generate --prompt "你好"
```

它和服务端使用同一套：

- raw Named Pipe
- length-prefixed frame
- Protobuf Envelope

因此它能在 Unity 接入前，先验证本地协议链是否完整。

## 推荐联调顺序

1. 启动 worker：
   - `python -m MiniVLLMWorker.main`
2. 发送 hello：
   - `python -m MiniVLLMWorker.test_client hello`
3. 发送 health：
   - `python -m MiniVLLMWorker.test_client health`
4. 发送 generate：
   - `python -m MiniVLLMWorker.test_client generate --prompt "你好"`

## 当前阶段价值

这一步完成后，系统已经不再只是“有设计”，而是已经具备了：

- 协议定义；
- Python 编解码；
- Named Pipe 服务端；
- 请求路由；
- 生成服务边界；
- 自测客户端。

之后接真实推理，就是把一条已经亮着的空车道接到发动机上。
