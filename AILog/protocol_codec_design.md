# protocol_codec.py 设计说明

## 位置

- 协议定义：`Protocol/minivllm_runtime.proto`
- Python 编解码器：`MiniVLLMWorker/protocol_codec.py`

## 设计目标

`protocol_codec.py` 只负责一件事：

```text
Protobuf Message
  <->
[length:uint32 little-endian][protobuf bytes]
```

它刻意不依赖 Named Pipe 细节，因此后续无论底层接的是：

- Windows Named Pipe；
- 单元测试内存流；
- 未来的其他本地双工流；

都可以复用同一套 framing 逻辑。

## 当前提供的能力

- `encode_message(message)`：把 protobuf 消息编码成完整 wire frame；
- `decode_message(payload, message)`：把 payload 解回指定 protobuf 类型；
- `write_message(stream, message)`：向二进制流写一帧；
- `read_frame(stream)`：从二进制流读一帧；
- `read_message(stream, message)`：从流中直接读并解码；
- `FrameTooLargeError`：防止异常大帧；
- `UnexpectedEofError`：处理半包/断流；
- `InvalidProtobufFrameError`：处理坏包。

## 线协议

```text
0..3 bytes   uint32 little-endian payload_length
4..N bytes   serialized protobuf payload
```

### 选择 little-endian 的原因

- Windows / x86 平台天然一致；
- 实现简单；
- C# / Python 都容易对齐。

## 为什么不用 JSON

- Protobuf 更紧凑；
- 强类型；
- C# 与 Python 都能由同一份 `.proto` 生成；
- 字段演进更可控；
- 更适合后续长期维护的本地 IPC 协议。

## 下一步建议

下一步应补：

1. 由 `.proto` 生成 Python 模块与 C# 模块；
2. `pipe_server.py`：把 `protocol_codec.py` 接到 Named Pipe 上；
3. 一组单元测试：
   - 正常帧；
   - 半包；
   - 超大帧；
   - 无效 protobuf；
   - 多帧连续读取。
