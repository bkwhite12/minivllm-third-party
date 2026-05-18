"""Observe active_requests while a real generation is in flight."""

from __future__ import annotations

import threading
import time

from Protocol.python_generated import minivllm_runtime_pb2 as pb

from .protocol_codec import read_message, write_message
from .test_client import connect, generate_envelope, metrics_envelope


def main() -> None:
    generate = generate_envelope("Tell me a very long story about a city at night.")
    generate.generate.max_new_tokens = 128

    stream = connect()

    def consume_generation() -> None:
        try:
            write_message(stream, generate)
            while True:
                reply = read_message(stream, pb.Envelope())
                if reply.type in (pb.DONE, pb.ERROR):
                    break
        finally:
            stream.close()

    thread = threading.Thread(target=consume_generation, daemon=True)
    thread.start()
    time.sleep(0.02)

    metrics_stream = connect()
    try:
        write_message(metrics_stream, metrics_envelope())
        reply = read_message(metrics_stream, pb.Envelope())
        print(reply)
    finally:
        metrics_stream.close()
    thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
