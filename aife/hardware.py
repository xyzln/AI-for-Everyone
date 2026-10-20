"""Hardware probing & acceleration-profile resolution (02-architecture §3.3 / 04-data-model §2.5).

Implements requirement #2 (设备感知): probe the machine with a graceful degrade
chain and resolve a concrete Ollama acceleration profile. CPU is a first-class
fallback (ADR-002) — a bare machine with no GPU MUST still resolve to a working
``cpu`` profile.

Stdlib + lazy torch only. Never imports fastapi (architecture §1.3 R1).
"""

from __future__ import annotations

import platform as _platform
import re
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .utils.logging import get_logger
from .utils.platform import cpu_count_logical, run_subprocess, total_memory_gb

logger = get_logger("aife.hardware")


class Evidence(str, Enum):
    E0 = "E0"  # 实测 direct command output reproduced
    E1 = "E1"  # 系统工具输出 (nvidia-smi / rocm-smi / WMI / sysfs / pnp)
    E2 = "E2"  # 推断 inference from driver/model/env
    E3 = "E3"  # 猜测 fallback


# Vendor profiles (04-data-model §2.5.2). env tables are authoritative (03-ollama-accel §2.1).
class VendorProfile(BaseModel):
    profile_id: str
    display_name: str
    priority: int
    device_kinds: list[str]
    ollama_accel: dict[str, str] = Field(default_factory=dict)
    request_defaults: dict[str, Any] = Field(default_factory=dict)
    min_ram_gb: float = 0.0
    experimental: bool = False
    caveats: list[str] = Field(default_factory=list)


VENDOR_PROFILES: dict[str, VendorProfile] = {
    "nvidia_cuda": VendorProfile(
        profile_id="nvidia_cuda", display_name="NVIDIA CUDA", priority=0,
        device_kinds=["cuda"], ollama_accel={},
        request_defaults={"num_gpu": -1, "num_ctx": 4096, "keep_alive": "5m"},
        min_ram_gb=4.0, caveats=["CUDA 由 Ollama 自动探测，无需额外环境变量"],
    ),
    "amd_rocm": VendorProfile(
        profile_id="amd_rocm", display_name="AMD ROCm (Linux)", priority=1,
        device_kinds=["rocm"], ollama_accel={},
        request_defaults={"num_gpu": -1, "num_ctx": 4096, "keep_alive": "5m"},
        min_ram_gb=4.0, caveats=["ROCm 主要在 Linux；HSA_OVERRIDE_GFX_VERSION 需显式 opt-in"],
    ),
    "intel_xpu": VendorProfile(
        profile_id="intel_xpu", display_name="Intel GPU (experimental)", priority=2,
        device_kinds=["xpu"], ollama_accel={"OLLAMA_INTEL_GPU": "1"},
        request_defaults={"num_gpu": -1, "num_ctx": 4096, "keep_alive": "5m"},
        min_ram_gb=4.0, experimental=True,
        caveats=["Intel GPU 路径为实验性；核显可追加 OLLAMA_IGPU_ENABLE=1"],
    ),
    "apple_mps": VendorProfile(
        profile_id="apple_mps", display_name="Apple Metal", priority=3,
        device_kinds=["mps"], ollama_accel={},
        request_defaults={"num_ctx": 4096, "keep_alive": "5m"},  # no num_gpu (D12)
        min_ram_gb=4.0, caveats=["Metal 由 Ollama 自管统一内存，不设 num_gpu"],
    ),
    "amd_vulkan": VendorProfile(
        profile_id="amd_vulkan", display_name="AMD Vulkan (Windows)", priority=4,
        device_kinds=["vulkan"], ollama_accel={"OLLAMA_VULKAN": "1"},
        request_defaults={"num_gpu": -1, "num_ctx": 4096, "keep_alive": "5m"},
        min_ram_gb=4.0, experimental=True,
        caveats=["Windows AMD 走 Vulkan；核显追加 OLLAMA_IGPU_ENABLE=1（实验性）"],
    ),
    "intel_npu": VendorProfile(
        profile_id="intel_npu", display_name="Intel NPU (no Ollama backend)", priority=5,
        device_kinds=["npu"], ollama_accel={},
        request_defaults={"num_gpu": 0, "num_ctx": 4096, "keep_alive": "5m"},
        min_ram_gb=4.0, experimental=True,
        caveats=["Ollama 主线无 NPU 后端，推理回退 CPU 路径"],
    ),
    "cpu": VendorProfile(
        profile_id="cpu", display_name="CPU", priority=6,
        device_kinds=["cpu"], ollama_accel={"OLLAMA_LOAD_TIMEOUT": "10m"},
        request_defaults={"num_gpu": 0, "num_ctx": 4096, "keep_alive": "5m"},
        min_ram_gb=2.0, caveats=["CPU 推理：首 token 延迟较高，适合 1.5b/3b 级模型"],
    ),
}

