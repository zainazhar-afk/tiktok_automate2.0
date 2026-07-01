from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.main import app
from app.config import validate_runtime_settings
from app.services import discovery, entitlements, safety, state_store


class DummySafetySettings:
    allowed_video_hosts = ["youtube.com", "youtu.be"]


class DummyAuthSettings:
    require_auth = True
    service_api_key = ""
    supabase_jwks_url = "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    supabase_url = "https://example.supabase.co"


class DummyEntitlementSettings:
    billing_required = True
    require_rights_attestation = False
    default_plan = "pro"
    allowed_subscription_statuses = {"active", "trialing"}
    monthly_download_limit = 1
    monthly_process_limit = 1
    monthly_transcription_limit = 1
    monthly_variant_limit = 1
    monthly_timeline_render_limit = 1
    stripe_secret_key = ""
    stripe_price_id = ""
    stripe_webhook_secret = ""
    stripe_portal_return_url = ""
    app_url = "http://localhost:3001"


class DummyRuntimeSettings:
    app_environment = "production"
    require_auth = False
    supabase_url = ""
    supabase_jwks_url = ""


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


def test_production_runtime_requires_auth_and_supabase_jwks():
    try:
        validate_runtime_settings(DummyRuntimeSettings())
    except RuntimeError as exc:
        assert "REQUIRE_AUTH" in str(exc)
    else:
        raise AssertionError("production settings allowed auth to be disabled")

    valid = DummyRuntimeSettings()
    valid.require_auth = True
    valid.supabase_url = "https://example.supabase.co"
    valid.supabase_jwks_url = "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    assert validate_runtime_settings(valid) is valid


def test_entitlement_blocks_unpaid_user_when_billing_required(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    monkeypatch.setattr(state_store, "DB_PATH", str(db_path))
    monkeypatch.setattr(entitlements, "get_settings", lambda: DummyEntitlementSettings())
    state_store.init_db()

    request = SimpleNamespace(
        state=SimpleNamespace(
            user=SimpleNamespace(
                user_id="user_1",
                email="u@example.com",
                role="authenticated",
                plan="",
                subscription_status="",
                stripe_customer_id="",
            )
        )
    )

    try:
        entitlements.require_feature(request, "download")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 402
    else:
        raise AssertionError("unpaid user was allowed")


def test_entitlement_records_and_enforces_monthly_usage(tmp_path, monkeypatch):
    class Settings(DummyEntitlementSettings):
        billing_required = False
        require_rights_attestation = False

    db_path = tmp_path / "state.db"
    monkeypatch.setattr(state_store, "DB_PATH", str(db_path))
    monkeypatch.setattr(entitlements, "get_settings", lambda: Settings())
    state_store.init_db()

    request = SimpleNamespace(
        state=SimpleNamespace(
            user=SimpleNamespace(
                user_id="user_2",
                email="u2@example.com",
                role="authenticated",
                plan="pro",
                subscription_status="active",
                stripe_customer_id="",
            )
        )
    )

    entitlements.require_feature(request, "download")
    try:
        entitlements.require_feature(request, "download")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 429
    else:
        raise AssertionError("over-quota user was allowed")


def test_fallback_search_passes_query_as_subprocess_argument(monkeypatch):
    captured = {}

    def fake_run_command(cmd, timeout=60):
        captured["cmd"] = cmd
        return 1, "", ""

    monkeypatch.setattr(discovery, "find_python", lambda: "python")
    monkeypatch.setattr(discovery, "run_command", fake_run_command)

    query = "safe'; import os; os.system('bad') #"
    discovery._fallback_search(query, 3)

    cmd = captured["cmd"]
    assert cmd[:3] == ["python", "-c", cmd[2]]
    assert query == cmd[3]
    assert query not in cmd[2]
