# pipe_server.py 设计说明

## 位置

- `MiniVLLMWorker/pipe_server.py`

## 当前选择

服务端采用：

```text
pywin32 raw Named Pipe
+
自定义长度前缀帧
+
Protobuf 消息体
```

而不是 `multiprocessing.connection.Listener(AF_PIPE)`。

原因：

- `multiprocessing.connection` 会额外引入它自己的传输封装；
- Unity 侧会使用原生 `NamedPipeClientStream`；
- 为了让 C# 与 Python 完全共享同一条线协议，服务端应直接处理原始字节流。

## 线协议

```text
[4 bytes little-endian payload length][protobuf payload]
```

## pipe_server.py 的职责

- 创建 `\\.\pipe\minivllm-runtime`；
- 接受多个本地客户端；
- 调用 `protocol_codec.py` 读写帧；
- 将请求交给外部 handler；
- 支持 handler 返回：
  - `None`
  - 单个 reply
  - 多个 reply（用于流式 token）

## 刻意不负责的事情

- 不负责模型加载；
- 不负责消息路由；
- 不负责业务错误映射；
- 不负责 protobuf 生成代码。

这些应由后续的：

- `request_router.py`
- `inference_service.py`
- 生成后的 `*_pb2.py`

承担。

## 新增运行时依赖

- `pywin32`

这是为了获得真正可与 Unity 原生 Named Pipe 客户端对接的 Win32 管道字节流。
