"""Triton-windows warmup and verification on RTX 5070 (sm120).

Covers:
1. Basic kernel compilation and execution
2. Matrix multiplication (core ML primitive)
3. Vectorized element-wise ops (activation-like pattern)
4. Flash-attention-style reduction (softmax pattern)
5. Triton autotuning round-trip

Each test reports compile time, run time, and correctness.
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

import torch
import triton
import triton.language as tl


# ---------------------------------------------------------------------------
# Test 1: Basic vector add — simplest compilation/runtime smoke test
# ---------------------------------------------------------------------------

@triton.jit
def _vec_add_kernel(x_ptr, y_ptr, out_ptr, N, BLOCK_SIZE: tl.constexpr):
    pid = tl.program_id(0)
    offs = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    mask = offs < N
    x = tl.load(x_ptr + offs, mask=mask, other=0.0)
    y = tl.load(y_ptr + offs, mask=mask, other=0.0)
    tl.store(out_ptr + offs, x + y, mask=mask)


def test_vec_add(device: str = "cuda") -> dict:
    N = 1024 * 1024
    BLOCK_SIZE = 1024
    x = torch.randn(N, device=device, dtype=torch.float32)
    y = torch.randn(N, device=device, dtype=torch.float32)
    out = torch.empty_like(x)

    t0 = time.perf_counter()
    grid = (triton.cdiv(N, BLOCK_SIZE),)
    _vec_add_kernel[grid](x, y, out, N, BLOCK_SIZE=BLOCK_SIZE)
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    expected = x + y
    correct = torch.allclose(out, expected, atol=1e-5)
    return {
        "test": "vec_add",
        "elapsed_ms": round(elapsed_ms, 3),
        "correct": correct,
        "elements": N,
    }


# ---------------------------------------------------------------------------
# Test 2: Matrix multiply — core deep learning primitive
# ---------------------------------------------------------------------------

@triton.jit
def _matmul_kernel(
    A, B, Out,
    M, N, K,
    stride_am, stride_ak,
    stride_bk, stride_bn,
    stride_om, stride_on,
    BLOCK_M: tl.constexpr, BLOCK_N: tl.constexpr, BLOCK_K: tl.constexpr,
):
    pid_m = tl.program_id(0)
    pid_n = tl.program_id(1)

    offs_m = pid_m * BLOCK_M + tl.arange(0, BLOCK_M)
    offs_n = pid_n * BLOCK_N + tl.arange(0, BLOCK_N)
    offs_k = tl.arange(0, BLOCK_K)

    a_ptrs = A + offs_m[:, None] * stride_am + offs_k[None, :] * stride_ak
    b_ptrs = B + offs_k[:, None] * stride_bk + offs_n[None, :] * stride_bn

    acc = tl.zeros((BLOCK_M, BLOCK_N), dtype=tl.float32)
    for k in range(0, K, BLOCK_K):
        mask_a = (offs_m[:, None] < M) & (offs_k[None, :] < K - k)
        mask_b = (offs_k[:, None] < K - k) & (offs_n[None, :] < N)
        a = tl.load(a_ptrs, mask=mask_a, other=0.0)
        b = tl.load(b_ptrs, mask=mask_b, other=0.0)
        acc += tl.dot(a, b)
        a_ptrs += BLOCK_K * stride_ak
        b_ptrs += BLOCK_K * stride_bk

    mask_o = (offs_m[:, None] < M) & (offs_n[None, :] < N)
    tl.store(Out + offs_m[:, None] * stride_om + offs_n[None, :] * stride_on,
             acc, mask=mask_o)


def test_matmul(device: str = "cuda") -> dict:
    M, N, K = 256, 256, 256
    BLOCK_M, BLOCK_N, BLOCK_K = 16, 16, 32

    A = torch.randn(M, K, device=device, dtype=torch.float32)
    B = torch.randn(K, N, device=device, dtype=torch.float32)
    Out = torch.empty(M, N, device=device, dtype=torch.float32)

    t0 = time.perf_counter()
    grid = (triton.cdiv(M, BLOCK_M), triton.cdiv(N, BLOCK_N))
    _matmul_kernel[grid](
        A, B, Out,
        M, N, K,
        A.stride(0), A.stride(1),
        B.stride(0), B.stride(1),
        Out.stride(0), Out.stride(1),
        BLOCK_M=BLOCK_M, BLOCK_N=BLOCK_N, BLOCK_K=BLOCK_K,
    )
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    expected = torch.mm(A, B)
    max_diff = (Out - expected).abs().max().item()
    correct = max_diff < 0.01
    return {
        "test": "matmul",
        "elapsed_ms": round(elapsed_ms, 3),
        "correct": correct,
        "max_diff": f"{max_diff:.6f}",
        "shape": f"{M}x{N}x{K}",
    }


# ---------------------------------------------------------------------------
# Test 3: SiLU activation (matching the pattern in layers/activation.py)
# ---------------------------------------------------------------------------

@triton.jit
def _silu_kernel(X_ptr, Y_ptr, N, BLOCK_SIZE: tl.constexpr):
    pid = tl.program_id(0)
    offs = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    mask = offs < N
    x = tl.load(X_ptr + offs, mask=mask, other=0.0)
    # Cast to float32 for exp, then back; sigmoid(x) = 1 / (1 + exp(-x))
    x_f32 = x.to(tl.float32)
    y_f32 = x_f32 / (1.0 + tl.exp(-x_f32))
    tl.store(Y_ptr + offs, y_f32, mask=mask)


def test_silu(device: str = "cuda") -> dict:
    N = 2 * 1024 * 1024
    BLOCK_SIZE = 1024
    x = torch.randn(N, device=device, dtype=torch.float16)
    y = torch.empty(N, device=device, dtype=torch.float32)

    t0 = time.perf_counter()
    grid = (triton.cdiv(N, BLOCK_SIZE),)
    _silu_kernel[grid](x, y, N, BLOCK_SIZE=BLOCK_SIZE)
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    expected = x.float() * torch.sigmoid(x.float())
    correct = torch.allclose(y, expected, atol=0.01)
    return {
        "test": "silu",
        "elapsed_ms": round(elapsed_ms, 3),
        "correct": correct,
        "elements": N,
    }


# ---------------------------------------------------------------------------
# Test 4: Softmax (attention-style reduction pattern)
# ---------------------------------------------------------------------------

@triton.jit
def _softmax_kernel(
    X_ptr, Y_ptr,
    N_ROWS, N_COLS,
    stride_xm, stride_ym,
    BLOCK_COLS: tl.constexpr,
):
    row = tl.program_id(0)
    offs = tl.arange(0, BLOCK_COLS)
    mask = offs < N_COLS

    x_row = tl.load(X_ptr + row * stride_xm + offs, mask=mask, other=0.0)
    x_row = x_row.to(tl.float32)
    x_max = tl.max(x_row, axis=0)
    safe_x = x_row - x_max
    exp_x = tl.exp(safe_x)
    exp_sum = tl.sum(exp_x, axis=0)
    y_row = exp_x / exp_sum

    tl.store(Y_ptr + row * stride_ym + offs, y_row, mask=mask)


def test_softmax(device: str = "cuda") -> dict:
    N_ROWS, N_COLS = 128, 2048
    BLOCK_COLS = 256
    x = torch.randn(N_ROWS, N_COLS, device=device, dtype=torch.float32)
    y = torch.empty_like(x)

    t0 = time.perf_counter()
    grid = (N_ROWS,)
    _softmax_kernel[grid](
        x, y,
        N_ROWS, N_COLS,
        x.stride(0), y.stride(0),
        BLOCK_COLS=BLOCK_COLS,
    )
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    expected_x = x - x.max(dim=-1, keepdim=True).values
    expected = torch.exp(expected_x) / torch.exp(expected_x).sum(dim=-1, keepdim=True)
    max_diff = (y - expected).abs().max().item()
    correct = max_diff < 0.05
    return {
        "test": "softmax",
        "elapsed_ms": round(elapsed_ms, 3),
        "correct": correct,
        "max_diff": f"{max_diff:.6f}",
        "shape": f"{N_ROWS}x{N_COLS}",
    }


# ---------------------------------------------------------------------------
# Test 5: Autotuning round-trip
# ---------------------------------------------------------------------------

@triton.autotune(
    configs=[
        triton.Config({"BLOCK_SIZE": 128}, num_warps=4),
        triton.Config({"BLOCK_SIZE": 256}, num_warps=8),
        triton.Config({"BLOCK_SIZE": 512}, num_warps=8),
        triton.Config({"BLOCK_SIZE": 1024}, num_warps=16),
        triton.Config({"BLOCK_SIZE": 2048}, num_warps=32),
    ],
    key=["N"],
)
@triton.jit
def _autotune_relu_kernel(X_ptr, Y_ptr, N, BLOCK_SIZE: tl.constexpr):
    pid = tl.program_id(0)
    offs = pid * BLOCK_SIZE + tl.arange(0, BLOCK_SIZE)
    mask = offs < N
    x = tl.load(X_ptr + offs, mask=mask, other=0.0)
    tl.store(Y_ptr + offs, tl.maximum(x, 0.0), mask=mask)


def test_autotune(device: str = "cuda") -> dict:
    N = 4 * 1024 * 1024
    x = torch.randn(N, device=device, dtype=torch.float32)
    y = torch.empty_like(x)

    t0 = time.perf_counter()
    _autotune_relu_kernel[(triton.cdiv(N, 1024),)](x, y, N)
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    expected = torch.relu(x)
    correct = torch.allclose(y, expected, atol=1e-5)
    return {
        "test": "autotune_relu",
        "elapsed_ms": round(elapsed_ms, 3),
        "correct": correct,
        "elements": N,
    }


# ---------------------------------------------------------------------------
# Test 6: BF16 kernel — matching the dtype used in minivllm models
# ---------------------------------------------------------------------------

@triton.jit
def _bf16_gemm_like_kernel(
    A, B, Out,
    M, N,
    stride_am, stride_an,
    stride_bm, stride_bn,
    stride_om, stride_on,
    BLOCK_M: tl.constexpr, BLOCK_N: tl.constexpr,
):
    pid_m = tl.program_id(0)
    pid_n = tl.program_id(1)
    offs_m = pid_m * BLOCK_M + tl.arange(0, BLOCK_M)
    offs_n = pid_n * BLOCK_N + tl.arange(0, BLOCK_N)
    mask_m = offs_m[:, None] < M
    mask_n = offs_n[None, :] < N

    a = tl.load(A + offs_m[:, None] * stride_am + offs_n[None, :] * stride_an,
                mask=mask_m & mask_n, other=0.0)
    b = tl.load(B + offs_m[:, None] * stride_bm + offs_n[None, :] * stride_bn,
                mask=mask_m & mask_n, other=0.0)
    out = a + b
    tl.store(Out + offs_m[:, None] * stride_om + offs_n[None, :] * stride_on,
             out, mask=mask_m & mask_n)


def test_bf16_kernel(device: str = "cuda") -> dict:
    M, N = 1024, 1024
    BLOCK_M, BLOCK_N = 16, 32
    a = torch.randn(M, N, device=device, dtype=torch.bfloat16)
    b = torch.randn(M, N, device=device, dtype=torch.bfloat16)
    out = torch.empty(M, N, device=device, dtype=torch.bfloat16)

    t0 = time.perf_counter()
    grid = (triton.cdiv(M, BLOCK_M), triton.cdiv(N, BLOCK_N))
    _bf16_gemm_like_kernel[grid](
        a, b, out,
        M, N,
        a.stride(0), a.stride(1),
        b.stride(0), b.stride(1),
        out.stride(0), out.stride(1),
        BLOCK_M=BLOCK_M, BLOCK_N=BLOCK_N,
    )
    torch.cuda.synchronize()
    elapsed_ms = (time.perf_counter() - t0) * 1000

    expected = (a.float() + b.float()).bfloat16()
    correct = torch.allclose(out.float(), expected.float(), atol=0.1)
    return {
        "test": "bf16_kernel",
        "elapsed_ms": round(elapsed_ms, 3),
        "correct": correct,
        "shape": f"{M}x{N}",
    }


# ---------------------------------------------------------------------------
# Main warmup runner
# ---------------------------------------------------------------------------

def main() -> None:
    if not torch.cuda.is_available():
        print("FATAL: CUDA is not available — cannot run triton warmup")
        sys.exit(1)

    device_name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    arch = f"sm{cap[0] * 10 + cap[1]}"
    mem_gb = torch.cuda.get_device_properties(0).total_memory / 1e9

    print("=" * 64)
    print("Triton-Windows Warmup — RTX 5070 Verification")
    print("=" * 64)
    print(f"  GPU:          {device_name}")
    print(f"  Architecture: {arch}")
    print(f"  Memory:       {mem_gb:.1f} GB")
    print(f"  Triton:       {triton.__version__}")
    print(f"  PyTorch:      {torch.__version__}")
    print(f"  CUDA:         {torch.version.cuda}")
    try:
        cache_dir = triton._C.libtriton.get_cache_dir()
    except AttributeError:
        import os
        cache_dir = os.environ.get("TRITON_CACHE_DIR", "default")
    print(f"  Triton cache: {cache_dir}")
    print("=" * 64)

    tests = [
        ("vec_add (f32)", test_vec_add),
        ("matmul (f16)", test_matmul),
        ("SiLU activation", test_silu),
        ("softmax (attention)", test_softmax),
        ("autotune round-trip", test_autotune),
        ("bf16 kernel", test_bf16_kernel),
    ]

    results = []
    all_pass = True
    total_ms = 0.0

    for name, fn in tests:
        print(f"\n[{name}] ", end="", flush=True)
        try:
            t0 = time.perf_counter()
            result = fn()
            compile_ms = (time.perf_counter() - t0) * 1000
            result["compile_and_run_ms"] = round(compile_ms, 3)
            results.append(result)

            status = "PASS" if result["correct"] else "FAIL"
            all_pass = all_pass and result["correct"]
            total_ms += result["elapsed_ms"]
            print(f"{status}  kernel: {result['elapsed_ms']}ms  total: {result['compile_and_run_ms']}ms")
        except Exception as exc:
            print(f"ERROR: {exc}")
            results.append({"test": name, "error": str(exc)})
            all_pass = False

    print("\n" + "=" * 64)
    print("SUMMARY")
    print("=" * 64)
    for r in results:
        if "error" in r:
            print(f"  {r['test']}: ERROR — {r['error']}")
        else:
            status = "PASS" if r["correct"] else "FAIL"
            diff = f"  max_diff={r['max_diff']}" if not r["correct"] and "max_diff" in r else ""
            print(f"  {r['test']}: {status}  ({r['elapsed_ms']}ms){diff}")

    print(f"\n  Triton warmup {'PASSED' if all_pass else 'FAILED — see errors above'}")

    if not all_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
