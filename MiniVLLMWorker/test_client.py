"""Minimal Python Named Pipe client for worker bring-up tests.

Usage examples:
  python -m MiniVLLMWorker.test_client hello
  python -m MiniVLLMWorker.test_client health
  python -m MiniVLLMWorker.test_client generate --prompt "你好"
"""

from __future__ import annotations

import argparse
import os
import time
import uuid

from Protocol.python_generated import minivllm_runtime_pb2 as pb

from .pipe_server import DEFAULT_PIPE_NAME
from .protocol_codec import read_message, write_message

try:
    import pywintypes
    import win32file
except ImportError:  # pragma: no cover - runtime dependency on Windows
    pywintypes = None
    win32file = None


class PipeClientError(RuntimeError):
    """Raised when the local test client cannot use the pipe transport."""


class _Win32PipeClientStream:
    def __init__(self, handle) -> None:
        self._handle = handle

    def read(self, size: int) -> bytes:
        if size == 0:
            return b""
        hr, data = win32file.ReadFile(self._handle, size)
        if hr not in (0,):
            raise OSError(f"ReadFile failed with code {hr}")
        return data

    def write(self, data: bytes) -> int:
        hr, written = win32file.WriteFile(self._handle, data)
        if hr not in (0,):
            raise OSError(f"WriteFile failed with code {hr}")
        return written

    def flush(self) -> None:
        win32file.FlushFileBuffers(self._handle)

    def close(self) -> None:
        win32file.CloseHandle(self._handle)


def connect(pipe_name: str = DEFAULT_PIPE_NAME) -> _Win32PipeClientStream:
    if os.name != "nt":
        raise PipeClientError("test_client is only supported on Windows")
    if win32file is None or pywintypes is None:
        raise PipeClientError("pywin32 is required for the test client")

    handle = win32file.CreateFile(
        pipe_name,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0,
        None,
        win32file.OPEN_EXISTING,
        0,
        None,
    )
    return _Win32PipeClientStream(handle)


def hello_envelope() -> pb.Envelope:
    env = _base_request(pb.HELLO)
    env.hello.client_name = "python-test-client"
    env.hello.client_version = "0.1.0-dev"
    return env


def health_envelope() -> pb.Envelope:
    env = _base_request(pb.HEALTH)
    env.health.SetInParent()
    return env


def generate_envelope(prompt: str) -> pb.Envelope:
    env = _base_request(pb.GENERATE)
    env.generate.model_alias = "echo"
    env.generate.prompt = prompt
    env.generate.max_new_tokens = max(1, len(prompt))
    env.generate.stream = True
    env.generate.sampling.method = pb.GREEDY
    env.generate.sampling.temperature = 1.0
    env.generate.sampling.top_k = 1
    env.generate.sampling.top_p = 1.0
    env.generate.stop_on_eos = True
    return env


def cancel_envelope(target_request_id: str) -> pb.Envelope:
    env = _base_request(pb.CANCEL)
    env.cancel.target_request_id = target_request_id
    return env


def metrics_envelope() -> pb.Envelope:
    env = _base_request(pb.METRICS)
    env.metrics.SetInParent()
    return env


def load_model_envelope(model_alias: str, backend: str = "") -> pb.Envelope:
    env = _base_request(pb.LOAD_MODEL)
    env.load_model.model_alias = model_alias
    env.load_model.backend = backend
    env.load_model.warmup = False
    return env


def run_once(request: pb.Envelope) -> list[pb.Envelope]:
    replies: list[pb.Envelope] = []
    stream = connect()
    try:
        write_message(stream, request)
        while True:
            reply = read_message(stream, pb.Envelope())
            replies.append(reply)
            if reply.type in (
                pb.HELLO_REPLY,
                pb.HEALTH_REPLY,
                pb.LOAD_MODEL_REPLY,
                pb.DONE,
                pb.ERROR,
                pb.CANCEL_REPLY,
                pb.METRICS,
            ):
                return replies
    finally:
        stream.close()


def _base_request(message_type: int) -> pb.Envelope:
    env = pb.Envelope()
    env.protocol_version = 1
    env.type = message_type
    env.request_id = f"req-{uuid.uuid4()}"
    env.session_id = "test-session"
    env.trace_id = f"trace-{uuid.uuid4()}"
    env.timestamp_ms = time.time_ns() // 1_000_000
    return env


def _print_replies(replies: list[pb.Envelope]) -> None:
    for reply in replies:
        if reply.type == pb.METRICS:
            _print_metrics(reply)
        else:
            print(reply)


def _print_metrics(reply: pb.Envelope) -> None:
    rt = reply.metrics.runtime
    print(f"METRICS:")
    print(f"  process_uptime_ms:     {rt.process_uptime_ms}")
    print(f"  total_requests:        {rt.total_requests}")
    print(f"  completed_requests:    {rt.completed_requests}")
    print(f"    cancelled:           {rt.cancelled_requests}")
    print(f"    eos_completions:     {rt.eos_completions}")
    print(f"    max_token:           {rt.max_token_completions}")
    print(f"  failed_requests:       {rt.failed_requests}")
    print(f"  active_requests:       {rt.active_requests}")
    print(f"  allocated_vram_bytes:  {rt.allocated_vram_bytes}")
    print(f"  reserved_vram_bytes:   {rt.reserved_vram_bytes}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hello")
    sub.add_parser("health")
    sub.add_parser("metrics")
    load = sub.add_parser("load-model")
    load.add_argument("--model-alias", required=True)
    load.add_argument("--backend", default="")
    gen = sub.add_parser("generate")
    gen.add_argument("--prompt", required=True)
    cancel = sub.add_parser("cancel")
    cancel.add_argument("--target-request-id", required=True)
    args = parser.parse_args()

    if args.command == "hello":
        request = hello_envelope()
    elif args.command == "health":
        request = health_envelope()
    elif args.command == "metrics":
        request = metrics_envelope()
    elif args.command == "load-model":
        request = load_model_envelope(args.model_alias, args.backend)
    elif args.command == "cancel":
        request = cancel_envelope(args.target_request_id)
    else:
        request = generate_envelope(args.prompt)

    _print_replies(run_once(request))


if __name__ == "__main__":
    main()
