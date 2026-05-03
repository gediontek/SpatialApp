"""Harness — H2 (chat layer_store identity bug).

Contract: when ChatSession is constructed with a SHARED layer_store
(typically state.layer_store), the session's `self.layer_store` MUST be
the same object — otherwise layers added later to the shared store are
invisible to the chat session.

The audit symptom: nl_gis/chat.py:316 used `layer_store or {}`. An empty
shared OrderedDict is FALSY in Python, so the expression silently swapped
the shared store for a new private dict. Imports landed in state.layer_store
never reached chat sessions created when state.layer_store was empty.
"""
from collections import OrderedDict

from nl_gis.chat import ChatSession


def test_empty_shared_store_preserves_identity():
    """Empty OrderedDict (falsy) MUST be preserved, not swapped."""
    shared = OrderedDict()  # falsy
    s = ChatSession(layer_store=shared)
    assert s.layer_store is shared, (
        "ChatSession swapped the shared empty OrderedDict for a private "
        "dict. Audit H2: use `is not None` not `or {}`."
    )


def test_layer_added_to_shared_visible_to_session():
    """Layer added to shared store after session construction is visible."""
    shared = OrderedDict()
    s = ChatSession(layer_store=shared)
    shared['parks'] = {'type': 'FeatureCollection', 'features': []}
    assert 'parks' in s.layer_store, (
        "Session does not see layer added to shared store after construction. "
        "Identity preservation broken (audit H2)."
    )


def test_none_layer_store_uses_private_dict():
    """layer_store=None should fall back to an empty dict (not raise)."""
    s = ChatSession(layer_store=None)
    assert s.layer_store == {}
    assert isinstance(s.layer_store, dict)


def test_populated_shared_store_preserves_identity():
    """Truthy shared store also preserves identity (regression baseline)."""
    shared = OrderedDict([('roads', {'features': []})])
    s = ChatSession(layer_store=shared)
    assert s.layer_store is shared
