"""Inference service boundary for MiniVLLMWorker."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from Protocol.python_generated import minivllm_runtime_pb2 as pb
from WindowsKernelPack.upstream_adapter import (
    GeneratedText,
    ModelNotLoadedError,
    UpstreamMiniVllmAdapter,
)


@dataclass(slots=True)
class GenerationResult:
    text: str
    finish_reason: int
    prompt_tokens: int
    generated_tokens: int
    ttft_ms: int
    total_latency_ms: int
    tokens_per_sec: float


class InferenceService:
    """Generation boundary backed by the upstream adapter when available."""

    def __init__(self, adapter: UpstreamMiniVllmAdapter | None = None) -> None:
        self._adapter = adapter
        self._last_generated: GeneratedText | None = None

    @property
    def adapter(self) -> UpstreamMiniVllmAdapter | None:
        return self._adapter

    def stream_generate(self, request: pb.GenerateRequest) -> Iterable[pb.TokenChunk]:
        """Yield reply chunks for one request.

        With a loaded upstream adapter, current minivllm integration returns the
        final completion as one chunk because upstream ModelRunner exposes final
        text, not token callbacks. Without a loaded adapter, dev mode falls back
        to deterministic echo chunks so transport tests remain cheap.
        """
        if self._adapter is not None and self._adapter.loaded is not None:
            generated = self._adapter.generate_text(request)
            self._last_generated = generated
            chunk = pb.TokenChunk()
            chunk.text = generated.completion_text
            chunk.token_id = -1
            chunk.index = 0
            chunk.is_special = False
            yield chunk
            return

        self._last_generated = None
        text = request.prompt or ""
        for index, char in enumerate(text):
            chunk = pb.TokenChunk()
            chunk.text = char
            chunk.token_id = -1
            chunk.index = index
            chunk.is_special = False
            yield chunk

    def complete_generation(
        self,
        request: pb.GenerateRequest,
        *,
        emitted_tokens: int,
        started_at_ms: int,
        first_token_at_ms: int | None,
    ) -> GenerationResult:
        finished_at_ms = self._now_ms()
        generated_text = self._last_generated
        text = generated_text.full_text if generated_text is not None else (request.prompt or "")
        prompt_tokens = len(request.prompt or "")
        ttft_ms = 0 if first_token_at_ms is None else max(0, first_token_at_ms - started_at_ms)
        total_latency_ms = max(0, finished_at_ms - started_at_ms)
        tokens_per_sec = (
            emitted_tokens / (total_latency_ms / 1000.0)
            if total_latency_ms > 0 and emitted_tokens > 0
            else 0.0
        )
        return GenerationResult(
            text=text,
            finish_reason=pb.MAX_TOKENS,
            prompt_tokens=prompt_tokens,
            generated_tokens=emitted_tokens,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tokens_per_sec=tokens_per_sec,
        )

    @staticmethod
    def _now_ms() -> int:
        return time.time_ns() // 1_000_000
