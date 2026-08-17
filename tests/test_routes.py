from fastapi.testclient import TestClient


def test_api_under_kindling_prefix():
    from kindling.app import create_app

    app = create_app()
    client = TestClient(app)
    res = client.get('/api/kindling/health')
    assert res.status_code in (200, 401, 403)  # any non-404 means routed


def test_dashboard_served_at_kindling():
    from kindling.app import create_app

    app = create_app()
    client = TestClient(app)
    res = client.get('/kindling/')
    assert res.status_code == 200


def test_old_paths_return_404():
    from kindling.app import create_app

    app = create_app()
    client = TestClient(app)
    assert client.get('/kindling/').status_code == 404
    assert client.get('/api/kindling/health').status_code == 404
