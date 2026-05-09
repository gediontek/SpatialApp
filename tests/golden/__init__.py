"""Golden-path workflow tests — user experience, not units.

Each test in this package mimics a real user journey:
    chat NL → LLM tool dispatch → Overpass/Nominatim fetch
        → GeoJSON layer creation → server-side layer_store write
        → SSE event stream the frontend would render.

LLM provider and external HTTP calls are mocked for deterministic CI.
The browser-render leg is covered by tests/test_golden_path.py
(Playwright, gated by SPATIALAPP_GOLDEN_LIVE for the live polygon paint).

Run: `pytest tests/golden/ -v` or `make golden`.
"""
