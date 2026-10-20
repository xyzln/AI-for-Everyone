"""Single YAML configuration source for AIE (04-data-model §2.1).

Loads ``~/.aife/config.yaml`` (or a path resolved from CLI/``$AIE_CONFIG``),
expands ``${VAR}`` / ``${VAR:-default}`` references, validates with pydantic v2,
and supports in-process reload for hot-swapping (ADR-003). The domain layer never
imports ``fastapi`` (architecture §1.3 R1).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .utils.logging import get_logger

logger = get_logger("aife.config")

CONFIG_VERSION = 1
DEFAULT_DIR = Path.home() / ".aife"
DEFAULT_PATH = DEFAULT_DIR / "config.yaml"

_PATH_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}$")
_KEEPALIVE_RE = re.compile(r"^[0-9]+[smhd]$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_MODEL_NAME_RE = re.compile(r"^[a-z0-9._-]+(/[a-z0-9._-]+)?(:[a-z0-9._-]+)?$")


# --------------------------------------------------------------------------- #
# Low-level env expansion
# --------------------------------------------------------------------------- #
def expand_env(value: Any) -> Any:
    """Recursively expand ``${VAR}`` and ``${VAR:-default}`` in strings/lists/dicts."""
    if isinstance(value, str):
        # single-token case: ${VAR} / ${VAR:-default}
        m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}", value.strip())
        if m:
            var, _, default = m.group(1), m.group(2), m.group(3)
            return os.environ.get(var, default if default is not None else "")
        # inline interpolation
        return re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-([^}]*))?\}",
            lambda mm: os.environ.get(mm.group(1), mm.group(3) or ""),
            value,
        )
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def _expand_path(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return os.path.expanduser(os.path.expandvars(value))


# --------------------------------------------------------------------------- #
# Config schema
# --------------------------------------------------------------------------- #
class HardwareConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    device: Literal["auto", "cuda", "rocm", "vulkan", "xpu", "mps", "npu", "cpu"] = "auto"
    vram_gb: Optional[float] = None  # read-only, filled by probing


class InstallConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    method: Literal["auto", "winget", "brew", "apt", "script", "manual"] = "auto"
    confirm: bool = True


class OllamaConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str = "127.0.0.1"
    port: int = Field(default=11434, ge=1, le=65535)
    autostart: bool = True
    keep_alive: str = "5m"
    num_gpu: int = Field(default=-1, ge=-1)
    max_loaded_models: int = Field(default=1, ge=1, le=8)
    executable: str = "ollama"
    models_dir: Optional[str] = None
    min_version: str = "0.5.0"
    shutdown_on_exit: bool = True
    install: InstallConfig = Field(default_factory=InstallConfig)

    @field_validator("host")
    @classmethod
    def _host_ok(cls, v: str) -> str:
        if not v:
            raise ValueError("ollama.host 不可为空")
        return v

    @field_validator("keep_alive")
    @classmethod
    def _keepalive_ok(cls, v: str) -> str:
        if not _KEEPALIVE_RE.match(v):
            raise ValueError("keep_alive 需为 ^[0-9]+(s|m|h|d)$")
        return v

    @field_validator("min_version")
    @classmethod
    def _ver_ok(cls, v: str) -> str:
        if not _VERSION_RE.match(v):
            raise ValueError("min_version 需为语义化版本 ^\\d+\\.\\d+\\.\\d+$")
        return v

    @field_validator("executable", "models_dir")
    @classmethod
    def _expand_path_fields(cls, v: Optional[str]) -> Optional[str]:
        return _expand_path(v)


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    default: Optional[str] = None
    tier: Literal["auto", "1.5b", "3b", "7b", "14b"] = "auto"
    max_concurrent_pull: int = Field(default=1, ge=1, le=4)

    @field_validator("default")
    @classmethod
    def _model_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _MODEL_NAME_RE.match(v):
            raise ValueError("models.default 格式不合法")
        return v


class BackendsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    active: Literal["ollama", "openai_compat", "llamacpp", "vllm"] = "ollama"
    fallback: list[Literal["ollama", "openai_compat", "llamacpp", "vllm"]] = Field(
        default_factory=lambda: ["ollama"]
    )


class OpenAICompatConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    base_url: str = "${AIE_OPENAI_BASE_URL:-https://api.openai.com/v1}"
    api_key: str = "${AIE_OPENAI_API_KEY:-}"
    model: str = "gpt-4o-mini"
    timeout_s: float = Field(default=120, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("api_key")
    @classmethod
    def _api_key_form(cls, v: str) -> str:
        if v and not _PATH_RE.match(v.strip()):
            raise ValueError("openai_compat.api_key 只允许 ${VAR} 形式或空串")
        return v

    @field_validator("base_url")
    @classmethod
    def _url_ok(cls, v: str) -> str:
        if not re.match(r"^https?://", v):
            raise ValueError("openai_compat.base_url 需为 http(s) URL")
        return v


class LlamaCppConfig(BaseModel):
    """llama-server（llama.cpp）后端：managed 拉起或 adopted 连接外部已在跑实例。"""

    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    binary: str = ""            # llama-server 可执行文件名或路径；空=只连接
    host: str = "127.0.0.1"
    port: int = Field(default=8081, ge=1, le=65535)
    model: str = ""             # GGUF 模型文件路径（-m）
    base_url: str = ""          # adopted：连接已在跑的 llama-server
    autostart: bool = True      # managed 模式下由 AIE 拉起
    startup_timeout_s: int = Field(default=120, gt=0)
    extra_args: list[str] = Field(default_factory=list)  # 如 -ngl/--n-gpu-layers、-c

    @field_validator("base_url")
    @classmethod
    def _url_ok(cls, v: str) -> str:
        if v and not re.match(r"^https?://", v):
            raise ValueError("llamacpp.base_url 需为 http(s) URL")
        return v


class VllmConfig(BaseModel):
    """vLLM 后端：managed 拉起或 adopted 连接外部已在跑实例（GPU/CUDA/ROCm 为主）。"""

    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    binary: str = ""            # vllm 或 python 解释器路径；空=命令行回退 vllm
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    model: str = ""             # HF 模型名或本地路径（--model）
    base_url: str = ""          # adopted：连接已在跑的 vLLM 服务
    autostart: bool = True      # managed 模式下由 AIE 拉起
    startup_timeout_s: int = Field(default=180, gt=0)  # vLLM 加载权重慢，超时更长
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("base_url")
    @classmethod
    def _url_ok(cls, v: str) -> str:
        if v and not re.match(r"^https?://", v):
            raise ValueError("vllm.base_url 需为 http(s) URL")
        return v


class DesktopConfig(BaseModel):
    """原生桌面窗口行为（aife/desktop.py 消费）。

    托盘为可选增强：pystray 缺失时自动跳过，窗口行为不变（优雅降级）。
    """

    model_config = ConfigDict(extra="ignore")
    tray: bool = True               # 启用系统托盘图标（需可选依赖 pystray）
    minimize_to_tray: bool = True   # 最小化时隐藏到托盘而非任务栏


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str = "127.0.0.1"
    port: int = Field(default=8189, ge=1, le=65535)
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    open_browser: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:8189", "http://localhost:8189"]
    )
    ws_heartbeat_s: float = 30.0


class ChatConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_timeout_s: float = 300.0
    stream_timeout_s: float = 600.0
    stream_idle_timeout_s: float = 120.0


class NetworkConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mirror: Literal["auto", "official", "custom"] = "auto"
    mirror_urls: list[str] = Field(default_factory=list)
    proxy: Optional[str] = None
    connect_timeout_s: float = Field(default=10, gt=0)
    read_timeout_s: float = Field(default=600, gt=0)
    retries: int = Field(default=2, ge=0, le=5)


class SetupConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    skip: list[Literal["deps", "ollama", "model"]] = Field(default_factory=list)


class BenchConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    duration_s: int = Field(default=30, gt=0)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dir: Optional[str] = None
    app_file: str = "aife.log"
    rotate_max_mb: float = Field(default=10, gt=0)
    rotate_backups: int = Field(default=5, ge=0)
    run_log_keep: int = Field(default=20, ge=1)
    jsonl: bool = True
    console_level: Literal["debug", "info", "warning", "error"] = "info"


class AifeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    config_version: Literal[1] = 1
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    backends: BackendsConfig = Field(default_factory=BackendsConfig)
    openai_compat: OpenAICompatConfig = Field(default_factory=OpenAICompatConfig)
    llamacpp: LlamaCppConfig = Field(default_factory=LlamaCppConfig)
    vllm: VllmConfig = Field(default_factory=VllmConfig)
    desktop: DesktopConfig = Field(default_factory=DesktopConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    setup: SetupConfig = Field(default_factory=SetupConfig)
    bench: BenchConfig = Field(default_factory=BenchConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def _cross(self) -> "AifeConfig":
        if self.server.port == self.ollama.port:
            raise ValueError("server.port 不可与 ollama.port 相同")
        if self.network.mirror == "custom" and not self.network.mirror_urls:
            raise ValueError("mirror=custom 时 network.mirror_urls 不可为空")
        if not self.backends.fallback:
            raise ValueError("backends.fallback 不可为空")
        # 本地推理服务端口互斥：启用的 llamacpp/vllm 不得与 ollama/server 端口冲突，
        # 启用项之间也不可冲突（否则 managed 子进程必然端口占用失败）。
        local_ports: dict[str, int] = {
            "ollama": self.ollama.port,
            "server": self.server.port,
        }
        if self.llamacpp.enabled:
            local_ports["llamacpp"] = self.llamacpp.port
        if self.vllm.enabled:
            local_ports["vllm"] = self.vllm.port
        seen: dict[int, str] = {}
        for label, port in local_ports.items():
            if port in seen:
                raise ValueError(
                    f"{label}.port({port}) 与 {seen[port]}.port 冲突，本地服务端口必须互异"
                )
            seen[port] = label
        return self


# --------------------------------------------------------------------------- #
# Loading / persistence
# --------------------------------------------------------------------------- #
def _resolve_path(explicit: Optional[str] = None) -> Optional[Path]:
    if explicit:
        return Path(os.path.expanduser(os.path.expandvars(explicit))).resolve()
    env = os.environ.get("AIE_CONFIG")
    if env:
        return Path(os.path.expanduser(os.path.expandvars(env))).resolve()
    if DEFAULT_PATH.exists():
        return DEFAULT_PATH
    return None


def _template_path() -> Path:
    # Repo template lives at <repo>/config/aife.yaml; fall back to defaults if absent.
    from .utils.paths import resource_root
    cand = resource_root() / "config" / "aife.yaml"
    return cand if cand.exists() else DEFAULT_PATH


def load_config(path: Optional[str] = None) -> AifeConfig:
    """Load and validate config. Missing file -> defaults (no write)."""
    p = _resolve_path(path)
    if p is None or not p.exists():
        logger.info("config not found, using built-in defaults",
                    fields={"path": str(p) if p else None})
        return AifeConfig()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("config parse failed, using defaults", fields={"error": str(exc)})
        return AifeConfig()
    raw = expand_env(raw)
    try:
        cfg = AifeConfig.model_validate(raw)
    except Exception as exc:
        logger.error("config validation failed, using defaults",
                     fields={"error": str(exc)})
        raise
    cfg._path = p  # type: ignore[attr-defined]
    return cfg


def ensure_config() -> Path:
    """Ensure ~/.aife/config.yaml exists (copy from template). Returns its path."""
    DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_PATH.exists():
        tmpl = _template_path()
        try:
            DEFAULT_PATH.write_text(tmpl.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info("config initialized", fields={"path": str(DEFAULT_PATH)})
        except Exception as exc:
            logger.warning("could not copy config template", fields={"error": str(exc)})
    return DEFAULT_PATH


def save_config(cfg: AifeConfig, path: Optional[str] = None) -> Path:
    """Atomically write config (backup previous)."""
    p = _resolve_path(path) or DEFAULT_PATH
    if p.exists():
        bak = p.with_suffix(p.suffix + ".bak")
        bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    # Round-trip through model to drop computed-only fields.
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
    return p
