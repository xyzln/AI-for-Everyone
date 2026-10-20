"""llama.cpp server backend (managed subprocess or adopted).

``llama-server`` exposes the OpenAI protocol (``/health``, ``/v1/models``,
``/v1/chat/completions``); lifecycle and SSE normalization live in
``ManagedServerBackend``. GPU offload depends on the ``llama-server`` build
(CUDA / Vulkan / Metal / CPU): control layer counts via ``extra_args``
(``-ngl`` / ``--n-gpu-layers``), context via ``-c``.
"""

from __future__ import annotations

from ..config import AifeConfig, LlamaCppConfig
from .managed_server import ManagedServerBackend


class LlamaCppBackend(ManagedServerBackend):
    name = "llamacpp"
    kind = "llamacpp"

    def __init__(self, cfg: AifeConfig, section: LlamaCppConfig) -> None:
        super().__init__(cfg, section)

    def _launch_args(self) -> list[str]:
        s = self.section
        return [
            s.binary, "-m", s.model,
            "--host", s.host, "--port", str(s.port),
            *s.extra_args,
        ]
