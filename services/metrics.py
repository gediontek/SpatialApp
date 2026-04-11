"""Simple Prometheus-compatible metrics collector.

Thread-safe counters, gauges, and histograms with Prometheus text
exposition format output.  No external dependencies required.
"""

import threading


class MetricsCollector:
    """Collects counters, gauges, and histogram observations.

    All methods are thread-safe via a single lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {}   # key -> numeric value
        self._histograms = {}  # key -> list of observed values
        self._gauges = {}     # key -> numeric value

    def inc(self, name, labels=None, amount=1):
        """Increment a counter by *amount* (default 1)."""
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount

    def observe(self, name, value, labels=None):
        """Record a histogram observation."""
        key = self._key(name, labels)
        with self._lock:
            if key not in self._histograms:
                self._histograms[key] = []
            self._histograms[key].append(value)

    def set_gauge(self, name, value, labels=None):
        """Set a gauge to an absolute value."""
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = value

    def get_counter(self, name, labels=None):
        """Return current value of a counter (0 if not set)."""
        key = self._key(name, labels)
        with self._lock:
            return self._counters.get(key, 0)

    def format_prometheus(self):
        """Return metrics in Prometheus text exposition format."""
        lines = []
        with self._lock:
            for key, val in sorted(self._counters.items()):
                lines.append(f"{key} {val}")
            for key, val in sorted(self._gauges.items()):
                lines.append(f"{key} {val}")
            for key, values in sorted(self._histograms.items()):
                if values:
                    lines.append(f"{key}_count {len(values)}")
                    lines.append(f"{key}_sum {sum(values):.3f}")
        return "\n".join(lines) + "\n"

    def reset(self):
        """Clear all metrics. Intended for testing."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()

    @staticmethod
    def _key(name, labels):
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Module-level singleton
metrics = MetricsCollector()
