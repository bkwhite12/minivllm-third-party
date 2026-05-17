"""Raw Windows Named Pipe server for MiniVLLM protobuf envelopes.

This module intentionally exposes the same byte-level contract Unity will use:
[length:uint32 little-endian][protobuf payload].  It does not use
`multiprocessing.connection`, because that layer adds its own framing and would
force the Unity client to mimic Python-private transport behavior.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterable
from typing import Protocol, TypeAlias

from google.protobuf.message import Message

from .protocol_codec import ProtocolCodecError, ProtocolMessage, read_message, write_message

try:  # Imported lazily enough to keep non-Windows static analysis usable.
    import pywintypes
    import win32file
    import win32pipe
except ImportError:  # pragma: no cover - depends on Windows runtime packaging
    pywintypes = None
    win32file = None
    win32pipe = None


logger = logging.getLogger(__name__)

DEFAULT_PIPE_NAME = r"\\.\pipe\minivllm-runtime"
_DEFAULT_BUFFER_SIZE = 64 * 1024


class EnvelopeFactory(Protocol):
    def __call__(self) -> ProtocolMessage: ...


HandlerResult: TypeAlias = ProtocolMessage | Iterable[ProtocolMessage] | None
RequestHandler: TypeAlias = Callable[[ProtocolMessage], HandlerResult]


class PipeServerError(RuntimeError):
    """Base class for server lifecycle failures."""


class _Win32PipeStream:
    """Small binary-stream adapter over a Win32 pipe handle."""

    def __init__(self, handle) -> None:
        self._handle = handle

    def read(self, size: int) -> bytes:
        if size == 0:
            return b""
        hr, data = win32file.ReadFile(self._handle, size)
        if hr not in (0,):
            raise OSError(f"ReadFile failed with code {hr}")
        return data

    def write(self, data: bytes) -> int:
        hr, written = win32file.WriteFile(self._handle, data)
        if hr not in (0,):
            raise OSError(f"WriteFile failed with code {hr}")
        return written

    def flush(self) -> None:
        win32file.FlushFileBuffers(self._handle)

    def close(self) -> None:
        try:
            win32pipe.DisconnectNamedPipe(self._handle)
        finally:
            win32file.CloseHandle(self._handle)


class NamedPipeServer:
    """Threaded raw-byte Windows named-pipe server."""

    def __init__(
        self,
        envelope_factory: EnvelopeFactory,
        request_handler: RequestHandler,
        *,
        pipe_name: str = DEFAULT_PIPE_NAME,
        daemon_threads: bool = True,
    ) -> None:
        if os.name != "nt":
            raise PipeServerError("NamedPipeServer is only supported on Windows")
        if win32pipe is None or win32file is None or pywintypes is None:
            raise PipeServerError(
                "pywin32 is required for raw Windows named-pipe transport"
            )

        self._envelope_factory = envelope_factory
        self._request_handler = request_handler
        self._pipe_name = pipe_name
        self._daemon_threads = daemon_threads

        self._accept_thread: threading.Thread | None = None
        self._client_threads: set[threading.Thread] = set()
        self._client_threads_lock = threading.Lock()
        self._stop_event = threading.Event()

    @property
    def pipe_name(self) -> str:
        return self._pipe_name

    @property
    def is_running(self) -> bool:
        return self._accept_thread is not None and not self._stop_event.is_set()

    def start(self) -> None:
        if self._accept_thread is not None:
            raise PipeServerError("server is already running")
        self._stop_event.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="minivllm-pipe-accept",
            daemon=self._daemon_threads,
        )
        self._accept_thread.start()
        logger.info("Named pipe server listening on %s", self._pipe_name)

    def serve_forever(self) -> None:
        if self._accept_thread is not None:
            raise PipeServerError("server is already running")
        self._stop_event.clear()
        logger.info("Named pipe server listening on %s", self._pipe_name)
        self._accept_loop()

    def stop(self, *, join_timeout: float = 2.0) -> None:
        self._stop_event.set()
        # Wake the blocking ConnectNamedPipe call by making a best-effort client
        # connection to our own pipe. The accept loop will observe stop_event and
        # tear it down immediately.
        self._wake_accept_loop()

        if self._accept_thread is not None:
            self._accept_thread.join(timeout=join_timeout)
            self._accept_thread = None

        with self._client_threads_lock:
            client_threads = list(self._client_threads)
        for thread in client_threads:
            thread.join(timeout=join_timeout)

        logger.info("Named pipe server stopped")

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            handle = self._create_pipe_handle()
            try:
                self._connect_pipe(handle)
            except Exception:
                win32file.CloseHandle(handle)
                if not self._stop_event.is_set():
                    logger.exception("named pipe accept failed")
                return

            if self._stop_event.is_set():
                stream = _Win32PipeStream(handle)
                stream.close()
                return

            thread = threading.Thread(
                target=self._client_loop,
                args=(_Win32PipeStream(handle),),
                name="minivllm-pipe-client",
                daemon=self._daemon_threads,
            )
            with self._client_threads_lock:
                self._client_threads.add(thread)
            thread.start()

    def _client_loop(self, stream: _Win32PipeStream) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    request = read_message(stream, self._envelope_factory())
                except ProtocolCodecError:
                    logger.warning("invalid protobuf frame received", exc_info=True)
                    return
                except pywintypes.error:
                    logger.debug("client pipe closed", exc_info=True)
                    return
                except OSError:
                    logger.debug("client stream closed", exc_info=True)
                    return

                try:
                    replies = self._normalize_replies(self._request_handler(request))
                    for reply in replies:
                        write_message(stream, reply)
                except Exception:
                    # Domain errors should normally be translated by request_router
                    # into ErrorReply envelopes. Escaped errors close only this client.
                    logger.exception("request handler failed")
                    return
        finally:
            try:
                stream.close()
            except Exception:
                logger.debug("client close raised", exc_info=True)
            with self._client_threads_lock:
                self._client_threads.discard(threading.current_thread())

    def _create_pipe_handle(self):
        return win32pipe.CreateNamedPipe(
            self._pipe_name,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            _DEFAULT_BUFFER_SIZE,
            _DEFAULT_BUFFER_SIZE,
            0,
            None,
        )

    @staticmethod
    def _connect_pipe(handle) -> None:
        try:
            win32pipe.ConnectNamedPipe(handle, None)
        except pywintypes.error as exc:
            # ERROR_PIPE_CONNECTED: client won the race and connected before
            # ConnectNamedPipe was invoked. That is still a successful accept.
            if exc.winerror != 535:
                raise

    def _wake_accept_loop(self) -> None:
        try:
            handle = win32file.CreateFile(
                self._pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
        except Exception:
            return
        try:
            win32file.CloseHandle(handle)
        except Exception:
            logger.debug("wake handle close raised", exc_info=True)

    @staticmethod
    def _normalize_replies(result: HandlerResult) -> Iterable[ProtocolMessage]:
        if result is None:
            return ()
        if isinstance(result, Message):
            return (result,)
        return result
