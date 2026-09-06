from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_configured_frontend_origin():
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_does_not_allow_arbitrary_origin():
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_does_not_enable_credentials():
    client = TestClient(app)
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-credentials" not in response.headers
