"""vLLM backend (managed subprocess or adopted).

``vllm serve`` (or ``python -m vllm.entrypoints.openai.api_server``) exposes the
OpenAI protocol; lifecycle and SSE normalization live in
``ManagedServerBackend``. vLLM targets GPUs (CUDA / ROCm) — the CPU backend is
experimental and slow; set ``extra_args`` (e.g. ``--device cpu``) only knowingly.
"""

from __future__ import annotations

import os

from ..config import AifeConfig, VllmConfig
from .managed_server import ManagedServerBackend


def _is_python_interpreter(binary: str) -> bool:
    """True when ``binary`` names a Python interpreter (python, python3.12, …)."""
    if not binary:
        return False
    name = os.path.basename(binary).lower()
    return name.startswith("python") or name.endswith("python")


class VllmBackend(ManagedServerBackend):
    name = "vllm"
    kind = "vllm"

    def __init__(self, cfg: AifeConfig, section: VllmConfig) -> None:
        super().__init__(cfg, section)

    def _launch_args(self) -> list[str]:
        s = self.section
        if _is_python_interpreter(s.binary):
            return [
                s.binary, "-m", "vllm.entrypoints.openai.api_server",
                "--model", s.model,
                "--host", s.host, "--port", str(s.port),
                *s.extra_args,
            ]
        # vllm serve <model>：模型是位置参数
        return [
            s.binary or "vllm", "serve", s.model,
            "--host", s.host, "--port", str(s.port),
            *s.extra_args,
        ]
