"""Batch reliability runner for multi-turn dialogue over the Named Pipe protocol."""

from __future__ import annotations

import argparse
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from Protocol.python_generated import minivllm_runtime_pb2 as pb

from .protocol_codec import read_message, write_message
from .test_client import (
    _base_request,
    cancel_envelope,
    connect,
    metrics_envelope,
)


DEFAULT_SYSTEM_PROMPT = (
    "你是游戏中的 NPC，请保持角色一致，回答简洁自然。"
    "只输出 Assistant 当前回复，不要输出 User:/Assistant:/System:，也不要续写下一轮对话。"
)

EXPLICIT_MEMORY_RULES = (
    "优先遵守【显式记忆】与【当前目标】。"
    "如果历史回复和显式记忆冲突，以显式记忆为准。"
    "回答必须直接服务当前玩家输入，不要复读旧建议。"
)

ROLE_MARKER_RE = re.compile(
    r"(?im)(^|\n)\s*("
    r"system|user|assistant|human|ai|"
    r"系统|用户|玩家|助手|助理|旁白"
    r")\s*[:：]"
)

LEADING_ASSISTANT_RE = re.compile(
    r"(?im)^\s*(assistant|助手|助理)\s*[:：]\s*"
)

CHAT_TEMPLATE_MARKER_RE = re.compile(
    r"(?i)<\|im_(?:start|end)\|>|<\|(?:system|user|assistant)\|>"
)


@dataclass(slots=True)
class RoundSpec:
    user: str
    expect_keywords: tuple[str, ...] = ()
    cancel_after_tokens: int | None = None


def _collapse_blank_lines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sanitize_assistant_text(raw_text: str) -> tuple[str, dict]:
    """Cut role leakage and return text safe to feed back into dialogue history."""
    original = raw_text or ""
    text = original
    leakage = {
        "detected": False,
        "marker": "",
        "offset": -1,
        "removed_suffix_chars": 0,
        "leading_assistant_marker_removed": False,
    }

    leading = LEADING_ASSISTANT_RE.match(text)
    if leading:
        leakage["detected"] = True
        leakage["marker"] = leading.group(1)
        leakage["offset"] = 0
        leakage["leading_assistant_marker_removed"] = True
        text = text[leading.end() :]

    chat_marker = CHAT_TEMPLATE_MARKER_RE.search(text)
    role_marker = ROLE_MARKER_RE.search(text)
    candidates = [m for m in (chat_marker, role_marker) if m is not None]
    if candidates:
        first = min(candidates, key=lambda m: m.start())
        cut_at = first.start()
        leakage["detected"] = True
        if not leakage["marker"]:
            leakage["marker"] = first.group(0).strip()
            leakage["offset"] = cut_at
        leakage["removed_suffix_chars"] = len(text) - cut_at
        text = text[:cut_at]

    cleaned = _collapse_blank_lines(text)
    return cleaned, leakage


def sanitize_history(history: list[tuple[str, str]], *, max_turns: int = 8) -> list[tuple[str, str]]:
    """Keep prompt history compact and free from assistant-side self-dialogue."""
    cleaned: list[tuple[str, str]] = []
    for user, assistant in history[-max_turns:]:
        safe_user = _collapse_blank_lines(user)
        safe_assistant, _ = sanitize_assistant_text(assistant)
        if safe_user and safe_assistant:
            cleaned.append((safe_user, safe_assistant))
    return cleaned


def explicit_memory_for_round(round_index: int) -> str:
    """Scenario-owned memory used to test whether explicit context improves reliability."""
    base = [
        "玩家姓名：林川。",
        "玩家身份：来自北境的铁匠。",
        "NPC风格：简洁、自然、像游戏内同伴，不要自称玩家。",
    ]
    if round_index >= 3:
        base.append("当前任务：玩家准备前往城堡。")
    if round_index >= 4:
        base.append("最近事件：玩家要求讲一个稍长的夜城故事，并会中途打断。")
    if round_index >= 5:
        base.extend(
            [
                "上一轮未完成事件：夜城故事刚开头就被玩家打断。",
                "当前目标：用一句话继续夜城故事。",
                "禁止事项：不要回到“去城堡前检查装备/工具”的建议。",
            ]
        )
    return "\n".join(f"- {item}" for item in base)