# Auto detection priority (ADR-002 / 04-data-model §2.1.2).
_AUTO_PRIORITY = ["cuda", "rocm", "xpu", "mps", "vulkan", "npu", "cpu"]


# --------------------------------------------------------------------------- #
# Data models
# --------------------------------------------------------------------------- #
class DeviceInfo(BaseModel):
    kind: str
    vendor: str
    name: str
    index: int = 0
    available: bool = True
    vram_gb: Optional[float] = None
    driver_version: Optional[str] = None
    cuda_version: Optional[str] = None
    compute_capability: Optional[str] = None
    torch_backend: Optional[str] = None
    evidence: Evidence
    source: str
    detail: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ResolvedProfile(BaseModel):
    profile_id: str
    device: Optional[DeviceInfo] = None
    device_kind_name: str
    devices: list[DeviceInfo] = Field(default_factory=list)
    ollama_env: dict[str, str] = Field(default_factory=dict)
    request_options: dict[str, Any] = Field(default_factory=dict)
    catalog_tier: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    fallback_from: Optional[str] = None
    launch_args: list[str] = Field(default_factory=list)


class ProfileSummary(BaseModel):
    profile_id: str
    device_kind: str
    fallback_from: Optional[str] = None
    experimental: bool = False
    caveats: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HardwareReport(BaseModel):
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    platform: str
    python: str
    devices: list[DeviceInfo] = Field(default_factory=list)
    profile: ProfileSummary
    evidence: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    system_ram_gb: Optional[float] = None
    cpu_cores: Optional[int] = None


# --------------------------------------------------------------------------- #
# Detection helpers
# --------------------------------------------------------------------------- #
def _cpu_name() -> str:
    try:
        if sys.platform == "win32":
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                val = winreg.QueryValueEx(key, "ProcessorNameString")[0]
                if val:
                    return " ".join(str(val).split())
    except Exception:
        pass
    proc = _platform.processor()
    if proc:
        return proc
    return "CPU"


def _detect_nvidia() -> Optional[DeviceInfo]:
    rc, out, err = run_subprocess(
        ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
         "--format=csv,noheader,nounits"], timeout=5
    )
    if rc != 0 or not out.strip():
        return None
    try:
        parts = [p.strip() for p in out.strip().split(",")]
        name = parts[0]
        vram = float(parts[1]) / 1024.0 if len(parts) > 1 else None
        driver = parts[2] if len(parts) > 2 else None
        cc = None
        try:  # lazy torch for finer capability detail (E0)
            import torch  # type: ignore

            if torch.cuda.is_available():
                cc = ".".join(str(x) for x in torch.cuda.get_device_capability(0))
        except Exception:
            pass
        return DeviceInfo(
            kind="cuda", vendor="nvidia", name=name, vram_gb=vram,
            driver_version=driver, compute_capability=cc,
            evidence=Evidence.E1, source="nvidia-smi",
            detail=out.strip()[:2000],
        )
    except Exception as exc:  # pragma: no cover - malformed output
        logger.warning("nvidia-smi parse failed", fields={"error": str(exc)})
        return None


