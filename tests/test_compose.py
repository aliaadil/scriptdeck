from pathlib import Path
import yaml


def test_compose_image_and_container():
    data = yaml.safe_load(Path('docker-compose.yml').read_text())
    svc = data['services']['kindling']
    assert 'aliaadil/kindling' in svc['image']
    assert svc['container_name'] == 'kindling'


def test_compose_env_uses_kindling_prefix():
    data = yaml.safe_load(Path('docker-compose.yml').read_text())
    env = data['services']['kindling'].get('environment', {})
    keys = list(env.keys()) if isinstance(env, dict) else [k.split('=')[0] for k in env]
    assert any(k.startswith('KINDLING_') for k in keys)
    assert not any(k.startswith('KINDLING_') for k in keys)