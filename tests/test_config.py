import os
from pathlib import Path


def test_env_var_prefix(monkeypatch):
    monkeypatch.setenv('KINDLING_DB_PATH', '/tmp/kindling.db')
    from kindling.config import load_config, reset_cache
    reset_cache()
    cfg = load_config()
    assert cfg.db_path == Path('/tmp/kindling.db')


def test_config_file_name(tmp_path, monkeypatch):
    cfg_file = tmp_path / 'kindling.toml'
    cfg_file.write_text('db_path = "/tmp/from-file.db"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('KINDLING_DB_PATH', raising=False)
    from kindling.config import load_config, reset_cache
    reset_cache()
    cfg = load_config()
    assert cfg.db_path == Path('/tmp/from-file.db')


def test_default_db_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('KINDLING_DB_PATH', raising=False)
    monkeypatch.delenv('KINDLING_CONFIG', raising=False)
    from kindling.config import load_config, reset_cache
    reset_cache()
    cfg = load_config()
    assert cfg.db_path == Path('./data/kindling.db')


def test_create_app_fails_without_env_key(monkeypatch, tmp_path):
    """Bare-Python boot without KINDLING_ENV_ENCRYPTION_KEY must hard-fail,
    not silently fall back to a zero-byte AES-GCM key."""
    monkeypatch.delenv('KINDLING_ENV_ENCRYPTION_KEY', raising=False)
    monkeypatch.setenv('KINDLING_DB_PATH', str(tmp_path / 'k.db'))
    from kindling.config import Settings, reset_cache
    from kindling.app import create_app

    reset_cache()
    s = Settings(db_path=str(tmp_path / 'k.db'))
    try:
        create_app(s)
    except RuntimeError as exc:
        assert 'KINDLING_ENV_ENCRYPTION_KEY' in str(exc)
    else:
        raise AssertionError('create_app() should have raised without env key')


def test_create_app_with_test_opt_out(monkeypatch, tmp_path):
    """allow_insecure_defaults_for_tests=True bypasses the fail-fast check."""
    monkeypatch.delenv('KINDLING_ENV_ENCRYPTION_KEY', raising=False)
    monkeypatch.setenv('KINDLING_DB_PATH', str(tmp_path / 'k.db'))
    from kindling.config import Settings
    from kindling.app import create_app

    s = Settings(
        db_path=str(tmp_path / 'k.db'),
        allow_insecure_defaults_for_tests=True,
    )
    # Should construct without raising.
    app = create_app(s)
    assert app.title == 'Kindling'