def build_prompt(
    history: list[tuple[str, str]],
    user_text: str,
    *,
    round_index: int = 0,
    explicit_memory: bool = False,
) -> str:
    system_prompt = DEFAULT_SYSTEM_PROMPT
    if explicit_memory:
        system_prompt += EXPLICIT_MEMORY_RULES
    lines = [f"System: {system_prompt}"]
    if explicit_memory:
        lines.append(f"System: 【显式记忆】\n{explicit_memory_for_round(round_index)}")
    for user, assistant in sanitize_history(history):
        lines.append(f"User: {user}")
        lines.append(f"Assistant: {assistant}")
    lines.append(f"User: {_collapse_blank_lines(user_text)}")
    lines.append("Assistant:")
    return "\n".join(lines)


def generate_envelope(
    prompt: str,
    *,
    max_new_tokens: int,
    session_id: str,
    use_chat_template: bool,
) -> pb.Envelope:
    env = _base_request(pb.GENERATE)
    env.session_id = session_id
    env.generate.model_alias = "qwen3-0.6b"
    env.generate.prompt = prompt
    env.generate.max_new_tokens = max_new_tokens
    env.generate.stream = True
    env.generate.sampling.method = pb.GREEDY
    env.generate.sampling.temperature = 1.0
    env.generate.sampling.top_k = 1
    env.generate.sampling.top_p = 1.0
    env.generate.stop_on_eos = True
    env.generate.use_chat_template = use_chat_template
    env.generate.use_thinking = False
    return env


def run_generate(
    prompt: str,
    *,
    max_new_tokens: int,
    session_id: str,
    use_chat_template: bool,
    cancel_after_tokens: int | None = None,
) -> dict:
    env = generate_envelope(
        prompt,
        max_new_tokens=max_new_tokens,
        session_id=session_id,
        use_chat_template=use_chat_template,
    )
    stream = connect()
    started = time.perf_counter()
    token_chunks: list[str] = []
    token_ids: list[int] = []
    cancel_reply: dict | None = None

    def cancel_now() -> None:
        nonlocal cancel_reply
        cstream = connect()
        try:
            cancel = cancel_envelope(env.request_id)
            cancel.session_id = session_id
            write_message(cstream, cancel)
            reply = read_message(cstream, pb.Envelope())
            cancel_reply = {
                "accepted": bool(reply.cancel_reply.accepted),
                "target_request_id": reply.cancel_reply.target_request_id,
            }
        finally:
            cstream.close()

    try:
        write_message(stream, env)
        cancel_started = False
        while True:
            reply = read_message(stream, pb.Envelope())
            if reply.type == pb.TOKEN:
                token_chunks.append(reply.token.text)
                token_ids.append(reply.token.token_id)
                if (
                    cancel_after_tokens is not None
                    and not cancel_started
                    and len(token_chunks) >= cancel_after_tokens
                ):
                    cancel_started = True
                    threading.Thread(target=cancel_now, daemon=True).start()
            elif reply.type == pb.DONE:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "request_id": env.request_id,
                    "streamed_text": "".join(token_chunks),
                    "token_count": len(token_chunks),
                    "token_ids": token_ids,
                    "done_text": reply.done.text,
                    "finish_reason": pb.FinishReason.Name(reply.done.finish_reason),
                    "prompt_tokens": reply.done.metrics.prompt_tokens,
                    "generated_tokens": reply.done.metrics.generated_tokens,
                    "ttft_ms": reply.done.metrics.ttft_ms,
                    "total_latency_ms": reply.done.metrics.total_latency_ms,
                    "client_elapsed_ms": elapsed_ms,
                    "tokens_per_sec": reply.done.metrics.tokens_per_sec,
                    "cancel_reply": cancel_reply,
                    "error": "",
                }
            elif reply.type == pb.ERROR:
                return {
                    "request_id": env.request_id,
                    "streamed_text": "".join(token_chunks),
                    "token_count": len(token_chunks),
                    "finish_reason": "ERROR",
                    "error": reply.error.message,
                }
    finally:
        stream.close()


