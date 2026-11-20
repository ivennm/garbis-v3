from fastapi.testclient import TestClient

from garbis_server.main import app


def test_health_reports_ready_with_whisper_loaded():
    with TestClient(app) as client:          # runs the startup (whisper load)
        body = client.get("/health").json()
    assert body["ready"] is True
    assert body["stt_device"] in ("cuda", "cpu")
    assert body["protocol"] == 1
