using System;
using System.Buffers.Binary;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Google.Protobuf;

namespace MiniVllm.Runtime.Transport
{
    public static class FrameCodec
    {
        private const int HeaderSize = 4;

        public static async Task WriteAsync(
            Stream stream,
            IMessage message,
            CancellationToken cancellationToken = default)
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            if (message == null) throw new ArgumentNullException(nameof(message));

            var payload = message.ToByteArray();
            var header = new byte[HeaderSize];
            BinaryPrimitives.WriteUInt32LittleEndian(header, checked((uint)payload.Length));

            await stream.WriteAsync(header, 0, header.Length, cancellationToken);
            await stream.WriteAsync(payload, 0, payload.Length, cancellationToken);
            await stream.FlushAsync(cancellationToken);
        }

        public static async Task<T> ReadAsync<T>(
            Stream stream,
            MessageParser<T> parser,
            CancellationToken cancellationToken = default)
            where T : IMessage<T>
        {
            if (stream == null) throw new ArgumentNullException(nameof(stream));
            if (parser == null) throw new ArgumentNullException(nameof(parser));

            var header = new byte[HeaderSize];
            await ReadExactlyAsync(stream, header, cancellationToken);
            var payloadLength = BinaryPrimitives.ReadUInt32LittleEndian(header);
            var payload = new byte[payloadLength];
            await ReadExactlyAsync(stream, payload, cancellationToken);
            return parser.ParseFrom(payload);
        }

        private static async Task ReadExactlyAsync(
            Stream stream,
            byte[] buffer,
            CancellationToken cancellationToken)
        {
            var offset = 0;
            while (offset < buffer.Length)
            {
                var read = await stream.ReadAsync(
                    buffer,
                    offset,
                    buffer.Length - offset,
                    cancellationToken);
                if (read == 0)
                {
                    throw new EndOfStreamException("Unexpected end of stream while reading a framed protobuf message.");
                }

                offset += read;
            }
        }
    }
}
