"""Length-prefixed Protobuf framing helpers for the local Named Pipe protocol.

This module deliberately stays transport-agnostic: it only knows how to encode and
parse protocol frames. The Named Pipe server/client can sit above it without
learning anything about Protobuf internals.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO, Protocol, TypeVar

from google.protobuf.message import DecodeError, Message


_FRAME_HEADER = struct.Struct("<I")  # uint32 little-endian payload length
_MAX_FRAME_SIZE = 16 * 1024 * 1024   # 16 MiB safety ceiling for local IPC frames


class ProtocolMessage(Protocol):
    def SerializeToString(self) -> bytes: ...

    def ParseFromString(self, data: bytes) -> int: ...


TMessage = TypeVar("TMessage", bound=ProtocolMessage)


class ProtocolCodecError(Exception):
    """Base class for framing / decode failures."""


class FrameTooLargeError(ProtocolCodecError):
    """Raised when a frame exceeds the configured safety ceiling."""


class UnexpectedEofError(ProtocolCodecError):
    """Raised when a stream closes before a complete frame is read."""


class InvalidProtobufFrameError(ProtocolCodecError):
    """Raised when bytes do not decode into the expected protobuf message."""


@dataclass(frozen=True)
class Frame:
    """A decoded wire frame before transport-specific handling."""

    payload: bytes

    @property
    def size(self) -> int:
        return len(self.payload)


def encode_message(message: ProtocolMessage) -> bytes:
    """Serialize a protobuf message into a length-prefixed wire frame."""
    payload = message.SerializeToString()
    payload_size = len(payload)
    _validate_frame_size(payload_size)
    return _FRAME_HEADER.pack(payload_size) + payload


def decode_message(frame_payload: bytes, message: TMessage) -> TMessage:
    """Parse a protobuf payload into the supplied message instance."""
    _validate_frame_size(len(frame_payload))
    try:
        message.ParseFromString(frame_payload)
    except DecodeError as exc:
        raise InvalidProtobufFrameError("failed to decode protobuf payload") from exc
    return message


def write_message(stream: BinaryIO, message: ProtocolMessage) -> None:
    """Write one complete length-prefixed protobuf frame to a binary stream."""
    stream.write(encode_message(message))
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def read_frame(stream: BinaryIO) -> Frame:
    """Read exactly one length-prefixed payload from a binary stream."""
    header = _read_exact(stream, _FRAME_HEADER.size)
    (payload_size,) = _FRAME_HEADER.unpack(header)
    _validate_frame_size(payload_size)
    payload = _read_exact(stream, payload_size)
    return Frame(payload=payload)


def read_message(stream: BinaryIO, message: TMessage) -> TMessage:
    """Read and decode one protobuf message from a binary stream."""
    frame = read_frame(stream)
    return decode_message(frame.payload, message)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size

    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise UnexpectedEofError(
                f"stream closed with {remaining} byte(s) still expected"
            )
        chunks.append(chunk)
        remaining -= len(chunk)

    return b"".join(chunks)


def _validate_frame_size(size: int) -> None:
    if size < 0:
        raise ProtocolCodecError("frame size cannot be negative")
    if size > _MAX_FRAME_SIZE:
        raise FrameTooLargeError(
            f"frame size {size} exceeds limit {_MAX_FRAME_SIZE}"
        )
