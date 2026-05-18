"""Thin compatibility layer between the Windows worker and upstream minivllm."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from Protocol.python_generated import minivllm_runtime_pb2 as pb

from .bootstrap import BootstrapResult, initialize
from .prebuilt_loader import load_prebuilt


@dataclass(slots=True)
class LoadedModelHandle:
    model: Any
    tokenizer: Any
    config: Any
    model_alias: str
    backend: str
    config_path: Path


@dataclass(frozen=True, slots=True)
class GeneratedText:
    full_text: str
    completion_text: str


@dataclass(frozen=True, slots=True)
class GeneratedToken:
    text: str
    token_id: int
    index: int
    is_special: bool = False


class GenerationCancelledError(RuntimeError):
    """Raised when an active generation is cancelled by the caller."""


class ModelNotLoadedError(RuntimeError):
    """Raised when generation is requested before a model is loaded."""


class UpstreamMiniVllmAdapter:
    """First-pass façade over upstream minivllm."""

    def __init__(
        self,
        *,
        runtime_root: str | Path | None = None,
        mode: str = "dev",
    ) -> None:
        self._bootstrap: BootstrapResult = initialize(runtime_root, mode=mode)
        self._loaded: LoadedModelHandle | None = None
        self._kernel_pack_id = ""
        self._last_stream_result: GeneratedText | None = None
        self._install_windows_megakernel_loader()

    @property
    def bootstrap(self) -> BootstrapResult:
        return self._bootstrap

    @property
    def loaded(self) -> LoadedModelHandle | None:
        return self._loaded

    def load_model_from_config(
        self,
        config_path: str | Path,
        *,
        model_alias: str = "default",
    ) -> LoadedModelHandle:
        """Load upstream model/tokenizer using an existing minivllm YAML config."""
        from utils.config import GlobalConfig
        from engine.loader import load_model

        cfg = GlobalConfig.from_yaml(str(config_path))
        cfg = self.apply_windows_overlay(cfg)
        self._ensure_runtime_initialized(cfg)
        model, tokenizer = load_model(cfg)
        handle = LoadedModelHandle(
            model=model,
            tokenizer=tokenizer,
            config=cfg,
            model_alias=model_alias,
            backend=cfg.inference.backend,
            config_path=Path(config_path).expanduser().resolve(),
        )
        self._loaded = handle
        return handle

    def apply_windows_overlay(self, cfg):
        """Return a Windows-safe copy of an upstream config object."""
        cfg = copy.deepcopy(cfg)
        if os.name == "nt":
            if cfg.env.distributed.backend == "nccl":
                cfg.env.distributed.backend = "gloo"
            if cfg.env.distributed.init_method.startswith("tcp://localhost"):
                port = cfg.env.distributed.init_method.rsplit(":", 1)[-1]
                cfg.env.distributed.init_method = f"tcp://127.0.0.1:{port}"
        return cfg

    def build_request_config(self, request: pb.GenerateRequest):
        loaded = self._require_loaded()
        cfg = copy.deepcopy(loaded.config)
        cfg.inference.prompt = request.prompt
        cfg.inference.max_new_tokens = request.max_new_tokens
        cfg.inference.stop_on_eos = request.stop_on_eos
        cfg.inference.use_chat_template = request.use_chat_template
        cfg.inference.use_thinking = request.use_thinking
        cfg.inference.sampling.sample_method = self._sampling_method_name(request.sampling.method)
        cfg.inference.sampling.temperature = request.sampling.temperature
        cfg.inference.sampling.topk = request.sampling.top_k
        cfg.inference.sampling.topp = request.sampling.top_p
        return cfg

    def generate_text(self, request: pb.GenerateRequest) -> GeneratedText:
        """Run one real upstream generation request and return final text.

        Current upstream exposes final-text generation through ModelRunner rather
        than token callbacks, so the first true integration is non-streaming at
        the model boundary. The worker can still preserve the external stream
        contract and later replace this with a token-yielding adapter hook.
        """
        from engine.model_runner import ModelRunner

        loaded = self._require_loaded()
        cfg = self.build_request_config(request)
        if hasattr(loaded.model, "reset"):
            loaded.model.reset()
        runner = ModelRunner(model=loaded.model, tokenizer=loaded.tokenizer, cfg=cfg)
        full_text = runner.inference()
        prompt = request.prompt or ""
        completion = full_text[len(prompt):] if prompt and full_text.startswith(prompt) else full_text
        return GeneratedText(full_text=full_text, completion_text=completion)

    def stream_generate_tokens(
        self,
        request: pb.GenerateRequest,
        *,
        is_cancelled=None,
    ) -> Iterable[GeneratedToken]:
        """Run a real upstream generation loop and yield text as tokens arrive."""
        from engine.model_runner import ModelRunner
        from engine.context import set_context
        import torch

        loaded = self._require_loaded()
        cfg = self.build_request_config(request)
        if hasattr(loaded.model, "reset"):
            loaded.model.reset()
        runner = ModelRunner(model=loaded.model, tokenizer=loaded.tokenizer, cfg=cfg)
        runner.use_progress = False

        input_ids = runner.input_ids
        position_ids = runner.position_ids
        prompt_seq_len = input_ids.shape[1]
        past_len = 0
        generated_ids: list[int] = []
        previous_text = ""

        cu_seqlens_q_prefill = torch.tensor(
            [0, prompt_seq_len], dtype=torch.long, device=runner.device
        )
        set_context(
            is_prefill=True,
            cache_len=past_len,
            cu_seqlens_q=cu_seqlens_q_prefill,
        )
        logits = runner.run(input_ids, position_ids)
        next_token = runner.sampler.sample(logits)

        token_id = int(next_token.item())
        generated_ids.append(token_id)
        past_len += prompt_seq_len
        text = runner.tokenizer.decode(generated_ids, skip_special_tokens=True)
        delta = text[len(previous_text):]
        previous_text = text
        if delta:
            yield GeneratedToken(text=delta, token_id=token_id, index=0)

        current_tokens = 1
        stopped_by_eos = token_id in runner.eos_token_ids
        while current_tokens < runner.max_new_tokens and not stopped_by_eos:
            if is_cancelled is not None and is_cancelled():
                full_text = runner.tokenizer.decode(
                    input_ids[0], skip_special_tokens=True
                ) + previous_text
                prompt = request.prompt or ""
                completion = (
                    full_text[len(prompt):]
                    if prompt and full_text.startswith(prompt)
                    else previous_text
                )
                self._last_stream_result = GeneratedText(
                    full_text=full_text,
                    completion_text=completion,
                )
                raise GenerationCancelledError("generation cancelled")
            logits = runner.run_decode(next_token, past_len)
            next_token = runner.sampler.sample(logits)
            token_id = int(next_token.item())
            generated_ids.append(token_id)
            past_len += 1
            text = runner.tokenizer.decode(generated_ids, skip_special_tokens=True)
            delta = text[len(previous_text):]
            previous_text = text
            if delta:
                yield GeneratedToken(
                    text=delta,
                    token_id=token_id,
                    index=current_tokens,
                )
            current_tokens += 1
            if token_id in runner.eos_token_ids:
                stopped_by_eos = True

        full_text = runner.tokenizer.decode(
            input_ids[0], skip_special_tokens=True
        ) + previous_text
        prompt = request.prompt or ""
        completion = full_text[len(prompt):] if prompt and full_text.startswith(prompt) else previous_text
        self._last_stream_result = GeneratedText(
            full_text=full_text,
            completion_text=completion,
        )

    def health_snapshot(self) -> dict[str, str]:
        loaded = self._loaded
        return {
            "active_model": loaded.model_alias if loaded else "",
            "backend": loaded.backend if loaded else "unbound",
            "kernel_pack_id": self._kernel_pack_id,
            "runtime_root": str(self._bootstrap.paths.runtime_root),
            "upstream_root": str(self._bootstrap.paths.upstream_root),
        }

    @property
    def last_stream_result(self) -> GeneratedText | None:
        return self._last_stream_result

    def to_generate_config(self, request: pb.GenerateRequest) -> dict[str, Any]:
        """Expose the normalized request mapping for diagnostics / tests."""
        return {
            "model_alias": request.model_alias,
            "prompt": request.prompt,
            "max_new_tokens": request.max_new_tokens,
            "stream": request.stream,
            "stop_on_eos": request.stop_on_eos,
            "use_chat_template": request.use_chat_template,
            "use_thinking": request.use_thinking,
            "sampling": {
                "method": self._sampling_method_name(request.sampling.method),
                "temperature": request.sampling.temperature,
                "top_k": request.sampling.top_k,
                "top_p": request.sampling.top_p,
            },
        }

    def _ensure_runtime_initialized(self, cfg) -> None:
        import torch
        import torch.distributed as dist

        torch.set_default_dtype(cfg.env.get_torch_dtype())
        torch.set_default_device(cfg.env.device)
        if os.name == "nt" and cfg.env.distributed.world_size == 1:
            self._install_single_process_dist_shim(dist)
            return
        if not dist.is_initialized():
            dist.init_process_group(
                backend=cfg.env.distributed.backend if torch.cuda.is_available() else "gloo",
                init_method=cfg.env.distributed.init_method,
                world_size=cfg.env.distributed.world_size,
                rank=cfg.env.distributed.rank,
            )

    def _require_loaded(self) -> LoadedModelHandle:
        if self._loaded is None:
            raise ModelNotLoadedError("no model has been loaded")
        return self._loaded

    def _install_windows_megakernel_loader(self) -> None:
        """Prefer prebuilt Windows megakernels and only allow JIT in dev mode."""
        if os.name != "nt":
            return

        from kernels import megakernel_cuda

        original_get_module = megakernel_cuda._get_module
        allow_jit = self._bootstrap.allow_jit_build

        def _get_module_windows_prefer_prebuilt(variant: str | None = None):
            resolved_variant = os.environ.get("MINI_VLLM_MK_VARIANT") or variant or "default"
            if resolved_variant in megakernel_cuda._modules:
                return megakernel_cuda._modules[resolved_variant]

            try:
                module = load_prebuilt(resolved_variant)
                megakernel_cuda._modules[resolved_variant] = module
                self._kernel_pack_id = "cp312-cu128-sm120"
                return module
            except FileNotFoundError:
                if not allow_jit:
                    raise RuntimeError(
                        "Missing prebuilt Windows megakernel "
                        f"for variant {resolved_variant!r}; release mode forbids JIT build."
                    )

            module = original_get_module(resolved_variant)
            megakernel_cuda._modules[resolved_variant] = module
            return module

        megakernel_cuda._get_module = _get_module_windows_prefer_prebuilt

    @staticmethod
    def _install_single_process_dist_shim(dist) -> None:
        """Avoid fragile Gloo init on Windows when tensor parallel world size is 1."""
        dist.get_rank = lambda *args, **kwargs: 0
        dist.get_world_size = lambda *args, **kwargs: 1

    @staticmethod
    def _sampling_method_name(method: int) -> str:
        if method == pb.GREEDY:
            return "greedy"
        if method == pb.TOP_P:
            return "topp"
        return "greedy"
