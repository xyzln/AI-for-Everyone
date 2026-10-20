"""Cross-platform helpers: path resolution, subprocess, process management.

Stdlib only. No torch / no fastapi. Used by hardware probing and the Ollama
manager so those modules stay importable on a bare machine (architecture §1.3 R1).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def platform_label() -> str:
    import platform

    return platform.platform()


def python_version() -> str:
    return "{0.major}.{0.minor}.{0.micro}".format(sys.version_info)


def resolve_path(p: Optional[str]) -> Optional[Path]:
    """Expand ~ and ${VAR} in a path string; return None for empty input."""
    if p is None:
        return None
    return Path(os.path.expanduser(os.path.expandvars(p))).resolve()


def find_executable(name: str) -> Optional[str]:
    """Like ``shutil.which`` but also accepts an explicit path/name containing a slash."""
    return shutil_which(name)


def shutil_which(name: str) -> Optional[str]:
    import shutil

    return shutil.which(name)


def run_subprocess(
    cmd: list[str],
    timeout: float = 10.0,
    text: bool = True,
    env: Optional[dict[str, str]] = None,
    shell: bool = False,
) -> Tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr). Never raises on a missing
    binary — returns (nonzero, "", stderr) so probing degrades gracefully."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=text,
            encoding="utf-8",
            errors="replace",
            env=env,
            shell=shell,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or "" if isinstance(exc.stdout, str) else ""
        err = exc.stderr or "" if isinstance(exc.stderr, str) else ""
        return 124, out, err
    except OSError as exc:
        return 127, "", str(exc)


def total_memory_gb() -> float:
    """Best-effort total system RAM in GiB. Returns 0.0 if undetermined."""
    try:
        if is_windows():
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys / (1024 ** 3)
            return 0.0
        if is_linux():
            with open("/proc/meminfo") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
            return 0.0
        if is_macos():
            rc, out, _ = run_subprocess(
                ["sysctl", "-n", "hw.memsize"], timeout=5
            )
            if rc == 0 and out.strip().isdigit():
                return int(out.strip()) / (1024 ** 3)
        # generic
        import shutil

        total, _, _ = shutil.disk_usage(os.path.expanduser("~"))
        return total / (1024 ** 3)
    except Exception:
        return 0.0


def cpu_count_logical() -> int:
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def find_free_port(preferred: int = 8189, host: str = "127.0.0.1") -> int:
    """Return ``preferred`` if free, else an ephemeral free port."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, preferred))
        return preferred
    except OSError:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((host, 0))
        return s.getsockname()[1]
    finally:
        s.close()


def terminate_process_tree(pid: int, timeout: float = 10.0) -> None:
    """Terminate a process (and its children where supported). Best effort."""
    import signal

    try:
        if is_windows():
            os.system(f"taskkill /F /T /PID {pid} >NUL 2>NUL")
            return
        os.kill(pid, signal.SIGTERM)
        # give it a moment; hard kill if still around
        try:
            os.waitpid(pid, 0)  # type: ignore[arg-type]
        except Exception:
            pass
    except Exception:
        pass


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
