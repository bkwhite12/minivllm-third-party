"""Minimal worker bring-up entrypoint."""

from __future__ import annotations

import logging
import os

from Protocol.python_generated import minivllm_runtime_pb2 as pb
from WindowsKernelPack.upstream_adapter import UpstreamMiniVllmAdapter

from .inference_service import InferenceService
from .pipe_server import NamedPipeServer
from .request_router import RequestRouter, WorkerRuntimeInfo


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    adapter = UpstreamMiniVllmAdapter(mode=os.environ.get("MINIVLLM_MODE", "dev"))
    config_path = os.environ.get("MINIVLLM_CONFIG_PATH")
    if config_path:
        adapter.load_model_from_config(
            config_path,
            model_alias=os.environ.get("MINIVLLM_MODEL_ALIAS", "default"),
        )

    health = adapter.health_snapshot()
    runtime_info = WorkerRuntimeInfo(
        active_model=health["active_model"],
        backend=health["backend"],
    )
    service = InferenceService(adapter=adapter)
    router = RequestRouter(runtime_info=runtime_info, inference_service=service)
    server = NamedPipeServer(pb.Envelope, router.handle)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
