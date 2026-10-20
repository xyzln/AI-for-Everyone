"""Ollama process lifecycle: detection, launch, health, restart, graceful exit.

Implements requirement #3 (Ollama 加速配置): derives the exact env whitelist from
the resolved acceleration profile (03-ollama-accel §2.1), launches Ollama as a
managed subprocess (killed on exit when ``shutdown_on_exit``), or adopts an
already-running Ollama (never killed). ``num_gpu`` is intentionally NOT injected as
an env var — it lives only in request-level options (architecture §1.2 errata1).
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx

from ..config import OllamaConfig
from ..utils.logging import get_logger
from ..utils.platform import find_executable, terminate_process_tree
from .protocol import OllamaClient, OllamaProtocolError

logger = get_logger("aife.ollama.manager")


class OllamaStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    CRASHED = "crashed"


class OllamaManagerState:
    def __init__(self) -> None:
        self.status: OllamaStatus = OllamaStatus.STOPPED
        self.pid: Optional[int] = None
        self.version: Optional[str] = None
        self.env: dict[str, str] = {}
        self.restart_count: int = 0
        self.started_at: Optional[datetime] = None
        self.adopted: bool = False
        self.last_error: Optional[str] = None


class OllamaManager:
    def __init__(self, cfg: OllamaConfig, resolved, proxy: Optional[str] = None) -> None:
        self.cfg = cfg
        self.resolved = resolved
        self.proxy = proxy
        self.base_url = f"http://{cfg.host}:{cfg.port}"
        self.client = OllamaClient(self.base_url, proxy=proxy)
        self.state = OllamaManagerState()
        self._proc: Optional[subprocess.Popen] = None

    # ---- env derivation ---------------------------------------------------- #
    def build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["OLLAMA_HOST"] = f"{self.cfg.host}:{self.cfg.port}"
        env["OLLAMA_KEEP_ALIVE"] = self.cfg.keep_alive
        env["OLLAMA_MAX_LOADED_MODELS"] = str(self.cfg.max_loaded_models)
        # Acceleration profile env (whitelist only — 03-ollama-accel §2.1).
        for k, v in (self.resolved.ollama_env or {}).items():
            env[k] = str(v)
        if self.cfg.models_dir:
            env["OLLAMA_MODELS"] = os.path.expanduser(os.path.expandvars(self.cfg.models_dir))
        if self.proxy:
            env["HTTP_PROXY"] = self.proxy
            env["HTTPS_PROXY"] = self.proxy
            env["NO_PROXY"] = "127.0.0.1,localhost"
        return env

    # ---- detection --------------------------------------------------------- #
    def is_installed(self) -> bool:
        return find_executable(self.cfg.executable) is not None

    def binary_version(self) -> Optional[str]:
        rc, out, _ = _run([self.cfg.executable, "--version"], timeout=8)
        if rc == 0:
            for tok in out.replace("version", " ").split():
                if tok.count(".") == 2:
                    return tok
        return None

    # ---- health ------------------------------------------------------------ #
    async def ping(self, timeout: float = 5.0) -> bool:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as c:
                r = await c.get("/api/version")
                if r.status_code == 200:
                    self.state.version = (r.json().get("version") or "").strip() or None
                    return True
        except (httpx.HTTPError, OSError):
            pass
        return False

    async def is_healthy(self) -> bool:
        try:
            v = await self.client.version()
            self.state.version = v or self.state.version
            return bool(v)
        except OllamaProtocolError:
            return False
        except Exception:  # pragma: no cover
            return False

    def check_version(self) -> tuple[bool, Optional[str]]:
        """Return (ok, remedy) against cfg.min_version (D11)."""
        ver = self.state.version or self.binary_version()
        if not ver:
            return False, f"未检测到 Ollama；请先安装（>= {self.cfg.min_version}）"
        if not _ge_version(ver, self.cfg.min_version):
            return False, (
                f"Ollama 版本 {ver} 低于最低要求 {self.cfg.min_version}，"
                f"请升级：curl -fsSL https://ollama.com/install.sh | sh"
            )
        return True, None

    # ---- lifecycle --------------------------------------------------------- #
    async def ensure_started(self) -> OllamaStatus:
        """Adopt if externally running, else launch managed (if autostart)."""
        if await self.ping(3.0):
            self.state.status = OllamaStatus.RUNNING
            self.state.adopted = True
            await self.is_healthy()
            logger.info("adopted running Ollama", fields={"base_url": self.base_url})
            return self.state.status
        if not self.cfg.autostart:
            self.state.status = OllamaStatus.STOPPED
            return self.state.status
        if not self.is_installed():
            self.state.status = OllamaStatus.UNHEALTHY
            self.state.last_error = "ollama 未安装"
            return self.state.status
        await self._launch()
        return self.state.status

    async def _launch(self) -> None:
        env = self.build_env()
        cmd = [self.cfg.executable, "serve"]
        logger.info("launching managed Ollama", fields={"cmd": " ".join(cmd)})
        self._proc = subprocess.Popen(
            cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.state.status = OllamaStatus.STARTING
        self.state.pid = self._proc.pid
        self.state.adopted = False
        self.state.started_at = datetime.now(timezone.utc)
        for _ in range(30):
            if await self.ping(2.0):
                self.state.status = OllamaStatus.RUNNING
                await self.is_healthy()
                return
            await asyncio.sleep(0.5)
        self.state.status = OllamaStatus.UNHEALTHY
        self.state.last_error = "启动后健康检查超时"

    async def restart(self) -> None:
        logger.info("restarting Ollama", fields={"managed": not self.state.adopted})
        await self.shutdown()
        await asyncio.sleep(1.0)
        self.state.restart_count += 1
        await self._launch()

    async def shutdown(self) -> None:
        if self.state.adopted:
            logger.info("adopted Ollama — not terminating")
            return
        if self._proc is not None and self._proc.poll() is None:
            terminate_process_tree(self._proc.pid)
            try:
                self._proc.wait(timeout=10)
            except Exception:
                pass
        if self.cfg.shutdown_on_exit and self.state.pid and self._proc is None:
            terminate_process_tree(self.state.pid)
        self.state.status = OllamaStatus.STOPPED

    async def aclose(self) -> None:
        if self.cfg.shutdown_on_exit:
            await self.shutdown()
        await self.client.aclose()


def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    rc, out, err = (0, "", "")
    try:
        p = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, text=True, encoding="utf-8", errors="replace",
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", exc.stderr or ""
    except OSError as exc:
        return 127, "", str(exc)


def _ge_version(a: str, b: str) -> bool:
    def _t(v: str):
        nums = re.findall(r"\d+", v)
        return tuple(int(x) for x in nums[:3]) if nums else (0,)
    return _t(a) >= _t(b)
