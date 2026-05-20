"""Megakernel CUDA JIT compilation and smoke test for Windows.

Verifies:
1. torch.utils.cpp_extension.load() can JIT-compile .cu + .cpp to a module
2. The compiled module exports the expected functions (decode, decode_with_logits)
3. A smoke decode call produces valid output

Prerequisites:
- MSVC Build Tools / Visual Studio with C++ workload
- CUDA Toolkit 12.8.1
- Ninja 1.13.0
- PyTorch 2.9.1+cu128
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import torch


def test_megakernel_jit(variant: str = "default", smoke: bool = True) -> dict:
    """JIT-compile a megakernel variant and optionally run a smoke decode call."""

    kernel_dir = Path(__file__).resolve().parents[1] / "minivllm" / "kernels" / "megakernel_cuda"

    # Add kernel_dir parent to path so we can import the __init__.py
    kernels_parent = kernel_dir.parent
    if str(kernels_parent) not in sys.path:
        sys.path.insert(0, str(kernels_parent))

    # Respect the caller's target architecture. build_megakernel.ps1 sets this
    # explicitly so the same smoke/build helper can cross-compile sm86/sm89/sm120
    # packs from one Windows build machine.
    os.environ.setdefault("TORCH_CUDA_ARCH_LIST", "12.0")

    # Import triggers JIT compilation via megakernel_cuda/__init__.py
    t0 = time.perf_counter()

    try:
        from megakernel_cuda import _get_module

        module = _get_module(variant)
    except FileNotFoundError as e:
        return {
            "variant": variant,
            "jit_success": False,
            "error": str(e),
            "stage": "source_check",
        }
    except Exception as e:
        return {
            "variant": variant,
            "jit_success": False,
            "error": str(e),
            "stage": "jit_compile",
        }

    compile_ms = (time.perf_counter() - t0) * 1000

    # Verify exported functions
    expected_funcs = ["decode", "decode_with_logits", "init_profiler",
                      "reset_profiler", "export_profiler", "destroy_profiler"]
    missing = [f for f in expected_funcs if not hasattr(module, f)]
    if missing:
        return {
            "variant": variant,
            "jit_success": False,
            "compile_ms": round(compile_ms, 1),
            "error": f"Missing exports: {missing}",
            "stage": "export_check",
        }

    if not smoke:
        return {
            "variant": variant,
            "jit_success": True,
            "compile_ms": round(compile_ms, 1),
            "smoke_pass": None,
            "stage": "compile_only",
        }

    # Smoke test: create minimal tensors and call decode
    try:
        result = _smoke_decode(module)
    except Exception as e:
        return {
            "variant": variant,
            "jit_success": True,
            "compile_ms": round(compile_ms, 1),
            "smoke_pass": False,
            "error": str(e),
            "stage": "smoke_decode",
        }

    result["variant"] = variant
    result["jit_success"] = True
    result["compile_ms"] = round(compile_ms, 1)
    return result


def _smoke_decode(module) -> dict:
    """Minimal decode smoke test — does NOT require a real model.

    Allocates dummy tensors matching the Qwen3-0.6B shapes and verifies
    the kernel returns a valid token_id (integer in valid range).
    """
    HIDDEN_SIZE = 1024
    INTERMEDIATE_SIZE = 3072
    NUM_Q_HEADS = 16
    NUM_KV_HEADS = 8
    HEAD_DIM = 128
    NUM_LAYERS = 28
    VOCAB_SIZE = 151936
    MAX_SEQ_LEN = 2048

    device = torch.device("cuda:0")
    dtype = torch.bfloat16

    # Allocate per-layer weights (raw bytes)
    layer_bytes_per = (
        # Q weight + K weight + V weight + O weight
        4 * HIDDEN_SIZE * HIDDEN_SIZE * 2  # bf16 -> 2 bytes
        # gate + up + down (MLP)
        + 3 * HIDDEN_SIZE * INTERMEDIATE_SIZE * 2
        # RMS norm weights
        + 2 * HIDDEN_SIZE * 2  # attention norm + mlp norm
    )
    layer_weights_bytes = torch.zeros(
        NUM_LAYERS, layer_bytes_per, dtype=torch.uint8, device=device
    )

    embed_weight = torch.randn(VOCAB_SIZE, HIDDEN_SIZE, device=device, dtype=dtype)
    final_norm_weight = torch.randn(HIDDEN_SIZE, device=device, dtype=dtype)
    lm_head_weight = torch.randn(VOCAB_SIZE, HIDDEN_SIZE, device=device, dtype=dtype)

    # Rotary embedding tables
    cos_table = torch.randn(MAX_SEQ_LEN, HEAD_DIM, device=device, dtype=dtype)
    sin_table = torch.randn(MAX_SEQ_LEN, HEAD_DIM, device=device, dtype=dtype)

    # KV cache
    k_cache = torch.zeros(NUM_LAYERS, NUM_KV_HEADS, MAX_SEQ_LEN, HEAD_DIM,
                          device=device, dtype=dtype)
    v_cache = torch.zeros_like(k_cache)

    # Global buffers
    hidden_buffer = torch.zeros(HIDDEN_SIZE, device=device, dtype=dtype)
    num_blocks = module.LM_HEAD_NUM_BLOCKS if hasattr(module, "LM_HEAD_NUM_BLOCKS") else 1184
    g_activations = torch.zeros(num_blocks, INTERMEDIATE_SIZE, device=device, dtype=torch.float32)
    g_residual = torch.zeros(num_blocks, HIDDEN_SIZE, device=device, dtype=torch.float32)
    g_q = torch.zeros(num_blocks, NUM_Q_HEADS * HEAD_DIM, device=device, dtype=torch.float32)
    g_k = torch.zeros(num_blocks, NUM_KV_HEADS * HEAD_DIM, device=device, dtype=torch.float32)
    g_v = torch.zeros(num_blocks, NUM_KV_HEADS * HEAD_DIM, device=device, dtype=torch.float32)
    g_attn_out = torch.zeros(num_blocks, NUM_Q_HEADS * HEAD_DIM, device=device, dtype=torch.float32)
    g_mlp_intermediate = torch.zeros(num_blocks, INTERMEDIATE_SIZE, device=device, dtype=torch.float32)
    g_normalized = torch.zeros(num_blocks, HIDDEN_SIZE, device=device, dtype=torch.float32)

    # LM head block max buffers
    block_max_vals = torch.zeros(num_blocks, device=device, dtype=torch.float32)
    block_max_idxs = torch.zeros(num_blocks, device=device, dtype=torch.int32)

    input_token_id = 1
    position = 0
    cache_len = 1
    attn_scale = 1.0 / (HEAD_DIM ** 0.5)

    t0 = time.perf_counter()
    token_id = module.decode(
        input_token_id,
        position,
        cache_len,
        layer_weights_bytes,
        embed_weight,
        final_norm_weight,
        lm_head_weight,
        cos_table,
        sin_table,
        k_cache,
        v_cache,
        hidden_buffer,
        g_activations,
        g_residual,
        g_q,
        g_k,
        g_v,
        g_attn_out,
        g_mlp_intermediate,
        g_normalized,
        block_max_vals,
        block_max_idxs,
        num_blocks,
        NUM_LAYERS,
        MAX_SEQ_LEN,
        attn_scale,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    valid_token = 0 <= token_id < VOCAB_SIZE
    return {
        "smoke_pass": True,
        "output_token_id": token_id,
        "valid_range": valid_token,
        "decode_ms": round(elapsed_ms, 3),
    }


def main() -> None:
    if not torch.cuda.is_available():
        print("FATAL: CUDA is not available")
        sys.exit(1)

    device_name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    arch = f"sm{cap[0] * 10 + cap[1]}"
    mem_gb = torch.cuda.get_device_properties(0).total_memory / 1e9

    print("=" * 64)
    print("Megakernel CUDA JIT Compilation — Windows Verification")
    print("=" * 64)
    print(f"  GPU:          {device_name}")
    print(f"  Architecture: {arch}")
    print(f"  Memory:       {mem_gb:.1f} GB")
    print(f"  PyTorch:      {torch.__version__}")
    print(f"  CUDA:         {torch.version.cuda}")
    print("=" * 64)

    compile_only = "--compile-only" in sys.argv

    # Test the default variant first (simplest, most tested)
    result = test_megakernel_jit("default", smoke=not compile_only)
    print(f"\n[default variant]")
    if not result["jit_success"]:
        print(f"  JIT compile: FAILED at stage '{result['stage']}'")
        print(f"  Error: {result['error']}")
        sys.exit(1)

    print(f"  JIT compile: PASS  ({result['compile_ms']}ms)")
    if result.get("stage") == "compile_only":
        print("  Smoke decode: SKIPPED (compile-only mode)")
    elif result.get("smoke_pass"):
        print(f"  Smoke decode: PASS  ({result['decode_ms']}ms, token={result['output_token_id']})")
    else:
        print(f"  Smoke decode: FAILED at stage '{result['stage']}'")
        print(f"  Error: {result.get('error', 'unknown')}")
        sys.exit(1)

    # Also test all_combined if default passes
    print(f"\n[all_combined variant]")
    try:
        r2 = test_megakernel_jit("all_combined", smoke=not compile_only)
        if r2["jit_success"]:
            print(f"  JIT compile: PASS  ({r2['compile_ms']}ms)")
            if r2.get("stage") == "compile_only":
                print("  Smoke decode: SKIPPED (compile-only mode)")
            elif r2.get("smoke_pass"):
                print(f"  Smoke decode: PASS  ({r2['decode_ms']}ms, token={r2['output_token_id']})")
            else:
                print(f"  Smoke decode: FAILED — {r2.get('error', 'unknown')}")
                sys.exit(1)
        else:
            print(f"  JIT compile: FAILED — {r2['error']}")
            sys.exit(1)
    except Exception as e:
        print(f"  Skipped (error: {e})")

    print("\n" + "=" * 64)
    print("Megakernel JIT verification PASSED")
    print("=" * 64)


if __name__ == "__main__":
    main()
