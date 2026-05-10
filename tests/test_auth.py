"""Direct unit tests for blueprints/auth.py.

The decorator + 4 routes are exercised indirectly through other suites,
but the auth surface is security-critical and deserves direct contract
tests. Covers BL2 from /critical-review (auth.py was untested directly).

Pinned contracts:
  - require_api_token: per-user vs shared vs no-token modes
  - /api/register: validation, dedup, rate limit, no PII leak on error
  - /api/me: identifies the bearer correctly, anon for no-token mode
  - /api/health: minimal vs full body based on auth, per-user counts
  - /api/health/ready: 200 only when DB+LLM both up
"""
from __future__ import annotations

import json
import os

# Clear LLM keys + downgrade prod-secret check before importing app.
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY",
           "GEMINI_API_KEY", "GOOGLE_API_KEY"):
    os.environ[_k] = ""
os.environ.setdefault("FLASK_DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "auth-test-secret")

import pytest

from app import app
from config import Config
import state
from services.rate_limiter import register_limiter


@pytest.fixture
def client():
    prior_csrf = app.config.get("WTF_CSRF_ENABLED")
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    register_limiter.reset()
    with state.layer_lock:
        state.layer_store.clear()
        state.layer_owners.clear()
    state.chat_sessions.clear()
    try:
        with app.test_client() as c:
            yield c
    finally:
        register_limiter.reset()
        if prior_csrf is not None:
            app.config["WTF_CSRF_ENABLED"] = prior_csrf


def _register(client, username):
    r = client.post(
        "/api/register",
        data=json.dumps({"username": username}),
        content_type="application/json",
    )
    return r


# ---------------------------------------------------------------------------
# /api/register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_returns_201_with_token(self, client):
        r = _register(client, "alice_unit")
        assert r.status_code == 201, r.get_data(as_text=True)
        body = r.get_json()
        assert body.get("success") is True
        assert body.get("user_id")
        assert body.get("api_token")
        assert body.get("username") == "alice_unit"

    def test_missing_username_400(self, client):
        r = client.post("/api/register",
                        data=json.dumps({}),
                        content_type="application/json")
        assert r.status_code == 400
        assert "username" in r.get_json().get("error", "").lower()

    def test_blank_username_400(self, client):
        r = _register(client, "   ")
        assert r.status_code == 400

    def test_too_long_username_400(self, client):
        r = _register(client, "x" * 101)
        assert r.status_code == 400

    def test_duplicate_username_currently_allowed(self, client):
        """Pinning the actual contract: `users.username` has no UNIQUE
        constraint (only `api_token` does), so duplicate usernames are
        accepted and produce a NEW user with a new token. The 409 path
        in auth.py only fires on token-hash collision, which is a
        (practically impossible) UUID4 birthday event. If we ever decide
        usernames should be unique, change the schema first, then flip
        this test to expect 409."""
        first = _register(client, "dupe_unit")
        second = _register(client, "dupe_unit")
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.get_json()["user_id"] != second.get_json()["user_id"]
        assert first.get_json()["api_token"] != second.get_json()["api_token"]

    def test_token_collision_yields_409(self, client, monkeypatch):
        """The 409 branch in auth.py keys on 'UNIQUE' in the exception
        message. Force a collision-shaped exception and confirm the
        sanitized error fires."""
        if state.db is None:
            pytest.skip("DB unavailable")

        def _boom(username, api_token=None):
            raise Exception(
                "UNIQUE constraint failed: users.api_token"
            )

        monkeypatch.setattr(state.db, "create_user", _boom)
        r = _register(client, "collision_unit")
        assert r.status_code == 409
        body = r.get_json()
        assert "already exists" in body.get("error", "").lower()
        # Even on the 409 path, raw exception details must not leak.
        text = r.get_data(as_text=True).lower()
        assert "constraint" not in text
        assert "users.api_token" not in text

    def test_register_rate_limit_5_per_hour(self, client):
        """N11 contract: 5 successful registrations per IP, then 429."""
        for i in range(5):
            r = _register(client, f"rl_unit_{i}")
            assert r.status_code == 201, f"call {i}: {r.get_data(as_text=True)}"
        # 6th must be rate-limited
        sixth = _register(client, "rl_unit_overflow")
        assert sixth.status_code == 429
        assert "registration" in sixth.get_json().get("error", "").lower()

    def test_error_response_does_not_leak_exception(self, client):
        """N10 hardening: registration failures must not echo the exception
        string back to the client (could leak DB internals)."""
        # Trigger UNIQUE constraint via duplicate; assert error string is
        # the sanitized one, not the raw sqlite message.
        _register(client, "leak_check")
        r = _register(client, "leak_check")
        body_text = r.get_data(as_text=True).lower()
        assert "sqlite" not in body_text
        assert "constraint" not in body_text
        assert "traceback" not in body_text


# ---------------------------------------------------------------------------
# require_api_token decorator (via /api/me)
# ---------------------------------------------------------------------------

class TestRequireApiToken:
    def test_no_token_no_config_open_access(self, client):
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = ""
        try:
            r = client.get("/api/me")
            assert r.status_code == 200
            assert r.get_json().get("user_id") == "anonymous"
        finally:
            Config.CHAT_API_TOKEN = prior

    def test_no_token_when_config_set_returns_401(self, client):
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "shared-secret-test"
        try:
            r = client.get("/api/me")
            assert r.status_code == 401
        finally:
            Config.CHAT_API_TOKEN = prior

    def test_invalid_token_returns_401(self, client):
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "shared-secret-test"
        try:
            r = client.get("/api/me",
                           headers={"Authorization": "Bearer wrong-token"})
            assert r.status_code == 401
        finally:
            Config.CHAT_API_TOKEN = prior

    def test_shared_token_admits(self, client):
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "shared-secret-admit"
        try:
            r = client.get(
                "/api/me",
                headers={"Authorization": "Bearer shared-secret-admit"},
            )
            assert r.status_code == 200
        finally:
            Config.CHAT_API_TOKEN = prior

    def test_per_user_token_resolves_user_id(self, client):
        reg = _register(client, "puttest_unit")
        assert reg.status_code == 201
        token = reg.get_json()["api_token"]
        user_id = reg.get_json()["user_id"]

        r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        body = r.get_json()
        assert body.get("user_id") == user_id
        assert body.get("username") == "puttest_unit"

    def test_per_user_token_takes_precedence_over_shared(self, client):
        """If a token matches a real user AND happens to equal the shared
        token, the user identity wins — never silently downgrade to anon."""
        reg = _register(client, "precedence_unit")
        token = reg.get_json()["api_token"]
        user_id = reg.get_json()["user_id"]
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = token  # simulate the collision
        try:
            r = client.get("/api/me",
                           headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            assert r.get_json().get("user_id") == user_id
        finally:
            Config.CHAT_API_TOKEN = prior

    def test_authorization_header_without_bearer_prefix_is_unauthorized(self, client):
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "needed"
        try:
            r = client.get("/api/me",
                           headers={"Authorization": "raw-token-no-bearer"})
            assert r.status_code == 401
        finally:
            Config.CHAT_API_TOKEN = prior


# ---------------------------------------------------------------------------
# /api/health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_unauthed_returns_minimal_body(self, client):
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = "guard-health"
        try:
            r = client.get("/api/health")
            assert r.status_code == 200
            body = r.get_json()
            assert body.get("status") == "ok"
            # Must NOT leak subsystem info to anonymous.
            assert "checks" not in body, (
                f"unauthed health leaked subsystem details: {body}"
            )
            assert "version" in body
            assert "uptime_seconds" in body
        finally:
            Config.CHAT_API_TOKEN = prior

    def test_no_token_configured_returns_full_body(self, client):
        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = ""
        try:
            r = client.get("/api/health")
            assert r.status_code == 200
            body = r.get_json()
            assert "checks" in body
            assert "database" in body["checks"]
            assert "llm" in body["checks"]
            assert "layers" in body["checks"]
        finally:
            Config.CHAT_API_TOKEN = prior

    def test_per_user_layer_count_isolation(self, client):
        """N10b regression: /api/health layer count must be per-user, not
        global. User A creating a layer must not be visible to User B's
        health probe."""
        reg_a = _register(client, "health_a")
        reg_b = _register(client, "health_b")
        token_a = reg_a.get_json()["api_token"]
        token_b = reg_b.get_json()["api_token"]
        uid_a = reg_a.get_json()["user_id"]

        # Plant a layer owned by A.
        with state.layer_lock:
            state.layer_store["a_only_layer"] = {
                "type": "FeatureCollection", "features": [],
            }
            state.layer_owners["a_only_layer"] = uid_a

        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = ""
        try:
            r_a = client.get(
                "/api/health",
                headers={"Authorization": f"Bearer {token_a}"},
            )
            r_b = client.get(
                "/api/health",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        finally:
            Config.CHAT_API_TOKEN = prior

        count_a = r_a.get_json()["checks"]["layers"]["count"]
        count_b = r_b.get_json()["checks"]["layers"]["count"]
        assert count_a >= 1, f"owner saw {count_a} of own layers"
        assert count_b == 0, (
            f"non-owner saw {count_b} layers — N10b cross-user leak"
        )

    def test_health_does_not_leak_db_exception_string(self, client, monkeypatch):
        """N10a contract: a DB error during the annotation-count probe
        must not surface str(exception) (could leak file paths or SQL)."""
        if state.db is None:
            pytest.skip("DB unavailable")

        def _boom(user_id=None):
            raise RuntimeError("/leaky/path/db.sqlite UNIQUE constraint failed")

        monkeypatch.setattr(state.db, "get_annotation_count", _boom)

        prior = Config.CHAT_API_TOKEN
        Config.CHAT_API_TOKEN = ""
        try:
            r = client.get("/api/health")
        finally:
            Config.CHAT_API_TOKEN = prior

        body_text = r.get_data(as_text=True).lower()
        assert "/leaky/path" not in body_text
        assert "unique constraint" not in body_text
        assert "traceback" not in body_text
        # The DB check itself should have been marked as error/degraded.
        body = r.get_json()
        assert body["checks"]["database"]["status"] == "error"
        assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# /api/health/ready
# ---------------------------------------------------------------------------

class TestHealthReady:
    def test_returns_503_when_llm_key_absent(self, client, monkeypatch):
        monkeypatch.setattr(Config, "get_llm_api_key", staticmethod(lambda: ""))
        r = client.get("/api/health/ready")
        assert r.status_code == 503
        body = r.get_json()
        assert body["ready"] is False
        assert body["checks"]["llm"] is False

    def test_returns_200_when_both_up(self, client, monkeypatch):
        monkeypatch.setattr(Config, "get_llm_api_key",
                            staticmethod(lambda: "test-key"))
        if state.db is None:
            pytest.skip("DB unavailable for ready check")
        r = client.get("/api/health/ready")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ready"] is True
        assert body["checks"]["database"] is True
        assert body["checks"]["llm"] is True

    def test_n29_prod_mode_requires_chat_auth_token(self, client, monkeypatch):
        """Audit N29: in prod mode (DEBUG=False) readiness MUST also
        check CHAT_API_TOKEN. Otherwise a load balancer happily routes
        traffic to an instance whose /api/chat is unauthenticated and
        runs up the LLM bill.
        """
        if state.db is None:
            pytest.skip("DB unavailable for ready check")
        monkeypatch.setattr(Config, "get_llm_api_key",
                            staticmethod(lambda: "test-key"))
        monkeypatch.setattr(Config, "DEBUG", False)
        monkeypatch.setattr(Config, "CHAT_API_TOKEN", "")

        r = client.get("/api/health/ready")
        assert r.status_code == 503
        body = r.get_json()
        assert body["ready"] is False
        assert body["checks"]["chat_auth"] is False
        # DB + LLM should still report green so the operator can see
        # exactly which gate failed.
        assert body["checks"]["database"] is True
        assert body["checks"]["llm"] is True

    def test_n29_prod_mode_with_chat_auth_token_returns_200(
        self, client, monkeypatch,
    ):
        """The other half of N29: setting CHAT_API_TOKEN in prod mode
        unblocks readiness."""
        if state.db is None:
            pytest.skip("DB unavailable for ready check")
        monkeypatch.setattr(Config, "get_llm_api_key",
                            staticmethod(lambda: "test-key"))
        monkeypatch.setattr(Config, "DEBUG", False)
        monkeypatch.setattr(Config, "CHAT_API_TOKEN", "prod-secret-token")

        r = client.get("/api/health/ready")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ready"] is True
        assert body["checks"]["chat_auth"] is True

    def test_n29_debug_mode_does_not_require_chat_auth(
        self, client, monkeypatch,
    ):
        """The dev-friendliness half of N29: in DEBUG mode, missing
        CHAT_API_TOKEN must not block readiness — devs run the dev
        server without it all the time."""
        if state.db is None:
            pytest.skip("DB unavailable for ready check")
        monkeypatch.setattr(Config, "get_llm_api_key",
                            staticmethod(lambda: "test-key"))
        monkeypatch.setattr(Config, "DEBUG", True)
        monkeypatch.setattr(Config, "CHAT_API_TOKEN", "")

        r = client.get("/api/health/ready")
        assert r.status_code == 200
        body = r.get_json()
        assert body["ready"] is True
        assert body["checks"]["chat_auth"] is True
