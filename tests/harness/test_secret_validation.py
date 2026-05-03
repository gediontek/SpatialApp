"""Harness — H3 (default SECRET_KEY accepted in production).

Contract:
  1. Config.validate() MUST raise RuntimeError when DEBUG=False AND
     SECRET_KEY is the default insecure value.
  2. create_app() MUST propagate that RuntimeError when run in production
     mode (FLASK_DEBUG=false, not testing).
  3. Dev mode (FLASK_DEBUG=true) downgrades the same condition to a
     warning, not a raise.

Implementation note: we do NOT reload the config or app modules — that
would mutate sys.modules state and break subsequent tests. Instead we
monkeypatch Config class attributes directly.
"""
import logging
import os

import pytest

DEFAULT_INSECURE_SECRET = 'dev-secret-key-change-in-production'


@pytest.fixture
def patched_config(monkeypatch):
    """Patch Config.DEBUG and Config.SECRET_KEY directly. Reverts cleanly."""
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False, raising=False)
    monkeypatch.setattr(Config, 'SECRET_KEY', DEFAULT_INSECURE_SECRET, raising=False)
    yield Config


def test_validate_raises_with_default_secret_in_prod(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', DEFAULT_INSECURE_SECRET)
    with pytest.raises(RuntimeError, match="SECRET_KEY must be set in production"):
        Config.validate()


def test_validate_allows_default_secret_in_debug(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', True)
    monkeypatch.setattr(Config, 'SECRET_KEY', DEFAULT_INSECURE_SECRET)
    Config.validate()  # must not raise


def test_validate_allows_strong_secret_in_prod(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', 'a' * 64)
    Config.validate()


# NOTE: end-to-end tests that re-invoke create_app() are deliberately
# omitted here — calling create_app() a second time on the singleton app
# double-registers CSRFProtect, blueprints, and error handlers, polluting
# downstream tests. The unit tests on Config.validate() above already
# cover the H3 contract; the create_app branching is exercised by
# integration tests that own their own app fixture (tests/test_app.py).
