"""Tests for Prometheus metrics endpoint and MetricsCollector."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.metrics import MetricsCollector


# ------------------------------------------------------------------
# Unit tests: MetricsCollector
# ------------------------------------------------------------------

class TestMetricsCollector:
    def setup_method(self):
        self.m = MetricsCollector()

    def test_counter_inc_default(self):
        self.m.inc("requests")
        assert self.m.get_counter("requests") == 1

    def test_counter_inc_custom_amount(self):
        self.m.inc("requests", amount=5)
        assert self.m.get_counter("requests") == 5

    def test_counter_with_labels(self):
        self.m.inc("http_total", {"method": "GET", "status": "200"})
        self.m.inc("http_total", {"method": "POST", "status": "200"})
        assert self.m.get_counter("http_total", {"method": "GET", "status": "200"}) == 1
        assert self.m.get_counter("http_total", {"method": "POST", "status": "200"}) == 1

    def test_counter_accumulates(self):
        self.m.inc("c")
        self.m.inc("c")
        self.m.inc("c", amount=3)
        assert self.m.get_counter("c") == 5

    def test_gauge_set(self):
        self.m.set_gauge("sessions", 42)
        output = self.m.format_prometheus()
        assert "sessions 42" in output

    def test_gauge_overwrite(self):
        self.m.set_gauge("sessions", 10)
        self.m.set_gauge("sessions", 5)
        output = self.m.format_prometheus()
        assert "sessions 5" in output
        assert "sessions 10" not in output

    def test_histogram_observe(self):
        self.m.observe("duration", 1.5)
        self.m.observe("duration", 2.5)
        output = self.m.format_prometheus()
        assert "duration_count 2" in output
        assert "duration_sum 4.000" in output

    def test_format_empty(self):
        output = self.m.format_prometheus()
        assert output == "\n"

    def test_format_sorted_output(self):
        self.m.inc("z_counter")
        self.m.inc("a_counter")
        output = self.m.format_prometheus()
        lines = output.strip().split("\n")
        assert lines[0].startswith("a_counter")
        assert lines[1].startswith("z_counter")

    def test_label_key_format(self):
        self.m.inc("req", {"method": "GET", "path": "/api"})
        output = self.m.format_prometheus()
        assert 'req{method="GET",path="/api"} 1' in output

    def test_reset(self):
        self.m.inc("c")
        self.m.set_gauge("g", 1)
        self.m.observe("h", 1.0)
        self.m.reset()
        assert self.m.format_prometheus() == "\n"

    def test_get_counter_missing(self):
        assert self.m.get_counter("nonexistent") == 0


# ------------------------------------------------------------------
# Integration tests: /metrics endpoint
# ------------------------------------------------------------------

@pytest.fixture
def client():
    """Test client with metrics reset."""
    os.environ['FLASK_DEBUG'] = 'false'
    os.environ['SECRET_KEY'] = 'test-secret-key'
    os.environ.pop('CHAT_API_TOKEN', None)

    from app import app
    from services.metrics import metrics

    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False
    metrics.reset()

    with app.test_client() as c:
        yield c

    metrics.reset()


class TestMetricsEndpoint:
    def test_metrics_returns_text(self, client):
        resp = client.get('/metrics')
        assert resp.status_code == 200
        assert resp.content_type.startswith('text/plain')

    def test_metrics_contains_counters_after_request(self, client):
        # Make a request first to generate http_requests_total
        client.get('/api/health')
        resp = client.get('/metrics')
        body = resp.data.decode()
        assert 'http_requests_total' in body

    def test_metrics_gauge_sessions(self, client):
        resp = client.get('/metrics')
        body = resp.data.decode()
        assert 'active_sessions' in body

    def test_metrics_gauge_layers(self, client):
        resp = client.get('/metrics')
        body = resp.data.decode()
        assert 'active_layers' in body

    def test_metrics_endpoint_not_counted(self, client):
        """Hitting /metrics itself should not increment http_requests_total."""
        from services.metrics import metrics
        metrics.reset()
        client.get('/metrics')
        client.get('/metrics')
        assert metrics.get_counter("http_requests_total", {"method": "GET", "status": "200"}) == 0
