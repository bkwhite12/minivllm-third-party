"""Load prebuilt Windows megakernel extensions without triggering JIT."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _runtime_pack_id() -> str:
    override = os.environ.get("MINIVLLM_KERNEL_PACK_ID")
    if override:
        return override

    try:
        import torch

        if torch.cuda.is_available():
            major, minor = torch.cuda.get_device_capability(0)
            return f"cp312-cu128-sm{major}{minor}"
    except Exception:
        pass

    return "cp312-cu128-sm120"


def _available_pack_ids() -> list[str]:
    root = Path(__file__).resolve().parent
    prebuilt_root = root / "prebuilt"
    if not prebuilt_root.exists():
        return []
    return sorted(
        path.name
        for path in prebuilt_root.iterdir()
        if path.is_dir() and path.name.startswith("cp312-cu128-sm")
    )


def load_prebuilt(variant: str = "default", pack_id: str | None = None):
    root = Path(__file__).resolve().parent
    resolved_pack_id = pack_id or _runtime_pack_id()
    artifact = (
        root
        / "prebuilt"
        / resolved_pack_id
        / f"mini_vllm_mk_{variant}.cp312-win_amd64.pyd"
    )
    if not artifact.exists():
        available = ", ".join(_available_pack_ids()) or "none"
        raise FileNotFoundError(
            f"Prebuilt megakernel not found: {artifact} "
            f"(pack_id={resolved_pack_id!r}, available_packs=[{available}])"
        )

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
    module.__minivllm_pack_id__ = resolved_pack_id
    module.__minivllm_artifact__ = str(artifact)
    return module


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="default")
    parser.add_argument("--pack-id", default=None)
    args = parser.parse_args()

    module = load_prebuilt(args.variant, pack_id=args.pack_id)
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
    print(f"variant={args.variant}")
    print(f"pack_id={args.pack_id or _runtime_pack_id()}")
    print("exports=PASS")


if __name__ == "__main__":
    main()
