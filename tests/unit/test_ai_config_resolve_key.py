from magnacoda import credentials, userdir
from magnacoda.config import AIConfig


def _use_tmp_config(monkeypatch, tmp_path):
    monkeypatch.setattr(userdir.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)


def test_resolve_api_key_returns_none_when_nothing_is_set(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert AIConfig().resolve_api_key() is None


def test_resolve_api_key_falls_back_to_the_stored_key(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-stored")

    assert AIConfig().resolve_api_key() == "sk-ant-stored"


def test_resolve_api_key_prefers_the_env_var_over_a_stored_key(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-stored")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    assert AIConfig().resolve_api_key() == "sk-ant-from-env"


def test_resolve_api_key_honours_a_custom_api_key_env_name(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)
    credentials.save_key("MY_CUSTOM_KEY", "sk-ant-custom")

    assert AIConfig(api_key_env="MY_CUSTOM_KEY").resolve_api_key() == "sk-ant-custom"
