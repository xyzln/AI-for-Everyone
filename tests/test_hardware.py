"""Hardware probing: CPU fallback + degrade chain + tier mapping (02-architecture §3.3)."""

from aife.hardware import probe_devices, resolve_profile


def test_probe_always_has_cpu_fallback():
    devices = probe_devices()
    assert any(d.kind == "cpu" for d in devices)


def test_resolve_returns_known_profile():
    resolved = resolve_profile()
    assert resolved.profile_id in {
        "nvidia_cuda", "amd_rocm", "intel_xpu", "apple_mps",
        "amd_vulkan", "intel_npu", "cpu",
    }


def test_catalog_tier_from_ram():
    # This machine has ~95 GiB RAM -> 14b tier regardless of GPU/NPU presence.
    resolved = resolve_profile()
    assert resolved.catalog_tier == "14b"


def test_resolved_has_ollama_env_and_request_options():
    resolved = resolve_profile()
    assert isinstance(resolved.ollama_env, dict)
    assert isinstance(resolved.request_options, dict)
