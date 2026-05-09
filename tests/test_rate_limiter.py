"""Direct unit tests for services/rate_limiter.py.

The module is exercised indirectly by harness/ tests, but its memory and
correctness contracts deserve direct coverage. BL1 from /critical-review:
`PerKeyRateLimiter._events` was unbounded across distinct keys; the dead
`if not history: pop()` branch never fired. Tests below pin both the
existing rate-limit contract and the new memory bound.
"""
from __future__ import annotations

import threading
import time

import pytest

from services.rate_limiter import PerKeyRateLimiter, RateLimiter


# ---------------------------------------------------------------------------
# RateLimiter (token-bucket / min-interval)
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_first_call_does_not_block(self):
        rl = RateLimiter("t1", min_interval_seconds=0.1)
        start = time.time()
        rl.wait()
        assert time.time() - start < 0.05

    def test_second_call_blocks_until_interval(self):
        rl = RateLimiter("t2", min_interval_seconds=0.1)
        rl.wait()
        start = time.time()
        rl.wait()
        elapsed = time.time() - start
        assert 0.08 <= elapsed <= 0.25, (
            f"expected ~0.1s wait, got {elapsed:.3f}s"
        )

    def test_would_wait_reflects_state(self):
        rl = RateLimiter("t3", min_interval_seconds=0.2)
        assert rl.would_wait() is False
        rl.wait()
        assert rl.would_wait() is True
        time.sleep(0.25)
        assert rl.would_wait() is False

    def test_can_proceed_alias(self):
        rl = RateLimiter("t4", min_interval_seconds=0.05)
        assert rl.can_proceed() is True
        rl.wait()
        assert rl.can_proceed() is False

    def test_thread_safety_serializes_waits(self):
        """Two threads racing must not both think they reserved the same slot.
        Both should complete; the second must have waited at least min_interval.
        """
        rl = RateLimiter("t5", min_interval_seconds=0.1)
        timestamps = []

        def _worker():
            rl.wait()
            timestamps.append(time.time())

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert len(timestamps) == 2
        timestamps.sort()
        gap = timestamps[1] - timestamps[0]
        assert gap >= 0.08, f"two waits collapsed to {gap:.3f}s — slot leak"


# ---------------------------------------------------------------------------
# PerKeyRateLimiter — BL1 regression + correctness
# ---------------------------------------------------------------------------