def _detect_rocm() -> Optional[DeviceInfo]:
    rc, out, err = run_subprocess(
        ["rocm-smi", "--showproductname", "--showdriverversion", "--showmeminfo", "vram"],
        timeout=5,
    )
    if rc != 0 or not out.strip():
        return None
    try:
        name = re.search(r"Card series:\s*(.+)", out) or re.search(r"(AMD[^\\n]+)", out)
        vram_m = re.search(r"Total Memory\s*\(B\):\s*(\d+)", out)
        vram = (int(vram_m.group(1)) / 1024 ** 3) if vram_m else None
        return DeviceInfo(
            kind="rocm", vendor="amd", name=(name.group(1).strip() if name else "AMD GPU"),
            vram_gb=vram, evidence=Evidence.E1, source="rocm-smi",
            detail=out.strip()[:2000],
        )
    except Exception:
        return None


def _detect_mps() -> Optional[DeviceInfo]:
    if sys.platform == "darwin" and _platform.machine() == "arm64":
        return DeviceInfo(
            kind="mps", vendor="apple", name="Apple Silicon",
            evidence=Evidence.E1, source="mps",
            detail="Apple Silicon unified memory",
        )
    return None


def _detect_intel_npu() -> Optional[DeviceInfo]:
    # Best-effort Windows PnP probe for an Intel NPU; harmless when absent.
    if sys.platform != "win32":
        return None
    try:
        rc, out, _ = run_subprocess(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Microsoft.NETProcessorUpstream | "
             "Where-Object {$_.FriendlyName -match 'NPU'} | Select-Object -First 1 FriendlyName"],
            timeout=8,
        )
        if rc == 0 and "NPU" in out:
            return DeviceInfo(
                kind="npu", vendor="intel", name=out.strip(),
                evidence=Evidence.E1, source="pnp",
                detail=out.strip()[:2000],
            )
    except Exception:
        pass
    return None


def _detect_cpu(ram_gb: float) -> DeviceInfo:
    return DeviceInfo(
        kind="cpu", vendor="unknown", name=_cpu_name(),
        index=0, available=True, vram_gb=None,
        evidence=Evidence.E3, source="fallback",
        detail=f"CPU fallback; total RAM≈{ram_gb:.1f}GiB, {cpu_count_logical()} logical cores",
    )


def probe_devices() -> list[DeviceInfo]:
    """Run the degrade chain; always end with a CPU fallback entry."""
    devices: list[DeviceInfo] = []
    try:
        nv = _detect_nvidia()
        if nv:
            devices.append(nv)
    except Exception as exc:
        logger.warning("nvidia probe error", fields={"error": str(exc)})
    try:
        rocm = _detect_rocm()
        if rocm:
            devices.append(rocm)
    except Exception:
        pass
    try:
        xpu = _detect_intel_npu()
        if xpu:
            devices.append(xpu)
    except Exception:
        pass
    try:
        mps = _detect_mps()
        if mps:
            devices.append(mps)
    except Exception:
        pass
    # Vulkan path is detected via AMD on Windows in real runs; explicit probe
    # omitted here (would require dxgi/driver APIs). Add CPU fallback last.
    ram = total_memory_gb()
    devices.append(_detect_cpu(ram))
    return devices


# --------------------------------------------------------------------------- #
# Profile resolution
# --------------------------------------------------------------------------- #
def _kind_to_profile(kind: str) -> Optional[str]:
    for pid, vp in VENDOR_PROFILES.items():
        if kind in vp.device_kinds:
            return pid
    return None


