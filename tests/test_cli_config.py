"""CLI: 全局 ``--config`` 必须对所有命令生效（不只 detect）。

``serve``/``backend``/``chat``/``models``/``setup``/``doctor`` 都经
``get_runtime() -> load_config()``（无路径），只读 ``$AIE_CONFIG`` 或默认
``~/.aife/config.yaml``。``main()`` 在有 ``--config`` 时把它注入
``$AIE_CONFIG``，这些命令因此统一 honor 显式配置路径。
"""

import os

import aife.runtime as runtime_mod
from aife.cli import main


def _write_config(tmp_path) -> str:
    p = tmp_path / "aife-cli-test.yaml"
    p.write_text(
        "config_version: 1\n"
        "llamacpp:\n"
        "  enabled: true\n"
        "  base_url: http://127.0.0.1:9\n"  # adopted：不拉起，连接必然拒绝
        "backends:\n"
        "  active: llamacpp\n"
        "  fallback: [llamacpp]\n",
        encoding="utf-8",
    )
    return str(p)


def test_config_flag_honored_by_backend_doctor(tmp_path, capsys):
    cfg = _write_config(tmp_path)
    saved = os.environ.pop("AIE_CONFIG", None)
    runtime_mod.reset_runtime()
    try:
        rc = main(["--config", cfg, "backend", "doctor"])
        assert rc == 0
        out = capsys.readouterr().out
        # 缺省配置下只会注册 ollama；出现 llamacpp 证明 --config 已生效
        assert "llamacpp" in out
        # 显式 --config 覆盖环境变量，供后续 get_runtime()/load_config() 使用
        assert os.environ.get("AIE_CONFIG") == cfg
    finally:
        os.environ.pop("AIE_CONFIG", None)
        if saved is not None:
            os.environ["AIE_CONFIG"] = saved
        runtime_mod.reset_runtime()


def test_config_flag_honored_by_backend_use(tmp_path, capsys):
    cfg = _write_config(tmp_path)
    saved = os.environ.pop("AIE_CONFIG", None)
    runtime_mod.reset_runtime()
    try:
        # backend use 不走网络：缺省配置下 llamacpp 未注册会返回 1；
        # 返回 0 且打印切换成功，证明 registry 来自 --config 指定的配置。
        rc = main(["--config", cfg, "backend", "use", "llamacpp"])
        assert rc == 0
        assert "已切换至 llamacpp" in capsys.readouterr().out
        assert os.environ.get("AIE_CONFIG") == cfg
    finally:
        os.environ.pop("AIE_CONFIG", None)
        if saved is not None:
            os.environ["AIE_CONFIG"] = saved
        runtime_mod.reset_runtime()
