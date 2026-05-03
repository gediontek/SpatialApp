"""Harness conftest — opt-in adversarial test suite.

Tests under tests/harness/ assert security/isolation contracts named in
work_plan/spatialapp/07-v2-audit-findings.md. They run with CSRF enabled
and a multi-user fixture, and are EXPECTED to fail on `main` until the
corresponding fix PR lands. Run with:

    pytest tests/harness/

Tests are auto-marked `harness`. CI gates on `pytest -m "not harness"`
until PR #11 promotes this suite.
"""
import os

# Provider keys MUST be empty during harness — N1 contamination guard.
# Set BEFORE any app import (config.py reads them at import time).
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
    if os.environ.get(_k):
        os.environ[_k] = ""

os.environ.setdefault("FLASK_DEBUG", "true")  # avoid prod-secret raise during harness boot
os.environ.setdefault("SECRET_KEY", "harness-secret-not-for-production")

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "harness: opt-in adversarial harness — expected red on main"
    )


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test in tests/harness/ with @pytest.mark.harness."""
    for item in items:
        if "tests/harness/" in str(item.fspath):
            item.add_marker(pytest.mark.harness)


# Sentinel status the harness uses to distinguish CSRF-rejection from
# other 400 responses (which app.py:180's generic handler sanitizes).
CSRF_REJECTED_STATUS = 419


@pytest.fixture
def csrf_enforced_client():
    """Flask test client with WTF_CSRF_ENABLED=True AND a CSRFError handler
    that returns a distinguishable status (419) so harness assertions can
    separate CSRF rejection from other 400s.

    Audit-required: every state-mutating route must EITHER reject as 419
    (CSRF blocked) OR be deliberately exempted via a working
    `csrf.exempt(<view_function>)` that survives Flask-WTF's actual lookup.
    """
    from app import app
    from flask_wtf.csrf import CSRFError

    prior_csrf = app.config.get("WTF_CSRF_ENABLED")
    prior_testing = app.config.get("TESTING")
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["TESTING"] = True

    # Register a CSRFError handler that bypasses app.py:180's generic 400
    # sanitizer so the harness can see WHY the request was rejected.
    @app.errorhandler(CSRFError)
    def _harness_csrf_handler(e):
        from flask import jsonify
        return jsonify(error="csrf_rejected", reason=str(e.description)), CSRF_REJECTED_STATUS

    try:
        with app.test_client() as client:
            yield client
    finally:
        app.config["WTF_CSRF_ENABLED"] = prior_csrf
        if prior_testing is not None:
            app.config["TESTING"] = prior_testing
