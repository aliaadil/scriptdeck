import os
from pathlib import Path


def test_env_var_prefix():
    os.environ['KINDLING_DB_PATH'] = '/tmp/kindling.db'
    os.environ.pop('SCRIPTDECK_DB_PATH', None)
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
