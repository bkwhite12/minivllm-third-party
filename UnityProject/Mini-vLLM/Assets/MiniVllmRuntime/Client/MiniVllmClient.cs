using System;
using System.Text;
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

        public GenerationSession StartGeneration(
            string prompt,
            Action<TokenChunk> onToken = null,
            int maxNewTokens = 64,
            CancellationToken cancellationToken = default)
        {
            var request = CreateEnvelope(MessageType.Generate);
            request.Generate = new GenerateRequest
            {
                ModelAlias = string.Empty,
                Prompt = prompt ?? string.Empty,
                MaxNewTokens = (uint)Math.Max(1, maxNewTokens),
                Stream = true,
                StopOnEos = true,
                UseChatTemplate = true,
                UseThinking = false,
                Sampling = new SamplingConfig
                {
                    Method = SamplingMethod.Greedy,
                    Temperature = 1.0f,
                    TopK = 1,
                    TopP = 1.0f,
                },
            };

            return new GenerationSession(
                request.RequestId,
                RunGenerationAsync(request, onToken, cancellationToken));
        }

        public async Task<GenerationSessionResult> GenerateAsync(
            string prompt,
            Action<TokenChunk> onToken = null,
            int maxNewTokens = 64,
            CancellationToken cancellationToken = default)
        {
            var session = StartGeneration(prompt, onToken, maxNewTokens, cancellationToken);
            return await session.Completion;
        }

        public async Task<GenerationSessionResult> RunGenerationAsync(
            Envelope request,
            Action<TokenChunk> onToken = null,
            CancellationToken cancellationToken = default)
        {
            await FrameCodec.WriteAsync(_transport.Stream, request, cancellationToken);
            var generatedText = new StringBuilder();
            while (true)
            {
                var response = await FrameCodec.ReadAsync(
                    _transport.Stream,
                    Envelope.Parser,
                    cancellationToken);

                if (response.RequestId != request.RequestId)
                {
                    throw new InvalidOperationException(
                        $"Unexpected response for request {response.RequestId}; expected {request.RequestId}.");
                }

                switch (response.Type)
                {
                    case MessageType.Token:
                        generatedText.Append(response.Token.Text);
                        onToken?.Invoke(response.Token);
                        break;

                    case MessageType.Done:
                        return new GenerationSessionResult(
                            request.RequestId,
                            generatedText.ToString(),
                            response.Done);

                    case MessageType.Error:
                        throw new InvalidOperationException(
                            $"Worker error {response.Error.Code}: {response.Error.Message}");

                    default:
                        throw new InvalidOperationException(
                            $"Unexpected response type during generation: {response.Type}.");
                }
            }
        }

        public async Task<CancelReply> CancelAsync(
            string targetRequestId,
            CancellationToken cancellationToken = default)
        {
            var request = CreateEnvelope(MessageType.Cancel);
            request.Cancel = new CancelRequest
            {
                TargetRequestId = targetRequestId ?? string.Empty,
            };

            var response = await ControlRoundTripAsync(request, cancellationToken);
            if (response.Type != MessageType.CancelReply)
            {
                throw new InvalidOperationException($"Expected CANCEL_REPLY, got {response.Type}.");
            }

            return response.CancelReply;
        }

        public async Task<MetricsReply> MetricsAsync(
            CancellationToken cancellationToken = default)
        {
            var request = CreateEnvelope(MessageType.Metrics);
            request.Metrics = new MetricsReply();

            var response = await ControlRoundTripAsync(request, cancellationToken);
            if (response.Type != MessageType.Metrics)
            {
                throw new InvalidOperationException($"Expected METRICS, got {response.Type}.");
            }

            return response.Metrics;
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

        private static async Task<Envelope> ControlRoundTripAsync(
            Envelope request,
            CancellationToken cancellationToken)
        {
            using var controlTransport = new NamedPipeRuntimeClient();
            await controlTransport.ConnectAsync(cancellationToken: cancellationToken);
            await FrameCodec.WriteAsync(controlTransport.Stream, request, cancellationToken);
            return await FrameCodec.ReadAsync(
                controlTransport.Stream,
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
