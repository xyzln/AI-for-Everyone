"""Config: env expansion, defaults, validation (04-data-model §2.1)."""

import os

import pytest
from pydantic import ValidationError

from aife.config import AifeConfig, expand_env, load_config


def test_expand_env_single():
    os.environ["AIE_TEST_VAR"] = "hi"
    assert expand_env("${AIE_TEST_VAR}") == "hi"


def test_expand_env_default():
    assert expand_env("${AIE_NOPE_XYZ:-fallback}") == "fallback"


def test_expand_inline():
    os.environ["AIE_TEST_VAR"] = "v"
    assert expand_env("prefix-${AIE_TEST_VAR}-suffix") == "prefix-v-suffix"


def test_load_defaults():
    cfg = load_config()
    assert cfg.server.port == 8189
    assert cfg.ollama.port == 11434


def test_validation_bad_port():
    with pytest.raises(ValidationError):
        AifeConfig.model_validate({"ollama": {"port": 99999}})


def test_cross_port_conflict():
    with pytest.raises(ValidationError):
        AifeConfig.model_validate(
            {"server": {"port": 11434}, "ollama": {"port": 11434}}
        )
