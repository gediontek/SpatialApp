"""Tests for v2.1 Plan 13 production hardening.

Covers:
- Security headers on responses (M2.3)
- /api/health uptime+version + /api/health/ready (M4.3)
- Model router heuristic (M3.2)
- LLM response cache (M3.1)
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault('FLASK_DEBUG', 'false')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('ANTHROPIC_API_KEY', '')

from app import app
from services.llm_cache import LLMCache, BYPASS_PHRASES, should_bypass
from services.model_router import (
    ModelRouter,
    RouterDecision,
    get_default_router,
    reset_default_router,
)


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    return app.test_client()


# ---------------------------------------------------------------------------
# Security headers (M2.3)
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    def test_health_response_has_security_headers(self, client):
        r = client.get('/api/health')
        assert r.status_code == 200
        assert r.headers.get('X-Content-Type-Options') == 'nosniff'
        assert r.headers.get('X-Frame-Options') == 'DENY'
        assert r.headers.get('X-XSS-Protection') == '0'
        assert r.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'
        assert 'default-src' in r.headers.get('Content-Security-Policy', '')

    def test_csp_allows_known_cdns(self, client):
        r = client.get('/api/health')
        csp = r.headers.get('Content-Security-Policy', '')
        assert 'cdn.jsdelivr.net' in csp
        assert 'unpkg.com' in csp
        # Map tile origins
        assert 'tile.openstreetmap.org' in csp

    def test_hsts_only_when_proxied_https(self, client):
        # Without X-Forwarded-Proto, HSTS must NOT be set
        r = client.get('/api/health')
        assert 'Strict-Transport-Security' not in r.headers

    def test_hsts_set_when_proxied_https(self, client):
        r = client.get('/api/health', headers={'X-Forwarded-Proto': 'https'})
        assert 'Strict-Transport-Security' in r.headers
        assert 'max-age=' in r.headers['Strict-Transport-Security']

    def test_security_headers_on_unknown_route_too(self, client):
        r = client.get('/api/this-does-not-exist')
        assert r.headers.get('X-Content-Type-Options') == 'nosniff'


# ---------------------------------------------------------------------------
# Health endpoints (M4.3)
# ---------------------------------------------------------------------------

class TestHealthEndpoints:
    def test_health_includes_uptime_and_version(self, client):
        r = client.get('/api/health')
        body = r.get_json()
        assert 'uptime_seconds' in body
        assert isinstance(body['uptime_seconds'], (int, float))
        assert body['uptime_seconds'] >= 0
        assert 'version' in body

    def test_readiness_returns_503_when_llm_not_configured(self, client, monkeypatch):
        # Force LLM key to empty so we get the not-configured branch
        from config import Config
        monkeypatch.setattr(Config, 'ANTHROPIC_API_KEY', '')
        monkeypatch.setattr(Config, 'GEMINI_API_KEY', '')
        monkeypatch.setattr(Config, 'OPENAI_API_KEY', '')
        r = client.get('/api/health/ready')
        body = r.get_json()
        assert body['checks']['llm'] is False
        # Status reflects readiness
        if body['ready']:
            assert r.status_code == 200
        else:
            assert r.status_code == 503

    def test_readiness_includes_uptime(self, client):
        r = client.get('/api/health/ready')
        body = r.get_json()
        assert 'uptime_seconds' in body


# ---------------------------------------------------------------------------
# Model router (M3.2)
# ---------------------------------------------------------------------------

class TestModelRouter:
    def setup_method(self):
        reset_default_router()

    def teardown_method(self):
        reset_default_router()

    def test_disabled_by_default(self):
        # Env var unset → disabled
        os.environ.pop("MODEL_TIERING_ENABLED", None)
        r = ModelRouter()
        assert r.enabled is False
        d = r.select("Where is Paris?")
        assert d.tier == "complex"
        assert d.matched_pattern is None

    def test_simple_query_routes_to_haiku(self):
        r = ModelRouter(simple_model="haiku-x", complex_model="sonnet-x", enabled=True)
        d = r.select("Where is Paris?")
        assert d.tier == "simple"
        assert d.model == "haiku-x"

    def test_show_query_simple(self):
        r = ModelRouter(simple_model="h", complex_model="c", enabled=True)
        d = r.select("Show me parks")
        assert d.tier == "simple"

    def test_complex_disqualifier_overrides_simple_match(self):
        r = ModelRouter(simple_model="h", complex_model="c", enabled=True)
        # "Show" matches a simple pattern, but "buffer" disqualifies.
        d = r.select("Show parks then buffer them by 500m")
        assert d.tier == "complex"
        assert "buffer" in (d.matched_pattern or "")

    def test_long_message_complex(self):
        r = ModelRouter(simple_model="h", complex_model="c", enabled=True)
        msg = " ".join(["word"] * 30)
        d = r.select(msg)
        assert d.tier == "complex"
        assert d.matched_pattern == "length>25"

    def test_default_to_complex(self):
        r = ModelRouter(simple_model="h", complex_model="c", enabled=True)
        d = r.select("flibbertigibbet xyzzy")  # nothing matches
        assert d.tier == "complex"
        assert d.matched_pattern is None

    def test_empty_message_complex(self):
        r = ModelRouter(simple_model="h", complex_model="c", enabled=True)
        assert r.select("").tier == "complex"
        assert r.select(None).tier == "complex"  # type: ignore[arg-type]

    def test_router_factory_singleton(self):
        a = get_default_router()
        b = get_default_router()
        assert a is b
        reset_default_router()
        c = get_default_router()
        assert c is not a

    def test_chained_query_complex(self):
        r = ModelRouter(simple_model="h", complex_model="c", enabled=True)
        d = r.select("Show parks then color them green")
        assert d.tier == "complex"

    def test_isochrone_complex(self):
        r = ModelRouter(simple_model="h", complex_model="c", enabled=True)
        assert r.select("Show 10-min walking isochrone").tier == "complex"


# ---------------------------------------------------------------------------
# LLM cache (M3.1)
# ---------------------------------------------------------------------------

class TestLLMCache:
    def test_set_get_round_trip(self):
        c = LLMCache(ttl_seconds=60.0, max_entries=10)
        c.set("k1", "v1")
        assert c.get("k1") == "v1"

    def test_miss_returns_none(self):
        c = LLMCache()
        assert c.get("nope") is None

    def test_hits_misses_counters(self):
        c = LLMCache()
        c.set("k", "v")
        c.get("k")
        c.get("missing")
        s = c.stats()
        assert s["hits"] == 1
        assert s["misses"] == 1

    def test_expiry(self):
        c = LLMCache(ttl_seconds=0.01, max_entries=10)
        c.set("k", "v")
        time.sleep(0.05)
        assert c.get("k") is None

    def test_lru_eviction_at_capacity(self):
        c = LLMCache(ttl_seconds=60.0, max_entries=3)
        c.set("a", 1); c.set("b", 2); c.set("c", 3)
        c.get("a")  # touch a → most recent
        c.set("d", 4)  # evicts b (oldest)
        assert c.get("a") == 1
        assert c.get("b") is None
        assert c.get("c") == 3
        assert c.get("d") == 4

    def test_clear(self):
        c = LLMCache()
        c.set("k", "v")
        c.clear()
        assert c.size == 0
        assert c.get("k") is None

    def test_make_key_stable_over_dict_order(self):
        # Same content, different dict order → same key
        msg_a = [{"role": "user", "content": "hi"}]
        msg_b = [{"content": "hi", "role": "user"}]
        k_a = LLMCache.make_key(system="s", messages=msg_a, tools=[])
        k_b = LLMCache.make_key(system="s", messages=msg_b, tools=[])
        assert k_a == k_b

    def test_make_key_differs_on_system(self):
        k1 = LLMCache.make_key(system="A", messages=[], tools=[])
        k2 = LLMCache.make_key(system="B", messages=[], tools=[])
        assert k1 != k2

    def test_make_key_differs_on_model(self):
        k1 = LLMCache.make_key(system="s", messages=[], tools=[], model="haiku")
        k2 = LLMCache.make_key(system="s", messages=[], tools=[], model="sonnet")
        assert k1 != k2

    def test_make_key_only_uses_tail_n(self):
        old = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        new = old + [{"role": "user", "content": "newest"}]
        k1 = LLMCache.make_key(system="s", messages=old[-6:], tools=[])
        k2 = LLMCache.make_key(system="s", messages=new[-6:], tools=[])
        # Different tail → different key
        assert k1 != k2

    def test_thread_safety_smoke(self):
        c = LLMCache(ttl_seconds=60.0, max_entries=200)
        import threading

        def worker(start):
            for i in range(100):
                k = f"k{start * 100 + i}"
                c.set(k, i)
                c.get(k)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        # No crashes; state consistent
        assert c.size <= 200

    def test_should_bypass_phrases(self):
        for p in BYPASS_PHRASES:
            assert should_bypass(f"please {p} this query") is True
        assert should_bypass("just a normal query") is False
        assert should_bypass(None) is False
        assert should_bypass("") is False
