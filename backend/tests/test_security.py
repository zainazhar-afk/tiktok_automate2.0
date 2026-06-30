from fastapi.testclient import TestClient

from app.main import app
from app.services import safety


class DummySafetySettings:
    allowed_video_hosts = ["youtube.com", "youtu.be"]


class DummyAuthSettings:
    require_auth = True
    service_api_key = ""
    supabase_jwks_url = "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    supabase_url = "https://example.supabase.co"


def test_safe_id_rejects_path_traversal():
    assert safety.safe_id("abc_123-xyz", "video id") == "abc_123-xyz"

    for value in ["../abc", "abc/def", "abc.def", "", "a" * 81]:
        try:
            safety.safe_id(value, "video id")
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe id accepted: {value}")


def test_public_video_url_rejects_private_or_unapproved_hosts(monkeypatch):
    monkeypatch.setattr(safety, "get_settings", lambda: DummySafetySettings())
    monkeypatch.setattr(
        safety.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, "", ("93.184.216.34", 0))],
    )

    assert safety.validate_public_video_url("https://www.youtube.com/watch?v=abc")

    for url in [
        "file:///tmp/video.mp4",
        "http://127.0.0.1/video.mp4",
        "http://localhost/video.mp4",
        "https://evil.example/video.mp4",
    ]:
        try:
            safety.validate_public_video_url(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe URL accepted: {url}")


def test_public_video_url_rejects_private_dns_resolution(monkeypatch):
    monkeypatch.setattr(safety, "get_settings", lambda: DummySafetySettings())
    monkeypatch.setattr(
        safety.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, "", ("10.1.2.3", 0))],
    )

    try:
        safety.validate_public_video_url("https://www.youtube.com/watch?v=abc")
    except ValueError as exc:
        assert "Private network" in str(exc)
    else:
        raise AssertionError("private DNS resolution was accepted")


def test_auth_middleware_rejects_api_without_token_when_enabled(monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "get_settings", lambda: DummyAuthSettings())

    client = TestClient(app)
    response = client.get("/api/videos/list")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"
