"""Initial protobuf request routing for the MiniVLLM worker."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from Protocol.python_generated import minivllm_runtime_pb2 as pb

from .inference_service import InferenceService


PROTOCOL_VERSION = 1


@dataclass(slots=True)
class WorkerRuntimeInfo:
    worker_name: str = "MiniVLLMWorker"
    worker_version: str = "0.1.0-dev"
    runtime_version: str = "windows-dev"
    minivllm_commit: str = "unknown"
    kernel_pack_id: str = "none"
    active_model: str = ""
    backend: str = "unbound"
    gpu_name: str = "unknown"
    gpu_compute_capability: str = "unknown"
    gpu_total_vram_bytes: int = 0
    gpu_free_vram_bytes: int = 0
    gpu_driver_version: str = "unknown"


class RequestRouter:
    """Translate request Envelopes into one or more reply Envelopes."""

    def __init__(
        self,
        runtime_info: WorkerRuntimeInfo | None = None,
        inference_service: InferenceService | None = None,
    ) -> None:
        self._runtime_info = runtime_info or WorkerRuntimeInfo()
        self._inference_service = inference_service or InferenceService()

    def handle(self, request: pb.Envelope) -> pb.Envelope | Iterable[pb.Envelope]:
        if request.protocol_version != PROTOCOL_VERSION:
            return self._error(
                request,
                pb.PROTOCOL_VERSION_UNSUPPORTED,
                f"unsupported protocol version {request.protocol_version}",
                recoverable=False,
            )

        if request.type == pb.HELLO:
            return self._hello_reply(request)
        if request.type == pb.HEALTH:
            return self._health_reply(request)
        if request.type == pb.GENERATE:
            return self._generate_stream(request)

        return self._error(
            request,
            pb.PROTOCOL_VERSION_UNSUPPORTED,
            f"message type {request.type} is not implemented yet",
            recoverable=True,
        )

    def _hello_reply(self, request: pb.Envelope) -> pb.Envelope:
        reply = self._base_reply(request, pb.HELLO_REPLY)
        reply.hello_reply.worker_name = self._runtime_info.worker_name
        reply.hello_reply.worker_version = self._runtime_info.worker_version
        reply.hello_reply.protocol_version = PROTOCOL_VERSION
        reply.hello_reply.supported_features.extend(
            ["protobuf", "named_pipe", "streaming", "health"]
        )
        return reply

    def _health_reply(self, request: pb.Envelope) -> pb.Envelope:
        info = self._runtime_info
        reply = self._base_reply(request, pb.HEALTH_REPLY)
        reply.health_reply.state = pb.READY
        reply.health_reply.active_model = info.active_model
        reply.health_reply.backend = info.backend
        reply.health_reply.runtime_version = info.runtime_version
        reply.health_reply.minivllm_commit = info.minivllm_commit
        reply.health_reply.kernel_pack_id = info.kernel_pack_id
        reply.health_reply.gpu.name = info.gpu_name
        reply.health_reply.gpu.compute_capability = info.gpu_compute_capability
        reply.health_reply.gpu.total_vram_bytes = info.gpu_total_vram_bytes
        reply.health_reply.gpu.free_vram_bytes = info.gpu_free_vram_bytes
        reply.health_reply.gpu.driver_version = info.gpu_driver_version
        return reply

    def _generate_stream(self, request: pb.Envelope) -> Iterable[pb.Envelope]:
        started_at_ms = self._now_ms()
        first_token_at_ms: int | None = None
        emitted_tokens = 0

        for chunk in self._inference_service.stream_generate(request.generate):
            if first_token_at_ms is None:
                first_token_at_ms = self._now_ms()
            token = self._base_reply(request, pb.TOKEN)
            token.token.CopyFrom(chunk)
            emitted_tokens += 1
            yield token

        result = self._inference_service.complete_generation(
            request.generate,
            emitted_tokens=emitted_tokens,
            started_at_ms=started_at_ms,
            first_token_at_ms=first_token_at_ms,
        )
        done = self._base_reply(request, pb.DONE)
        done.done.text = result.text
        done.done.finish_reason = result.finish_reason
        done.done.metrics.prompt_tokens = result.prompt_tokens
        done.done.metrics.generated_tokens = result.generated_tokens
        done.done.metrics.ttft_ms = result.ttft_ms
        done.done.metrics.total_latency_ms = result.total_latency_ms
        done.done.metrics.tokens_per_sec = result.tokens_per_sec
        yield done

    def _error(
        self,
        request: pb.Envelope,
        code: int,
        message: str,
        *,
        recoverable: bool,
    ) -> pb.Envelope:
        reply = self._base_reply(request, pb.ERROR)
        reply.error.code = code
        reply.error.message = message
        reply.error.recoverable = recoverable
        return reply

    @staticmethod
    def _base_reply(request: pb.Envelope, message_type: int) -> pb.Envelope:
        reply = pb.Envelope()
        reply.protocol_version = PROTOCOL_VERSION
        reply.type = message_type
        reply.request_id = request.request_id
        reply.session_id = request.session_id
        reply.trace_id = request.trace_id
        reply.timestamp_ms = RequestRouter._now_ms()
        return reply

    @staticmethod
    def _now_ms() -> int:
        return time.time_ns() // 1_000_000