def run_once(request: pb.Envelope) -> pb.Envelope:
    stream = connect()
    try:
        write_message(stream, request)
        return read_message(stream, pb.Envelope())
    finally:
        stream.close()


def fetch_metrics() -> dict:
    reply = run_once(metrics_envelope())
    rt = reply.metrics.runtime
    return {
        "process_uptime_ms": rt.process_uptime_ms,
        "total_requests": rt.total_requests,
        "completed_requests": rt.completed_requests,
        "failed_requests": rt.failed_requests,
        "active_requests": rt.active_requests,
        "cancelled_requests": rt.cancelled_requests,
        "eos_completions": rt.eos_completions,
        "max_token_completions": rt.max_token_completions,
        "allocated_vram_bytes": rt.allocated_vram_bytes,
        "reserved_vram_bytes": rt.reserved_vram_bytes,
    }


def default_rounds() -> list[RoundSpec]:
    return [
        RoundSpec("我叫林川，是一名来自北境的铁匠。", ("林川", "铁匠")),
        RoundSpec("我叫什么？我是做什么的？", ("林川", "铁匠")),
        RoundSpec("请给我一个去城堡前的简短建议。"),
        RoundSpec("现在请讲一个稍长的夜城故事，我会中途打断。", cancel_after_tokens=4),
        RoundSpec("刚才被打断后，请用一句话继续和我说话。"),
    ]


