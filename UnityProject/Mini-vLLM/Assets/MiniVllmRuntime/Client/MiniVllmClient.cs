using System;
using System.Threading;
using System.Threading.Tasks;
using MiniVllm.Runtime.Transport;
using MiniVllm.Runtime.V1;

namespace MiniVllm.Runtime.Client
{
    public sealed class MiniVllmClient : IDisposable
    {
        private const uint ProtocolVersion = 1;
        private readonly NamedPipeRuntimeClient _transport;

        public MiniVllmClient(NamedPipeRuntimeClient transport = null)
        {
            _transport = transport ?? new NamedPipeRuntimeClient();
        }

        public bool IsConnected => _transport.IsConnected;

        public Task ConnectAsync(
            int timeoutMilliseconds = 3000,
            CancellationToken cancellationToken = default)
        {
            return _transport.ConnectAsync(timeoutMilliseconds, cancellationToken);
        }

        public async Task<HelloReply> HelloAsync(
            string clientName,
            string clientVersion,
            CancellationToken cancellationToken = default)
        {
            var request = CreateEnvelope(MessageType.Hello);
            request.Hello = new HelloRequest
            {
                ClientName = clientName ?? string.Empty,
                ClientVersion = clientVersion ?? string.Empty,
            };

            var response = await RoundTripAsync(request, cancellationToken);
            if (response.Type != MessageType.HelloReply)
            {
                throw new InvalidOperationException($"Expected HELLO_REPLY, got {response.Type}.");
            }

            return response.HelloReply;
        }

        public async Task<HealthReply> HealthAsync(
            CancellationToken cancellationToken = default)
        {
            var request = CreateEnvelope(MessageType.Health);
            request.Health = new HealthRequest();

            var response = await RoundTripAsync(request, cancellationToken);
            if (response.Type != MessageType.HealthReply)
            {
                throw new InvalidOperationException($"Expected HEALTH_REPLY, got {response.Type}.");
            }

            return response.HealthReply;
        }

        public void Dispose()
        {
            _transport.Dispose();
        }

        private async Task<Envelope> RoundTripAsync(
            Envelope request,
            CancellationToken cancellationToken)
        {
            await FrameCodec.WriteAsync(_transport.Stream, request, cancellationToken);
            return await FrameCodec.ReadAsync(
                _transport.Stream,
                Envelope.Parser,
                cancellationToken);
        }

        private static Envelope CreateEnvelope(MessageType type)
        {
            return new Envelope
            {
                ProtocolVersion = ProtocolVersion,
                Type = type,
                RequestId = $"req-{Guid.NewGuid():N}",
                SessionId = "unity-session",
                TraceId = $"trace-{Guid.NewGuid():N}",
                TimestampMs = (ulong)DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
        }
    }
}
