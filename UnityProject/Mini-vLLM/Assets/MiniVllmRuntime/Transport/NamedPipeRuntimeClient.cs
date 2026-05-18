using System;
using System.IO.Pipes;
using System.Threading;
using System.Threading.Tasks;

namespace MiniVllm.Runtime.Transport
{
    public sealed class NamedPipeRuntimeClient : IDisposable
    {
        private readonly string _serverName;
        private readonly string _pipeName;
        private NamedPipeClientStream _stream;

        public NamedPipeRuntimeClient(
            string pipeName = "minivllm-runtime",
            string serverName = ".")
        {
            _pipeName = pipeName;
            _serverName = serverName;
        }

        public bool IsConnected => _stream?.IsConnected == true;

        public async Task ConnectAsync(
            int timeoutMilliseconds = 3000,
            CancellationToken cancellationToken = default)
        {
            if (IsConnected) return;

            _stream?.Dispose();
            _stream = new NamedPipeClientStream(
                _serverName,
                _pipeName,
                PipeDirection.InOut,
                PipeOptions.Asynchronous);

            using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeoutCts.CancelAfter(timeoutMilliseconds);
            await _stream.ConnectAsync(timeoutCts.Token);
        }

        public NamedPipeClientStream Stream
        {
            get
            {
                if (_stream == null || !_stream.IsConnected)
                {
                    throw new InvalidOperationException("Named pipe client is not connected.");
                }

                return _stream;
            }
        }

        public void Dispose()
        {
            _stream?.Dispose();
            _stream = null;
        }
    }
}