def run_suite(
    *,
    rounds: Iterable[RoundSpec],
    max_new_tokens: int,
    output_path: Path,
    transcript_path: Path | None = None,
    use_chat_template: bool = True,
    explicit_memory: bool = False,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if transcript_path is None:
        transcript_path = output_path.with_suffix(".txt")
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    session_id = f"dialogue-reliability-{int(time.time())}"
    history: list[tuple[str, str]] = []
    role_leakage_count = 0

    with output_path.open("w", encoding="utf-8") as f, transcript_path.open(
        "w", encoding="utf-8"
    ) as transcript:
        transcript.write("MiniVLLM 多轮对话可靠性记录\n")
        transcript.write(f"session_id: {session_id}\n")
        transcript.write(f"max_new_tokens: {max_new_tokens}\n")
        transcript.write(f"use_chat_template: {use_chat_template}\n")
        transcript.write(f"explicit_memory: {explicit_memory}\n")
        transcript.write("=" * 80 + "\n\n")

        for index, spec in enumerate(rounds, start=1):
            prompt = build_prompt(
                history,
                spec.user,
                round_index=index,
                explicit_memory=explicit_memory,
            )
            result = run_generate(
                prompt,
                max_new_tokens=max_new_tokens,
                session_id=session_id,
                use_chat_template=use_chat_template,
                cancel_after_tokens=spec.cancel_after_tokens,
            )
            raw_assistant_text = result.get("streamed_text", "")
            assistant_text, role_leakage = sanitize_assistant_text(raw_assistant_text)
            if role_leakage["detected"]:
                role_leakage_count += 1
            if result.get("finish_reason") != "CANCELLED":
                history.append((spec.user, assistant_text))

            keyword_hits = {
                keyword: keyword in assistant_text for keyword in spec.expect_keywords
            }
            record = {
                "session_id": session_id,
                "round": index,
                "user": spec.user,
                "prompt_chars": len(prompt),
                "max_new_tokens": max_new_tokens,
                "use_chat_template": use_chat_template,
                "explicit_memory": explicit_memory,
                "explicit_memory_block": explicit_memory_for_round(index)
                if explicit_memory
                else "",
                "expect_keywords": list(spec.expect_keywords),
                "keyword_hits": keyword_hits,
                "raw_streamed_text": raw_assistant_text,
                "cleaned_text": assistant_text,
                "role_leakage": role_leakage,
                "role_leakage_count_so_far": role_leakage_count,
                "history_turns_after_cleaning": len(sanitize_history(history)),
                **result,
                "metrics_after_round": fetch_metrics(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            transcript.write(f"Round {index}\n")
            transcript.write("-" * 80 + "\n")
            transcript.write(f"User:\n{spec.user}\n\n")
            if explicit_memory:
                transcript.write("Explicit memory:\n")
                transcript.write(explicit_memory_for_round(index) + "\n\n")
            transcript.write("Assistant:\n")
            transcript.write((assistant_text or "").strip() + "\n\n")
            transcript.write("Result:\n")
            transcript.write(f"  finish_reason: {record.get('finish_reason')}\n")
            transcript.write(f"  token_count: {record.get('token_count')}\n")
            transcript.write(f"  prompt_chars: {record.get('prompt_chars')}\n")
            transcript.write(f"  ttft_ms: {record.get('ttft_ms')}\n")
            transcript.write(f"  total_latency_ms: {record.get('total_latency_ms')}\n")
            transcript.write(f"  tokens_per_sec: {record.get('tokens_per_sec')}\n")
            transcript.write(f"  role_leakage: {'YES' if role_leakage['detected'] else 'NO'}\n")
            if role_leakage["detected"]:
                transcript.write(f"    marker: {role_leakage.get('marker')}\n")
                transcript.write(f"    offset: {role_leakage.get('offset')}\n")
                transcript.write(f"    removed_suffix_chars: {role_leakage.get('removed_suffix_chars')}\n")
            if spec.expect_keywords:
                transcript.write("  keyword_hits:\n")
                for keyword, hit in keyword_hits.items():
                    transcript.write(f"    {keyword}: {'PASS' if hit else 'MISS'}\n")
            if record.get("cancel_reply") is not None:
                transcript.write(f"  cancel_reply: {record['cancel_reply']}\n")
            metrics = record.get("metrics_after_round", {})
            transcript.write("  metrics_after_round:\n")
            transcript.write(f"    total_requests: {metrics.get('total_requests')}\n")
            transcript.write(f"    completed_requests: {metrics.get('completed_requests')}\n")
            transcript.write(f"    cancelled_requests: {metrics.get('cancelled_requests')}\n")
            transcript.write(f"    failed_requests: {metrics.get('failed_requests')}\n")
            transcript.write(f"    active_requests: {metrics.get('active_requests')}\n")
            transcript.write("\n" + "=" * 80 + "\n\n")
            transcript.flush()

            print(
                f"[round {index}] finish={record['finish_reason']} "
                f"tokens={record.get('token_count')} "
                f"latency={record.get('total_latency_ms')}ms "
                f"leak={'Y' if role_leakage['detected'] else 'N'} "
                f"text={assistant_text[:80]!r}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument(
        "--output",
        default="F:/CTest/Runtime/logs/dialogue_reliability/latest.jsonl",
    )
    parser.add_argument(
        "--transcript",
        default=None,
        help="Human-readable txt dialogue transcript path. Defaults to output path with .txt suffix.",
    )
    parser.add_argument(
        "--raw-prompt",
        action="store_true",
        help="Disable tokenizer chat_template and use raw prompt tokenization for A/B comparison.",
    )
    parser.add_argument(
        "--explicit-memory",
        action="store_true",
        help="Inject scenario-owned explicit memory/current-goal context into every round.",
    )
    args = parser.parse_args()

    run_suite(
        rounds=default_rounds(),
        max_new_tokens=args.max_new_tokens,
        output_path=Path(args.output),
        transcript_path=Path(args.transcript) if args.transcript else None,
        use_chat_template=not args.raw_prompt,
        explicit_memory=args.explicit_memory,
    )


if __name__ == "__main__":
    main()

