"""Windows runtime bootstrap for using upstream minivllm without forking it."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    runtime_root: Path
    repo_root: Path
    upstream_root: Path
    cache_root: Path
    triton_cache: Path
    cuda_cache: Path
    torch_extensions_cache: Path
    hf_cache: Path
    logs_root: Path
    models_root: Path


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    paths: RuntimePaths
    mode: str
    allow_jit_build: bool


def initialize(
    runtime_root: str | os.PathLike[str] | None = None,
    *,
    mode: str = "dev",
    allow_jit_build: bool | None = None,
) -> BootstrapResult:
    """Prepare a Windows-friendly runtime envelope around upstream minivllm.

    This first version focuses on stable pathing and environment ownership. The
    prebuilt-kernel selector will be wired in once the first Windows kernel pack
    exists.
    """
    if mode not in {"dev", "release"}:
        raise ValueError("mode must be either 'dev' or 'release'")

    paths = _resolve_paths(runtime_root)
    _ensure_directories(paths)
    _configure_environment(paths)
    _ensure_import_paths(paths)

    if allow_jit_build is None:
        allow_jit_build = mode == "dev"
    os.environ["MINIVLLM_ALLOW_JIT_BUILD"] = "1" if allow_jit_build else "0"

    return BootstrapResult(
        paths=paths,
        mode=mode,
        allow_jit_build=allow_jit_build,
    )


def _resolve_paths(runtime_root: str | os.PathLike[str] | None) -> RuntimePaths:
    repo_root = Path(__file__).resolve().parents[1]
    root = Path(runtime_root).expanduser().resolve() if runtime_root else repo_root / "Runtime"
    cache_root = root / "cache"
    return RuntimePaths(
        runtime_root=root,
        repo_root=repo_root,
        upstream_root=repo_root / "minivllm",
        cache_root=cache_root,
        triton_cache=cache_root / "triton",
        cuda_cache=cache_root / "cuda",
        torch_extensions_cache=cache_root / "torch_extensions",
        hf_cache=cache_root / "hf",
        logs_root=root / "logs",
        models_root=root / "models",
    )


def _ensure_directories(paths: RuntimePaths) -> None:
    for directory in (
        paths.runtime_root,
        paths.cache_root,
        paths.triton_cache,
        paths.cuda_cache,
        paths.torch_extensions_cache,
        paths.hf_cache,
        paths.logs_root,
        paths.models_root,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _configure_environment(paths: RuntimePaths) -> None:
    env = os.environ
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env["TRITON_CACHE_DIR"] = str(paths.triton_cache)
    env["CUDA_CACHE_PATH"] = str(paths.cuda_cache)
    env["TORCH_EXTENSIONS_DIR"] = str(paths.torch_extensions_cache)
    env["HF_HOME"] = str(paths.hf_cache)
    env["TRANSFORMERS_CACHE"] = str(paths.hf_cache)


def _ensure_import_paths(paths: RuntimePaths) -> None:
    upstream = str(paths.upstream_root)
    repo = str(paths.repo_root)
    if repo not in sys.path:
        sys.path.insert(0, repo)
    if upstream not in sys.path:
        sys.path.insert(0, upstream)
