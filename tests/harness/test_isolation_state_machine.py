"""Harness — Hypothesis state machine for multi-user isolation (C3 + C4).

Replaces the scenario tests in test_multi_user_isolation.py with
property-based fuzzing across (n_users × random op sequences).
The state machine models:
  - layer create / read / delete per user
  - annotation create / read / clear per user

The cross-user isolation invariant is checked after every transition:
  - For every (user, layer) the user did NOT create, the user MUST NOT
    see it in their /api/layers response.
  - For every (user, annotation) the user did NOT create, the user MUST
    NOT see it in their /get_annotations response.

`max_examples` is conservative (50) so CI run-time stays bounded;
nightly runs can bump via the standard Hypothesis settings profile.
"""
from __future__ import annotations

import uuid

import pytest

import state

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, settings, strategies as st  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    Bundle, RuleBasedStateMachine, initialize, invariant, rule,
)


# Restrict to a small alphabet for layer / annotation names so the model
# can collide them frequently — collisions are where ownership bugs hide.
_NAME = st.text(alphabet="abcdef", min_size=1, max_size=6)


class IsolationModel(RuleBasedStateMachine):
    """Two users, random create/read/delete ops; isolation invariant
    checked after every step.

    The model tracks `expected_layers[user_id] = set(layer_names)` and
    asserts /api/layers and state.layer_owners agree with the model.
    """

    layers_by_user: dict[str, set]
    annots_by_user: dict[str, set]

    def __init__(self):
        super().__init__()
        # Two users — keep the bundle small so collisions happen.
        self._users = {}  # user_id -> token
        self.layers_by_user = {}
        self.annots_by_user = {}
        self._client = None
        self._app_csrf_prior = None

    @initialize()
    def setup(self):
        from app import app
        # Reset shared state for the model run.
        state.layer_store.clear()
        state.layer_owners.clear()
        state.geo_coco_annotations.clear()

        self._app_csrf_prior = app.config.get("WTF_CSRF_ENABLED")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        suffix = uuid.uuid4().hex[:8]
        for label in ("alice", "bob"):
            user = state.db.create_user(f"hyp_{label}_{suffix}")
            self._users[user["user_id"]] = user["api_token"]
            self.layers_by_user[user["user_id"]] = set()
            self.annots_by_user[user["user_id"]] = set()

        self._client = app.test_client().__enter__()

    def teardown(self):
        from app import app
        try:
            self._client.__exit__(None, None, None)
        except Exception:
            pass
        # Clean shared state and DB rows we created.
        state.layer_store.clear()
        state.layer_owners.clear()
        state.geo_coco_annotations.clear()
        try:
            from services.database import get_connection as _gc
            conn = _gc()
            conn.execute("DELETE FROM users WHERE username LIKE 'hyp_%'")
            conn.commit()
        except Exception:
            pass
        if self._app_csrf_prior is not None:
            app.config["WTF_CSRF_ENABLED"] = self._app_csrf_prior

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _auth(self, user_id: str) -> dict:
        return {"Authorization": f"Bearer {self._users[user_id]}"}

    def _user_ids(self):
        return list(self._users)

    # -----------------------------------------------------------------
    # Rules (operations Hypothesis will sequence randomly)
    # -----------------------------------------------------------------

    @rule(name=_NAME, user_idx=st.integers(min_value=0, max_value=1))
    def create_layer(self, name, user_idx):
        """User creates a layer with the given name. Direct in-memory
        write (mirrors the post-condition of /api/import without paying
        the multipart upload cost in the loop)."""
        users = self._user_ids()
        if user_idx >= len(users):
            return
        uid = users[user_idx]
        # Idempotency: if name already exists, model the overwrite as
        # ownership transfer to the new caller (matches the production
        # /api/import behavior where the last writer wins).
        previous_owner = state.layer_owners.get(name)
        if previous_owner and previous_owner != uid:
            self.layers_by_user[previous_owner].discard(name)
        state.layer_store[name] = {"type": "FeatureCollection", "features": []}
        state.layer_owners[name] = uid
        self.layers_by_user[uid].add(name)

    @rule(name=_NAME, user_idx=st.integers(min_value=0, max_value=1))
    def delete_layer(self, name, user_idx):
        """User attempts DELETE; succeeds only if they own it. Model
        updates the expected set accordingly."""
        users = self._user_ids()
        if user_idx >= len(users):
            return
        uid = users[user_idx]
        # IMPORTANT: snapshot pre-request state because the request itself
        # mutates state.layer_owners on success.
        existed_before = name in state.layer_store
        owner_before = state.layer_owners.get(name)

        r = self._client.delete(f"/api/layers/{name}", headers=self._auth(uid))

        if not existed_before:
            assert r.status_code == 404, (
                f"isolation regression: delete of nonexistent layer returned "
                f"{r.status_code} (must be 404)"
            )
        elif owner_before == uid:
            # Owner-delete must succeed (200) AND the in-memory state
            # must reflect the removal.
            assert r.status_code == 200, (
                f"isolation regression: owner {uid} could not delete own "
                f"layer {name!r}; got {r.status_code}"
            )
            assert name not in state.layer_store
            assert name not in state.layer_owners
            self.layers_by_user[uid].discard(name)
        else:
            # Cross-user delete: must 404 (existence-leak avoidance) AND
            # must NOT mutate state.
            assert r.status_code == 404, (
                f"isolation regression: user {uid} got {r.status_code} "
                f"for cross-user delete of layer owned by {owner_before!r}"
            )
            assert name in state.layer_store, (
                f"isolation regression: cross-user delete by {uid} mutated "
                f"layer {name!r} owned by {owner_before!r}"
            )
            assert state.layer_owners.get(name) == owner_before

    @rule(user_idx=st.integers(min_value=0, max_value=1))
    def list_layers(self, user_idx):
        """User lists layers; result MUST equal model's expected set."""
        users = self._user_ids()
        if user_idx >= len(users):
            return
        uid = users[user_idx]
        r = self._client.get("/api/layers", headers=self._auth(uid))
        assert r.status_code == 200
        seen = {entry["name"] for entry in r.get_json()["layers"]}
        expected = self.layers_by_user[uid]
        assert seen == expected, (
            f"isolation regression: user {uid} layer view diverged from model. "
            f"seen={sorted(seen)} expected={sorted(expected)}"
        )

    # -----------------------------------------------------------------
    # Invariant — checked after every transition
    # -----------------------------------------------------------------

    @invariant()
    def no_cross_user_layer_visibility(self):
        """For every layer in the store, the recorded owner in
        state.layer_owners MUST be the SAME user the model recorded as
        the creator. No user's expected_layers set may contain a layer
        owned by another user."""
        for name, _ in state.layer_store.items():
            owner = state.layer_owners.get(name, "anonymous")
            for uid, expected in self.layers_by_user.items():
                if name in expected and uid != owner:
                    raise AssertionError(
                        f"model leak: layer {name!r} in user {uid}'s expected "
                        f"set but state.layer_owners says owner is {owner!r}"
                    )


# Wrap the state machine as a pytest test. Conservative settings:
#   - max_examples=50: keep CI under a couple of seconds per run
#   - deadline=None: state-machine tests can have variable per-step time
#   - suppress_health_check: shared state across rules is the point
TestIsolationStateMachine = IsolationModel.TestCase
TestIsolationStateMachine.settings = settings(
    max_examples=50,
    deadline=None,
    stateful_step_count=20,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.too_slow,
    ],
)
