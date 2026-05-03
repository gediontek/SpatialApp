"""Harness — N11 (/api/register has no rate limit).

Contract: a single client IP MUST be rate-limited on /api/register so
bot-create loops cannot exhaust the user table or enumerate usernames.
The configured cap is 5 / hour per IP via services.rate_limiter.register_limiter.
"""
import pytest

from services.rate_limiter import register_limiter, PerKeyRateLimiter


@pytest.fixture(autouse=True)
def _reset_register_limiter():
    """Per-test reset so order doesn't poison the bucket."""
    register_limiter.reset()
    yield
    register_limiter.reset()


def test_per_key_limiter_allows_burst_then_blocks():
    """Cap behavior on the limiter primitive."""
    lim = PerKeyRateLimiter("test", max_requests=3, window_seconds=60)
    assert lim.allow("ip1") is True
    assert lim.allow("ip1") is True
    assert lim.allow("ip1") is True
    assert lim.allow("ip1") is False  # over the cap


def test_per_key_limiter_separate_keys():
    """Different keys have independent buckets."""
    lim = PerKeyRateLimiter("test", max_requests=2, window_seconds=60)
    assert lim.allow("ip1") is True
    assert lim.allow("ip1") is True
    assert lim.allow("ip2") is True  # different key — independent
    assert lim.allow("ip1") is False


def test_register_endpoint_rate_limited():
    """End-to-end: 6th register from same IP returns 429."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        # First 5 may legitimately fail for other reasons (duplicate
        # username, DB not available in test scope) but must NOT 429.
        # We POST minimal valid data.
        for i in range(5):
            r = client.post(
                "/api/register",
                json={"username": f"harness_n11_{i}_uniq"},
                environ_overrides={"REMOTE_ADDR": "10.55.0.99"},
            )
            assert r.status_code != 429, (
                f"Unexpected 429 on attempt {i + 1} (cap is 5)."
            )
        # 6th attempt MUST 429.
        r = client.post(
            "/api/register",
            json={"username": "harness_n11_should_429"},
            environ_overrides={"REMOTE_ADDR": "10.55.0.99"},
        )
        assert r.status_code == 429, (
            f"Audit N11 regression: 6th register from same IP returned "
            f"{r.status_code} instead of 429."
        )


def test_register_endpoint_separate_ips_independent():
    """Different IPs have independent rate-limit buckets."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        for _ in range(5):
            client.post(
                "/api/register",
                json={"username": "harness_n11_burned"},
                environ_overrides={"REMOTE_ADDR": "10.55.0.100"},
            )
        # Different IP — first request must NOT 429.
        r = client.post(
            "/api/register",
            json={"username": "harness_n11_other_ip"},
            environ_overrides={"REMOTE_ADDR": "10.55.0.101"},
        )
        assert r.status_code != 429, (
            "Per-IP isolation broken: a different IP was throttled."
        )
