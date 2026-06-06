from fastapi.testclient import TestClient

from rezn_ai.api.main import app


def test_health_exposes_weave_project():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "weave_project": "rezn-ai/rezn-ai",
    }