class TestPerKeyRateLimiter:
    def test_under_cap_allows(self):
        rl = PerKeyRateLimiter("t", max_requests=3, window_seconds=60)
        assert rl.allow("ip-A") is True
        assert rl.allow("ip-A") is True
        assert rl.allow("ip-A") is True

    def test_at_cap_blocks(self):
        rl = PerKeyRateLimiter("t", max_requests=2, window_seconds=60)
        assert rl.allow("ip-A") is True
        assert rl.allow("ip-A") is True
        assert rl.allow("ip-A") is False
        assert rl.allow("ip-A") is False

    def test_keys_are_isolated(self):
        rl = PerKeyRateLimiter("t", max_requests=1, window_seconds=60)
        assert rl.allow("ip-A") is True
        assert rl.allow("ip-A") is False
        assert rl.allow("ip-B") is True
        assert rl.allow("ip-B") is False

    def test_window_expiry_re_admits(self):
        rl = PerKeyRateLimiter("t", max_requests=1, window_seconds=1)
        assert rl.allow("ip-A") is True
        assert rl.allow("ip-A") is False
        time.sleep(1.05)
        assert rl.allow("ip-A") is True

    def test_reset_clears_single_key(self):
        rl = PerKeyRateLimiter("t", max_requests=1, window_seconds=60)
        rl.allow("ip-A")
        assert rl.allow("ip-A") is False
        rl.reset("ip-A")
        assert rl.allow("ip-A") is True

    def test_reset_clears_all(self):
        rl = PerKeyRateLimiter("t", max_requests=1, window_seconds=60)
        rl.allow("ip-A")
        rl.allow("ip-B")
        rl.reset()
        assert rl.allow("ip-A") is True
        assert rl.allow("ip-B") is True

    # --- BL1 regression: memory bound under key-rotation flood ---

    def test_memory_bounded_under_distinct_key_flood(self):
        """An attacker sending one request from each of N distinct keys
        must not be able to grow `_events` past `max_keys`. Pre-fix this
        dict was unbounded and the GC branch was dead code."""
        rl = PerKeyRateLimiter(
            "t", max_requests=1, window_seconds=60, max_keys=100,
        )
        # Hit the cap exactly.
        for i in range(100):
            assert rl.allow(f"ip-{i}") is True
        assert len(rl._events) == 100

        # Next 50 distinct keys must be refused — bucket is full and
        # nothing has expired yet, so GC can't free anything.
        for i in range(100, 150):
            assert rl.allow(f"ip-{i}") is False
        assert len(rl._events) == 100, (
            f"_events grew past max_keys={100}: now {len(rl._events)} — "
            "BL1 regression"
        )

    def test_existing_keys_keep_working_when_cap_full(self):
        """When `_events` is at the cap, already-known keys must still be
        served. Only genuinely-new keys are refused."""
        rl = PerKeyRateLimiter(
            "t", max_requests=5, window_seconds=60, max_keys=10,
        )
        for i in range(10):
            assert rl.allow(f"k-{i}") is True
        # Cap reached; new key rejected.
        assert rl.allow("k-new") is False
        # Existing key still served (under per-key limit).
        assert rl.allow("k-0") is True

    def test_gc_drops_stale_keys_after_window(self):
        """After the window expires for old keys, a sweep must drop them
        so new keys can be admitted again."""
        rl = PerKeyRateLimiter(
            "t", max_requests=1, window_seconds=1, max_keys=5,
        )
        for i in range(5):
            assert rl.allow(f"k-{i}") is True
        assert len(rl._events) == 5
        assert rl.allow("k-new") is False

        # Wait out the window.
        time.sleep(1.1)

        # Force GC by triggering the cap path again.
        # The cap-check path runs GC unconditionally before refusing.
        assert rl.allow("k-new") is True
        assert len(rl._events) <= 5
        # The previously-stale keys should be gone.
        assert "k-0" not in rl._events

    def test_periodic_gc_runs_on_interval(self):
        """The opportunistic GC kicks in every `_GC_INTERVAL` calls so
        long-lived processes don't accumulate one-shot keys forever."""
        rl = PerKeyRateLimiter(
            "t", max_requests=1, window_seconds=1, max_keys=10_000,
        )
        # Force the sweep cadence low for the test.
        rl._GC_INTERVAL = 50

        # Insert 50 keys; the 50th call triggers GC.
        for i in range(50):
            rl.allow(f"k-{i}")

        # Wait the window out so all are stale, then trigger one more
        # call to hit the GC cadence.
        time.sleep(1.1)
        for _ in range(50):
            rl.allow("trigger")
        # All the original one-shot keys should be gone after sweep.
        assert all(k not in rl._events for k in (f"k-{i}" for i in range(50)))

    def test_thread_safety_distinct_keys(self):
        """Concurrent allows on distinct keys must produce exactly one
        admit per key when max_requests=1."""
        rl = PerKeyRateLimiter("t", max_requests=1, window_seconds=60)
        results = []
        keys = [f"k-{i}" for i in range(50)]

        def _worker(k):
            results.append((k, rl.allow(k)))

        threads = [threading.Thread(target=_worker, args=(k,)) for k in keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        admits = [k for k, ok in results if ok]
        assert sorted(admits) == sorted(keys), (
            f"distinct-key admits diverged from keys: {set(keys) - set(admits)}"
        )

    def test_thread_safety_single_key_burst(self):
        """50 threads racing on one key with max_requests=10 must produce
        exactly 10 admits — no double-counting, no torn state."""
        rl = PerKeyRateLimiter("t", max_requests=10, window_seconds=60)
        results = []

        def _worker():
            results.append(rl.allow("hot-key"))

        threads = [threading.Thread(target=_worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        admits = sum(1 for r in results if r)
        assert admits == 10, (
            f"expected exactly 10 admits, got {admits} — "
            "lock did not serialize append"
        )
