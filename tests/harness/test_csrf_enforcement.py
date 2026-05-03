"""Harness — C2 (Flask-WTF CSRF exemptions broken) + X1 (CSRF disabled in fixtures).

Contract under test:
  Every state-mutating route MUST EITHER
    (a) reject requests without a CSRF token via Flask-WTF (HTTP 419 in the
        harness — distinguished from other 400s by conftest's CSRFError
        handler), OR
    (b) be deliberately exempted via a `csrf.exempt(<view_function>)` call
        that survives Flask-WTF's actual lookup mechanism.

Bug evidence (gathered during PR #0 spike, 2026-05-03):

  Flask-WTF source (flask_wtf/csrf.py:302-311) builds the lookup key as:
      dest = f"{view.__module__}.{view.__name__}"
  e.g.  "blueprints.auth.api_register"

  app.py:170-175 calls:
      csrf.exempt(auth_bp.name + '.api_register')
  which adds:  "auth.api_register"  (endpoint string)

  These do not intersect. Live trace on /api/register confirmed:
      endpoint='auth.api_register'
      module_dest='blueprints.auth.api_register'
      exempt_set_has_dest=False   ← Flask-WTF checks this
      exempt_set_has_endpoint=True
  → CSRFError raised → 400 (sanitized to "Bad request" by app.py:180).

Expected harness state on `main`:
  All 7 intended-exempt routes return 419 (BROKEN — exemption did not match).
  Test fails with a precise diff naming each broken endpoint.
"""
import pytest

from tests.harness.conftest import CSRF_REJECTED_STATUS


# Routes app.py:170-175 INTENDS to exempt. After the C2 fix, these MUST
# return any status OTHER than CSRF_REJECTED_STATUS.
INTENDED_EXEMPT_ENDPOINTS = {
    "osm.api_auto_classify",
    "chat.api_chat",
    "layers.api_import_layer",
    "layers.api_delete_layer",
    "auth.api_register",
    "dashboard.api_delete_session",
    "collab.api_collab_create",
}


def _state_mutating_rules(app):
    """Yield (rule.rule, methods, endpoint) for every state-mutating route."""
    for rule in app.url_map.iter_rules():
        methods = (rule.methods or set()) - {"GET", "HEAD", "OPTIONS"}
        if methods:
            yield rule.rule, sorted(methods), rule.endpoint


def _fill_path_params(rule_path: str) -> str:
    """Replace <name> placeholders with safe stub values."""
    import re

    def sub(m):
        spec = m.group(1)
        return "1" if spec.startswith(("int:", "float:")) else "harness-test-stub"

    return re.sub(r"<([^>]+)>", sub, rule_path)


def _enforcement_matrix(client, app):
    """Return per-route observation row: status, intended_exempt, was_csrf_rejected."""
    rows = []
    for rule_path, methods, endpoint in _state_mutating_rules(app):
        url = _fill_path_params(rule_path)
        for method in methods:
            resp = client.open(
                url,
                method=method,
                json={},
                headers={"Content-Type": "application/json"},
            )
            rows.append(
                {
                    "endpoint": endpoint,
                    "method": method,
                    "url": url,
                    "status": resp.status_code,
                    "intended_exempt": endpoint in INTENDED_EXEMPT_ENDPOINTS,
                    "was_csrf_rejected": resp.status_code == CSRF_REJECTED_STATUS,
                }
            )
    return rows


def test_csrf_enforced_on_every_state_mutating_route(csrf_enforced_client, capsys):
    """RED on main when C2 is unfixed:
      - 7 intended-exempt routes ALL return 419 (BROKEN exemption — bug).
      - 8 non-exempt routes return 419 (correct — CSRF enforced).

    After C2 fix lands:
      - Intended-exempt routes: status != 419 (any other code OK).
      - Non-exempt routes: status == 419.
    """
    from app import app

    rows = _enforcement_matrix(csrf_enforced_client, app)

    # Print full matrix (visible in pytest -s output, captured otherwise)
    print("\n=== CSRF enforcement matrix (WTF_CSRF_ENABLED=True) ===")
    print(f"{'endpoint':<45} {'method':<7} {'status':<7} {'exempt?':<8} {'csrf_rej?':<10}")
    for r in rows:
        print(
            f"{r['endpoint']:<45} {r['method']:<7} {r['status']:<7} "
            f"{str(r['intended_exempt']):<8} {str(r['was_csrf_rejected']):<10}"
        )

    broken_exemptions = [
        r for r in rows if r["intended_exempt"] and r["was_csrf_rejected"]
    ]
    unenforced_non_exempt = [
        r for r in rows if not r["intended_exempt"] and not r["was_csrf_rejected"]
    ]

    print(
        f"\n=== Verdict ===\n"
        f"  total state-mutating routes:                          {len(rows)}\n"
        f"  broken_exemptions (intended-exempt but CSRF-blocked): {len(broken_exemptions)}\n"
        f"  unenforced_non_exempt (non-exempt but not CSRF-blocked): {len(unenforced_non_exempt)}\n"
    )
    for r in broken_exemptions:
        print(f"  BROKEN_EXEMPT: {r['method']} {r['url']} -> 419 (csrf rejected)")
    for r in unenforced_non_exempt:
        print(f"  UNENFORCED:    {r['method']} {r['url']} -> {r['status']}")

    assert not broken_exemptions, (
        f"C2 audit finding confirmed: {len(broken_exemptions)} intended-exempt "
        "endpoint(s) still rejected by CSRF. Root cause: app.py:170-175 "
        "passes endpoint strings ('chat.api_chat') to csrf.exempt(), but "
        "Flask-WTF compares against view.__module__+view.__name__ "
        "('blueprints.chat.api_chat'). Fix: pass the view function object "
        "instead of the string, e.g. `csrf.exempt(api_chat)` after import."
    )
    assert not unenforced_non_exempt, (
        f"Baseline failure: {len(unenforced_non_exempt)} state-mutating route(s) "
        "are not in INTENDED_EXEMPT_ENDPOINTS yet do not get CSRF-blocked. "
        "Either CSRF middleware is not wired or these endpoints should be "
        "added to the intended-exempt set with explicit rationale."
    )
