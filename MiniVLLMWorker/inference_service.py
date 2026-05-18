"""Inference service boundary for MiniVLLMWorker."""

from __future__ import annotations

import time
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from Protocol.python_generated import minivllm_runtime_pb2 as pb
from WindowsKernelPack.upstream_adapter import (
    GenerationCancelledError,
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


@dataclass(frozen=True, slots=True)
class RuntimeMetricsSnapshot:
    total_requests: int
    completed_requests: int
    failed_requests: int
    active_requests: int
    cancelled_requests: int
    eos_completions: int
    max_token_completions: int


class InferenceService:
    """Generation boundary backed by the upstream adapter when available."""

    def __init__(self, adapter: UpstreamMiniVllmAdapter | None = None) -> None:
        self._adapter = adapter
        self._last_generated: GeneratedText | None = None
        self._active_requests: dict[str, threading.Event] = {}
        self._active_lock = threading.Lock()
        self._last_finish_reason = pb.MAX_TOKENS
        self._total_requests = 0
        self._completed_requests = 0
        self._failed_requests = 0
        self._cancelled_requests = 0
        self._eos_completions = 0
        self._max_token_completions = 0

    @property
    def adapter(self) -> UpstreamMiniVllmAdapter | None:
        return self._adapter

    def stream_generate(
        self,
        request_id: str,
        request: pb.GenerateRequest,
    ) -> Iterable[pb.TokenChunk]:
        """Yield reply chunks for one request.

        With a loaded upstream adapter, current minivllm integration returns the
        final completion as one chunk because upstream ModelRunner exposes final
        text, not token callbacks. Without a loaded adapter, dev mode falls back
        to deterministic echo chunks so transport tests remain cheap.
        """
        cancel_event = threading.Event()
        with self._active_lock:
            self._active_requests[request_id] = cancel_event
            self._total_requests += 1
        self._last_finish_reason = pb.MAX_TOKENS
        try:
            if self._adapter is not None and self._adapter.loaded is not None:
                try:
                    for generated_token in self._adapter.stream_generate_tokens(
                        request,
                        is_cancelled=cancel_event.is_set,
                    ):
                        chunk = pb.TokenChunk()
                        chunk.text = generated_token.text
                        chunk.token_id = generated_token.token_id
                        chunk.index = generated_token.index
                        chunk.is_special = generated_token.is_special
                        yield chunk
                except GenerationCancelledError:
                    self._last_finish_reason = pb.CANCELLED
                else:
                    self._last_finish_reason = self._adapter.last_finish_reason
                self._last_generated = self._adapter.last_stream_result
                return

            self._last_generated = None
            text = request.prompt or ""
            for index, char in enumerate(text):
                if cancel_event.is_set():
                    self._last_finish_reason = pb.CANCELLED
                    break
                chunk = pb.TokenChunk()
                chunk.text = char
                chunk.token_id = -1
                chunk.index = index
                chunk.is_special = False
                yield chunk
        finally:
            with self._active_lock:
                self._active_requests.pop(request_id, None)

    def cancel(self, request_id: str) -> bool:
        with self._active_lock:
            event = self._active_requests.get(request_id)
        if event is None:
            return False
        event.set()
        return True

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
            finish_reason=self._last_finish_reason,
            prompt_tokens=prompt_tokens,
            generated_tokens=emitted_tokens,
            ttft_ms=ttft_ms,
            total_latency_ms=total_latency_ms,
            tokens_per_sec=tokens_per_sec,
        )

    def mark_completed(self, *, failed: bool = False, finish_reason: int = pb.MAX_TOKENS) -> None:
        with self._active_lock:
            if failed:
                self._failed_requests += 1
            else:
                self._completed_requests += 1
                if finish_reason == pb.CANCELLED:
                    self._cancelled_requests += 1
                elif finish_reason == pb.EOS:
                    self._eos_completions += 1
                else:
                    self._max_token_completions += 1

    def metrics_snapshot(self) -> RuntimeMetricsSnapshot:
        with self._active_lock:
            return RuntimeMetricsSnapshot(
                total_requests=self._total_requests,
                completed_requests=self._completed_requests,
                failed_requests=self._failed_requests,
                active_requests=len(self._active_requests),
                cancelled_requests=self._cancelled_requests,
                eos_completions=self._eos_completions,
                max_token_completions=self._max_token_completions,
            )

    @staticmethod
    def _now_ms() -> int:
        return time.time_ns() // 1_000_000
