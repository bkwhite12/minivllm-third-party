"""Exercise GENERATE on one pipe connection and CANCEL on another."""

from __future__ import annotations

import threading
import time

from Protocol.python_generated import minivllm_runtime_pb2 as pb

from .protocol_codec import read_message, write_message
from .test_client import cancel_envelope, connect, generate_envelope


def main() -> None:
    generate = generate_envelope("Tell me a long story about a city at night.")
    generate.generate.max_new_tokens = 128

    stream = connect()
    replies: list[pb.Envelope] = []

    def cancel_later() -> None:
        # Give the decode loop a brief head start, then cancel the active request.
        time.sleep(0.05)
        cancel_stream = connect()
        try:
            write_message(cancel_stream, cancel_envelope(generate.request_id))
            reply = read_message(cancel_stream, pb.Envelope())
            print(reply)
        finally:
            cancel_stream.close()

    thread = threading.Thread(target=cancel_later, daemon=True)
    thread.start()

    try:
        write_message(stream, generate)
        while True:
            reply = read_message(stream, pb.Envelope())
            replies.append(reply)
            print(reply)
            if reply.type in (pb.DONE, pb.ERROR):
                break
    finally:
        stream.close()
        thread.join(timeout=1.0)


if __name__ == "__main__":
    main()