def resolve_profile(
    devices: Optional[list[DeviceInfo]] = None,
    *,
    explicit_device: Optional[str] = None,
) -> ResolvedProfile:
    """Pick a VendorProfile from detected devices (or an explicit device).

    Priority follows ADR-002: cuda > rocm > xpu > mps > vulkan > npu > cpu.
    CPU is always reachable as the final fallback.
    """
    if devices is None:
        devices = probe_devices()

    chosen_pid: Optional[str] = None
    chosen_device: Optional[DeviceInfo] = None

    if explicit_device and explicit_device != "auto":
        # Map explicit device string to a known profile id.
        for pid, vp in VENDOR_PROFILES.items():
            if explicit_device in (pid, vp.device_kinds[0] if vp.device_kinds else ""):
                chosen_pid = pid
                # pick a matching detected device if present
                for d in devices:
                    if d.kind in vp.device_kinds:
                        chosen_device = d
                        break
                break
        if chosen_pid is None:
            logger.warning("unknown explicit device, falling back to auto",
                           fields={"device": explicit_device})
            explicit_device = None

    if chosen_pid is None:
        for kind in _AUTO_PRIORITY:
            pid = _kind_to_profile(kind)
            if pid is None:
                continue
            for d in devices:
                if d.kind in VENDOR_PROFILES[pid].device_kinds:
                    chosen_pid = pid
                    chosen_device = d
                    break
            if chosen_pid:
                break

    if chosen_pid is None:
        chosen_pid = "cpu"

    vp = VENDOR_PROFILES[chosen_pid]
    warnings: list[str] = []
    fallback_from: Optional[str] = None

    if chosen_pid == "cpu":
        warnings.append(
            "未检测到可用 GPU，将使用 CPU 推理路径；首 token 延迟较高，"
            "建议使用 1.5b/3b 级模型（如 qwen2.5:3b）。"
        )
    if vp.experimental:
        warnings.append(f"加速剖面 {vp.display_name} 为实验性，推理可能回退 CPU。")

    # Catalog tier from RAM (CPU/NPU path) or VRAM (GPU path).
    catalog_tier = _recommend_tier(chosen_device, total_memory_gb())

    ollama_env = dict(vp.ollama_accel)
    request_options = dict(vp.request_defaults)

    # evidence aggregation
    ev_counts: dict[str, int] = {}
    for d in devices:
        ev_counts[d.evidence.value] = ev_counts.get(d.evidence.value, 0) + 1
    min_ev = min((d.evidence.value for d in devices), default="E3")

    return ResolvedProfile(
        profile_id=chosen_pid,
        device=chosen_device,
        device_kind_name=vp.display_name,
        devices=devices,
        ollama_env=ollama_env,
        request_options=request_options,
        catalog_tier=catalog_tier,
        warnings=warnings,
        evidence={"min_evidence": min_ev, "by_channel": ev_counts},
        fallback_from=fallback_from,
        launch_args=[],  # Ollama has no perf launch args; only env + request options
    )


def _recommend_tier(device: Optional[DeviceInfo], ram_gb: float) -> str:
    """D8 tier table (architecture §11 / 04-data-model §2.1.4)."""
    vram = device.vram_gb if device and device.vram_gb else None
    has_gpu = bool(vram) and device.kind not in ("cpu", "npu")
    if has_gpu:
        if vram >= 12:
            return "14b"
        if 8 <= vram < 12:
            return "7b"
        return "3b"
    # CPU / NPU / no-accel -> RAM based
    if ram_gb >= 32:
        return "14b"
    if 16 <= ram_gb < 32:
        return "7b"
    if 8 <= ram_gb < 16:
        return "3b"
    return "1.5b"


def build_report(resolved: Optional[ResolvedProfile] = None) -> HardwareReport:
    if resolved is None:
        resolved = resolve_profile()
    ram = total_memory_gb()
    vp = VENDOR_PROFILES[resolved.profile_id]
    summary = ProfileSummary(
        profile_id=resolved.profile_id,
        device_kind=resolved.device_kind_name,
        fallback_from=resolved.fallback_from,
        experimental=vp.experimental,
        caveats=list(vp.caveats),
        warnings=list(resolved.warnings),
    )
    return HardwareReport(
        platform=_platform.platform(),
        python="{0.major}.{0.minor}.{0.micro}".format(sys.version_info),
        devices=resolved.devices,
        profile=summary,
        evidence=resolved.evidence,
        warnings=resolved.warnings,
        system_ram_gb=round(ram, 1),
        cpu_cores=cpu_count_logical(),
    )
