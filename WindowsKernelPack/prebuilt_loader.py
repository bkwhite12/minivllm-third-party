"""Load prebuilt Windows megakernel extensions without triggering JIT."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def load_prebuilt(variant: str = "default"):
    root = Path(__file__).resolve().parent
    artifact = (
        root
        / "prebuilt"
        / "cp312-cu128-sm120"
        / f"mini_vllm_mk_{variant}.cp312-win_amd64.pyd"
    )
    if not artifact.exists():
        raise FileNotFoundError(f"Prebuilt megakernel not found: {artifact}")

    module_name = f"mini_vllm_mk_{variant}"
    # On Windows, extension modules may depend on torch DLLs that are not on the
    # default DLL search path in a standalone process.
    import torch

    torch_lib = Path(torch.__file__).resolve().parent / "lib"
    if torch_lib.exists():
        os.add_dll_directory(str(torch_lib))

    spec = importlib.util.spec_from_file_location(module_name, artifact)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to create import spec for {artifact}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = load_prebuilt("default")
    expected = [
        "decode",
        "decode_with_logits",
        "init_profiler",
        "reset_profiler",
        "export_profiler",
        "destroy_profiler",
    ]
    missing = [name for name in expected if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"Missing exports: {missing}")
    print("prebuilt_load=PASS")
    print(f"module={module.__name__}")
    print("exports=PASS")


if __name__ == "__main__":
    main()
