"""Thin compatibility layer between the Windows worker and upstream minivllm."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from Protocol.python_generated import minivllm_runtime_pb2 as pb

from .bootstrap import BootstrapResult, initialize


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

    def health_snapshot(self) -> dict[str, str]:
        loaded = self._loaded
        return {
            "active_model": loaded.model_alias if loaded else "",
            "backend": loaded.backend if loaded else "unbound",
            "runtime_root": str(self._bootstrap.paths.runtime_root),
            "upstream_root": str(self._bootstrap.paths.upstream_root),
        }

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

    @staticmethod
    def _sampling_method_name(method: int) -> str:
        if method == pb.GREEDY:
            return "greedy"
        if method == pb.TOP_P:
            return "topp"
        return "greedy"
