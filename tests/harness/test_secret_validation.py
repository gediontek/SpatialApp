"""Harness — H3 (default SECRET_KEY accepted in production) +
N35 (placeholder SECURITY_CONTACT) + N37 (folder writability) prod gates.

Contract:
  1. Config.validate() MUST raise RuntimeError when DEBUG=False AND
     SECRET_KEY is the default insecure value.
  2. create_app() MUST propagate that RuntimeError when run in production
     mode (FLASK_DEBUG=false, not testing).
  3. Dev mode (FLASK_DEBUG=true) downgrades the same condition to a
     warning, not a raise.
  4. (N35) Config.validate() MUST raise when DEBUG=False AND
     SECURITY_CONTACT is one of the placeholder defaults.
  5. (N37) Config.validate() MUST raise when DEBUG=False AND any of
     UPLOAD_FOLDER / LABELS_FOLDER / LOG_FOLDER is unwritable.

Implementation note: we do NOT reload the config or app modules — that
would mutate sys.modules state and break subsequent tests. Instead we
monkeypatch Config class attributes directly.
"""
import logging
import os
import tempfile

import pytest

DEFAULT_INSECURE_SECRET = 'dev-secret-key-change-in-production'
PLACEHOLDER_CONTACT = 'mailto:security@example.com'
REAL_CONTACT = 'mailto:security@spatialapp-test.example'


@pytest.fixture
def writable_folders(monkeypatch, tmp_path):
    """Point Config's three writable folders at tmp_path subdirs that
    actually exist + are writable. Lets the N37 folder probe succeed
    without touching the real on-disk dirs the dev environment uses."""
    from config import Config
    up = tmp_path / "up"; lb = tmp_path / "lb"; lg = tmp_path / "lg"
    up.mkdir(); lb.mkdir(); lg.mkdir()
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', str(up))
    monkeypatch.setattr(Config, 'LABELS_FOLDER', str(lb))
    monkeypatch.setattr(Config, 'LOG_FOLDER', str(lg))
    return tmp_path


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


def test_validate_allows_strong_secret_in_prod(monkeypatch, writable_folders):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', 'a' * 64)
    monkeypatch.setattr(Config, 'SECURITY_CONTACT', REAL_CONTACT)
    Config.validate()


# ---------------------------------------------------------------------------
# N35 — placeholder SECURITY_CONTACT must be rejected in prod.
#
# The /.well-known/security.txt route publishes whatever Config.SECURITY_CONTACT
# resolves to. Shipping the unconfigured default would advertise a dead inbox
# to any researcher attempting responsible disclosure. The pre-deploy doc's
# F1 already calls this out as deploy-blocking; N35 makes it an actual code
# gate so an operator can't ship past it.
# ---------------------------------------------------------------------------

def test_n35_validate_rejects_placeholder_security_contact_in_prod(
    monkeypatch, writable_folders,
):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', 'a' * 64)
    monkeypatch.setattr(Config, 'SECURITY_CONTACT', PLACEHOLDER_CONTACT)
    with pytest.raises(RuntimeError, match="SECURITY_CONTACT must be set in production"):
        Config.validate()


@pytest.mark.parametrize("placeholder", [
    "mailto:security@example.com",
    "mailto:security@example.org",
    "mailto:placeholder@example.com",
    "",
    "TODO",
    "CHANGEME",
])
def test_n35_validate_rejects_each_known_placeholder(
    monkeypatch, writable_folders, placeholder,
):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', 'a' * 64)
    monkeypatch.setattr(Config, 'SECURITY_CONTACT', placeholder)
    with pytest.raises(RuntimeError, match="SECURITY_CONTACT"):
        Config.validate()


def test_n35_validate_allows_real_security_contact_in_prod(
    monkeypatch, writable_folders,
):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', 'a' * 64)
    monkeypatch.setattr(Config, 'SECURITY_CONTACT', REAL_CONTACT)
    Config.validate()  # must not raise


def test_n35_validate_allows_placeholder_security_contact_in_debug(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', True)
    monkeypatch.setattr(Config, 'SECURITY_CONTACT', PLACEHOLDER_CONTACT)
    Config.validate()  # dev mode unaffected


# ---------------------------------------------------------------------------
# N37 — folder writability must be probed at startup in prod.
#
# Without this, a deploy with bad permissions on UPLOAD_FOLDER /
# LABELS_FOLDER / LOG_FOLDER starts cleanly but throws opaque 500s on
# the first user upload. The probe surfaces the failure at startup so
# the operator sees the root cause instead of a downstream symptom.
# ---------------------------------------------------------------------------

def test_n37_validate_passes_with_writable_folders_in_prod(
    monkeypatch, writable_folders,
):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', 'a' * 64)
    monkeypatch.setattr(Config, 'SECURITY_CONTACT', REAL_CONTACT)
    Config.validate()  # writable_folders fixture ensures all three exist + writable


def test_n37_validate_rejects_unwritable_upload_folder_in_prod(
    monkeypatch, writable_folders, tmp_path,
):
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', False)
    monkeypatch.setattr(Config, 'SECRET_KEY', 'a' * 64)
    monkeypatch.setattr(Config, 'SECURITY_CONTACT', REAL_CONTACT)
    # Point UPLOAD_FOLDER at a path inside a read-only parent so the
    # makedirs+probe inside Config.validate fails. /proc is reliably
    # un-writable on Linux; on macOS we use a non-existent root path
    # that can't be created. The probe must surface as RuntimeError.
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', '/proc/spatialapp_n37_probe')
    with pytest.raises(RuntimeError, match="UPLOAD_FOLDER"):
        Config.validate()


def test_n37_validate_skipped_in_debug(monkeypatch):
    """Debug mode must NOT run the folder probe — dev sandboxes routinely
    have unmaterialized folders, and forcing makedirs at every Config
    init would break the test suite + ad-hoc REPL imports."""
    from config import Config
    monkeypatch.setattr(Config, 'DEBUG', True)
    # Set folders to a clearly-bad path; probe should be skipped entirely.
    monkeypatch.setattr(Config, 'UPLOAD_FOLDER', '/proc/spatialapp_n37_debug')
    Config.validate()  # must not raise — debug skips the probe


# NOTE: end-to-end tests that re-invoke create_app() are deliberately
# omitted here — calling create_app() a second time on the singleton app
# double-registers CSRFProtect, blueprints, and error handlers, polluting
# downstream tests. The unit tests on Config.validate() above already
# cover the H3 contract; the create_app branching is exercised by
# integration tests that own their own app fixture (tests/test_app.py).
