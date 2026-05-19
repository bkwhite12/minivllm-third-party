# DialogueReliabilityRunner

**Date**: 2026-05-20  
**File**: `MiniVLLMWorker/dialogue_reliability_runner.py`

## Purpose

Automates a small multi-turn reliability suite over the existing Windows Named Pipe + Protobuf protocol.

It validates:

- multi-turn prompt history construction
- role-marker truncation before history reuse
- cleaned assistant history to prevent self-dialogue contamination
- role leakage statistics per round
- streaming `TOKEN` collection
- terminal `DONE`
- cancellation in the middle of a generation
- metrics after every round
- JSONL logging for later analysis

## How to run

Start the worker first:

```powershell
F:\CTest\start_minivllm_worker.cmd
```

Then run:

```powershell
cd F:\CTest
C:\Users\BK白修\AppData\Local\Programs\Python\Python312\python.exe -m MiniVLLMWorker.dialogue_reliability_runner
```

Default output:

```text
F:\CTest\Runtime\logs\dialogue_reliability\latest.jsonl
F:\CTest\Runtime\logs\dialogue_reliability\latest.txt
```

The `.jsonl` file is for machine analysis.  
The `.txt` file is a human-readable dialogue transcript.

## Output fields added on 2026-05-20

Each JSONL record now includes:

```text
raw_streamed_text
cleaned_text
role_leakage.detected
role_leakage.marker
role_leakage.offset
role_leakage.removed_suffix_chars
role_leakage_count_so_far
history_turns_after_cleaning
```

`cleaned_text` is the text used for keyword checks and future prompt history.
`raw_streamed_text` is preserved so we can still inspect the exact model output.

The transcript also prints `role_leakage: YES/NO` for each round.

## Current test rounds

1. establish player identity: `林川 / 铁匠`
2. ask the model to recall that identity
3. ask for a short gameplay suggestion
4. request a longer story and cancel after several tokens
5. continue after cancellation

## Notes

The runner intentionally uses plain prompt-history formatting and sets:

```text
use_chat_template = false
use_thinking = false
sampling = greedy
```

This keeps the first reliability pass deterministic and focused on transport/runtime behavior rather than prompt-template behavior.

The system prompt was tightened to tell the model to output only the current assistant reply.
Even so, the runner does not trust the model blindly: if it emits `User:`, `Assistant:`, `System:`,
Chinese role labels, or common chat-template markers, the text is cut before that marker and only the
safe prefix is written into history.

## Next extensions

- load test cases from YAML/JSON
- add pass/fail summary aggregation
- add Unicode edge cases
- add long 30-round and 100-request stress modes

