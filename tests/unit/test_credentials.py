import stat
import sys

import pytest

from magnacoda import credentials, userdir


def _use_tmp_config(monkeypatch, tmp_path):
    monkeypatch.setattr(userdir.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)


def test_credentials_dir_honours_xdg_config_home_on_linux(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert credentials.credentials_dir() == tmp_path / "magnacoda"


def test_credentials_dir_falls_back_to_dot_config_when_xdg_unset(monkeypatch):
    monkeypatch.setattr(userdir.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert credentials.credentials_dir() == credentials.Path.home() / ".config" / "magnacoda"


def test_credentials_dir_uses_appdata_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(userdir.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert credentials.credentials_dir() == tmp_path / "magnacoda"


def test_load_stored_key_returns_none_when_no_file_exists(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") is None


def test_save_then_load_round_trip(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    path = credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-abc123")
    assert path == tmp_path / "magnacoda" / "credentials.json"
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") == "sk-ant-abc123"


def test_save_key_locks_file_to_owner_only_on_posix(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    if sys.platform == "win32":
        return
    path = credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-abc123")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_save_key_overwrites_an_existing_value(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-old")
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-new")
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") == "sk-ant-new"


def test_multiple_keys_coexist_under_different_env_var_names(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-one")
    credentials.save_key("OTHER_KEY_ENV", "sk-other-two")
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") == "sk-ant-one"
    assert credentials.load_stored_key("OTHER_KEY_ENV") == "sk-other-two"


def test_clear_key_removes_the_value_and_reports_true(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-abc123")
    assert credentials.clear_key("ANTHROPIC_API_KEY") is True
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") is None


def test_clear_key_on_absent_key_returns_false_without_error(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    assert credentials.clear_key("ANTHROPIC_API_KEY") is False


def test_clearing_the_last_key_deletes_the_file_entirely(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-abc123")
    credentials.clear_key("ANTHROPIC_API_KEY")
    assert not credentials.credentials_path().exists()


def test_clearing_one_of_several_keys_keeps_the_others(monkeypatch, tmp_path):
    _use_tmp_config(monkeypatch, tmp_path)
    credentials.save_key("ANTHROPIC_API_KEY", "sk-ant-one")
    credentials.save_key("OTHER_KEY_ENV", "sk-other-two")
    credentials.clear_key("ANTHROPIC_API_KEY")
    assert credentials.credentials_path().exists()
    assert credentials.load_stored_key("OTHER_KEY_ENV") == "sk-other-two"


@pytest.mark.parametrize("text", ["not valid json {{{", "[1, 2, 3]"])  # broken, or JSON but not an object
def test_load_stored_key_tolerates_a_damaged_file(monkeypatch, tmp_path, text):
    _use_tmp_config(monkeypatch, tmp_path)
    path = credentials.credentials_path()
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    assert credentials.load_stored_key("ANTHROPIC_API_KEY") is None
