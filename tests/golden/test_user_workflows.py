"""Golden-path workflow tests — chat → tool → render, end to end.

Each scenario mimics a basic user journey the manual tester expects to
"just work". Catches the class of regressions where the unit suite is
green but the live experience is broken (Overpass parsing drift, tool
dispatch wiring, layer_store write, GeoJSON validity for Leaflet).

Coverage matrix:
  W1 — single-tool fetch_osm:           polygons in store with valid coords
  W2 — geocode → fetch_osm chain:       both HTTP calls fire, layer renders
  W3 — empty Overpass response:         empty FeatureCollection, no error
  W4 — Overpass timeout:                error event, no layer added
  W5 — multi-feature realistic payload: all features survive the converter
  W6 — coordinate order is [lng, lat]:  guards against the lat/lon swap bug
"""
from __future__ import annotations

import json

import pytest
import requests as _requests

import state


def _post_chat(client, message):
    """POST /api/chat and return (status, parsed-sse-events)."""
    from tests.golden.conftest import parse_sse

    resp = client.post(
        "/api/chat",
        data=json.dumps({"message": message, "session_id": "golden-test"}),
        content_type="application/json",
    )
    body = resp.get_data(as_text=True)
    return resp.status_code, parse_sse(body)


def _layer_add_events(events):
    return [data for etype, data in events if etype == "layer_add"]


def _error_events(events):
    return [data for etype, data in events if etype == "error"]


def _coords_walk(geometry):
    """Yield every (lng, lat) from a GeoJSON geometry of any type."""
    coords = geometry.get("coordinates", [])
    geom_type = geometry.get("type", "")
    if geom_type == "Point":
        yield tuple(coords)
    elif geom_type in ("MultiPoint", "LineString"):
        for c in coords:
            yield tuple(c)
    elif geom_type in ("MultiLineString", "Polygon"):
        for ring in coords:
            for c in ring:
                yield tuple(c)
    elif geom_type == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for c in ring:
                    yield tuple(c)


def _assert_valid_geojson_layer(geojson, expected_min_features=1):
    """Layer-shape contract every renderable layer must satisfy."""
    assert isinstance(geojson, dict), "geojson must be a dict"
    assert geojson.get("type") == "FeatureCollection", \
        f"geojson.type must be FeatureCollection, got {geojson.get('type')!r}"
    features = geojson.get("features", [])
    assert isinstance(features, list), "features must be a list"
    assert len(features) >= expected_min_features, (
        f"expected at least {expected_min_features} feature(s), "
        f"got {len(features)}"
    )
    for i, feat in enumerate(features):
        assert feat.get("type") == "Feature", \
            f"feature[{i}] missing type=Feature"
        geom = feat.get("geometry")
        assert isinstance(geom, dict) and geom.get("type"), (
            f"feature[{i}] missing geometry — Leaflet will silently skip it. "
            "This is the bug class the user reported."
        )
        for lng, lat in _coords_walk(geom):
            assert -180.0 <= lng <= 180.0, (
                f"feature[{i}] longitude out of range: {lng}. "
                "Likely a [lat,lng] vs [lng,lat] swap."
            )
            assert -90.0 <= lat <= 90.0, (
                f"feature[{i}] latitude out of range: {lat}. "
                "Likely a [lat,lng] vs [lng,lat] swap."
            )


# ---------------------------------------------------------------------------
# Canned Overpass payloads — realistic shape from `out geom qt`
# ---------------------------------------------------------------------------

CHICAGO_PARK_POLYGON = {
    "type": "way",
    "id": 12345,
    "tags": {"leisure": "park", "name": "Grant Park"},
    "geometry": [
        {"lat": 41.8741, "lon": -87.6204},
        {"lat": 41.8741, "lon": -87.6132},
        {"lat": 41.8669, "lon": -87.6132},
        {"lat": 41.8669, "lon": -87.6204},
        {"lat": 41.8741, "lon": -87.6204},
    ],
}

CHICAGO_PARK_POLYGON_2 = {
    "type": "way",
    "id": 12346,
    "tags": {"leisure": "park", "name": "Millennium Park"},
    "geometry": [
        {"lat": 41.8830, "lon": -87.6225},
        {"lat": 41.8830, "lon": -87.6193},
        {"lat": 41.8810, "lon": -87.6193},
        {"lat": 41.8810, "lon": -87.6225},
        {"lat": 41.8830, "lon": -87.6225},
    ],
}

CHICAGO_PARK_POLYGON_3 = {
    "type": "way",
    "id": 12347,
    "tags": {"leisure": "park", "name": "Lincoln Park"},
    "geometry": [
        {"lat": 41.9214, "lon": -87.6336},
        {"lat": 41.9214, "lon": -87.6310},
        {"lat": 41.9180, "lon": -87.6310},
        {"lat": 41.9180, "lon": -87.6336},
        {"lat": 41.9214, "lon": -87.6336},
    ],
}

NOMINATIM_TIMES_SQUARE = [{
    "lat": "40.758",
    "lon": "-73.9855",
    "display_name": "Times Square, New York, NY, USA",
    "boundingbox": ["40.755", "40.762", "-73.989", "-73.982"],
}]

NOMINATIM_CHICAGO = [{
    "lat": "41.8781",
    "lon": "-87.6298",
    "display_name": "Chicago, IL, USA",
    "boundingbox": ["41.86", "41.89", "-87.65", "-87.61"],
}]


# ===========================================================================
# Workflow scenarios
# ===========================================================================

class TestSingleToolWorkflow:
    """W1 — the simplest user request that should render polygons."""

    def test_fetch_osm_renders_polygon_in_store(
        self, golden_client, scripted_llm, mock_overpass,
        tool_use, final_text,
    ):
        """User: 'show me parks in The Loop, Chicago'. The user reported
        manual tests where this class of query failed to render. This
        test asserts (a) the layer reaches state.layer_store, (b) the
        GeoJSON is shaped for Leaflet, (c) every coordinate is geographic.
        """
        scripted_llm([
            tool_use("fetch_osm", {
                "feature_type": "park",
                "category_name": "loop_parks",
                "bbox": "41.875,-87.640,41.890,-87.620",
            }),
            final_text("Found 1 park in The Loop."),
        ])
        mock_overpass({
            "overpass": {"elements": [CHICAGO_PARK_POLYGON]},
        })

        status, events = _post_chat(
            golden_client, "show me parks in The Loop, Chicago"
        )

        assert status == 200
        layer_events = _layer_add_events(events)
        assert len(layer_events) == 1, (
            f"expected exactly one layer_add event in SSE stream, "
            f"got {len(layer_events)}. Full events: "
            f"{[e for e, _ in events]}"
        )

        layer = layer_events[0]
        assert "name" in layer and "geojson" in layer
        _assert_valid_geojson_layer(layer["geojson"])

        # Server-side store must reflect the layer (frontend reads from here
        # via /api/layers on reload).
        with state.layer_lock:
            assert layer["name"] in state.layer_store
            stored = state.layer_store[layer["name"]]
        _assert_valid_geojson_layer(stored)


class TestGeocodeThenFetchChain:
    """W2 — two-tool chain. Catches the case where geocode succeeds but
    its bbox is mis-passed to fetch_osm and Overpass returns nothing."""

    def test_geocode_then_fetch_osm_renders_layer(
        self, golden_client, scripted_llm, mock_overpass,
        tool_use, final_text,
    ):
        scripted_llm([
            tool_use("geocode", {"query": "Times Square, NYC"}),
            tool_use("fetch_osm", {
                "feature_type": "restaurant",
                "category_name": "ts_restaurants",
                "bbox": "40.755,-73.989,40.762,-73.982",
            }),
            final_text("Found restaurants near Times Square."),
        ])
        mock_overpass({
            "nominatim": NOMINATIM_TIMES_SQUARE,
            "overpass": {"elements": [CHICAGO_PARK_POLYGON]},  # any valid way
        })

        status, events = _post_chat(
            golden_client, "find restaurants near Times Square"
        )

        assert status == 200
        layer_events = _layer_add_events(events)
        assert len(layer_events) >= 1, (
            "two-tool chain produced no layer — check that geocode result "
            "was passed through and fetch_osm fired"
        )
        _assert_valid_geojson_layer(layer_events[-1]["geojson"])


class TestEmptyOverpassResult:
    """W3 — Overpass returns no elements. The chat must not crash and
    the user must see a coherent response (empty layer or message)."""

    def test_empty_response_does_not_crash_or_render_garbage(
        self, golden_client, scripted_llm, mock_overpass,
        tool_use, final_text,
    ):
        scripted_llm([
            tool_use("fetch_osm", {
                "feature_type": "park",
                "category_name": "nowhere_parks",
                "bbox": "0.0,0.0,0.001,0.001",  # middle of the ocean
            }),
            final_text("No parks found in that area."),
        ])
        mock_overpass({"overpass": {"elements": []}})

        status, events = _post_chat(golden_client, "show parks in null island")
        assert status == 200

        # No error events should have been emitted.
        errors = _error_events(events)
        assert errors == [], (
            f"empty result should not yield an error event; got {errors}"
        )

        # Layer (if added) must be a well-formed empty FeatureCollection.
        layer_events = _layer_add_events(events)
        for layer in layer_events:
            geojson = layer["geojson"]
            assert geojson.get("type") == "FeatureCollection"
            assert geojson.get("features") == [], (
                "empty Overpass payload produced phantom features — "
                "the converter is fabricating geometry"
            )


class TestOverpassTimeoutSurfacesError:
    """W4 — Overpass times out. The chat stream must surface a friendly
    error event and must not write a partial/bogus layer."""

    def test_overpass_timeout_yields_error_no_layer(
        self, golden_client, scripted_llm, mock_overpass,
        tool_use, final_text,
    ):
        scripted_llm([
            tool_use("fetch_osm", {
                "feature_type": "building",
                "category_name": "test",
                "bbox": "41.0,-87.0,42.0,-86.0",
            }),
            final_text("OSM was slow; try a smaller area."),
        ])
        mock_overpass({"overpass": _requests.Timeout("simulated timeout")})

        status, events = _post_chat(golden_client, "show all buildings")
        assert status == 200

        # Tool result must contain the error string the handler returns
        # (the chat loop surfaces this as a tool_result, not necessarily
        # an `error` SSE event — both are acceptable, but neither path
        # may write a layer).
        layer_events = _layer_add_events(events)
        assert layer_events == [], (
            f"timeout produced a layer_add — partial state leaked. "
            f"Layers: {[l.get('name') for l in layer_events]}"
        )
        # And nothing landed in the store.
        with state.layer_lock:
            assert not state.layer_store, (
                f"layer_store mutated despite Overpass timeout: "
                f"{list(state.layer_store)}"
            )


class TestMultiFeaturePayload:
    """W5 — realistic multi-feature payload. Every way must survive the
    OSM → GeoJSON converter and reach Leaflet as a renderable polygon."""

    def test_three_polygon_payload_survives_converter(
        self, golden_client, scripted_llm, mock_overpass,
        tool_use, final_text,
    ):
        scripted_llm([
            tool_use("fetch_osm", {
                "feature_type": "park",
                "category_name": "chi_parks_3",
                "bbox": "41.86,-87.65,41.93,-87.61",
            }),
            final_text("Found 3 Chicago parks."),
        ])
        mock_overpass({
            "overpass": {
                "elements": [
                    CHICAGO_PARK_POLYGON,
                    CHICAGO_PARK_POLYGON_2,
                    CHICAGO_PARK_POLYGON_3,
                ]
            }
        })

        status, events = _post_chat(golden_client, "show all Chicago parks")
        assert status == 200

        layer_events = _layer_add_events(events)
        assert len(layer_events) == 1
        _assert_valid_geojson_layer(layer_events[0]["geojson"],
                                    expected_min_features=3)

        # Each feature must be a closed polygon — Leaflet silently skips
        # unclosed rings, which is exactly the "no polygons appear" symptom.
        features = layer_events[0]["geojson"]["features"]
        for i, feat in enumerate(features):
            ring = feat["geometry"]["coordinates"][0]
            assert ring[0] == ring[-1], (
                f"feature[{i}] polygon ring not closed; Leaflet will skip it"
            )


class TestCoordinateOrderInvariant:
    """W6 — explicit guard against the lat/lon swap bug. ValidatedPoint
    is used in the GIS layer; this test asserts the GeoJSON that reaches
    the SSE stream actually obeys the [lng, lat] convention so the
    frontend can hand it to L.geoJSON without manual swapping."""

    def test_polygon_coordinates_are_lng_lat_not_lat_lng(
        self, golden_client, scripted_llm, mock_overpass,
        tool_use, final_text,
    ):
        scripted_llm([
            tool_use("fetch_osm", {
                "feature_type": "park",
                "category_name": "swap_check",
                "bbox": "41.86,-87.65,41.89,-87.61",
            }),
            final_text("ok"),
        ])
        mock_overpass({
            "overpass": {"elements": [CHICAGO_PARK_POLYGON]},
        })

        status, events = _post_chat(golden_client, "render parks for swap test")
        assert status == 200

        layer = _layer_add_events(events)[0]["geojson"]
        ring = layer["features"][0]["geometry"]["coordinates"][0]
        # Chicago: longitude ≈ -87, latitude ≈ +41. If swapped, lng would
        # be +41 (within bounds but very wrong) — so we also assert sign +
        # rough range, not just bounds.
        sample_lng, sample_lat = ring[0]
        assert sample_lng < 0, (
            f"longitude should be negative for Chicago, got {sample_lng}. "
            "Almost certainly a lat/lon swap."
        )
        assert sample_lat > 0, (
            f"latitude should be positive for Chicago, got {sample_lat}."
        )
        assert -90 <= sample_lng <= -80, (
            f"longitude {sample_lng} outside Chicago's expected range "
            "(-90, -80) — coordinate order is wrong."
        )
        assert 40 <= sample_lat <= 45, (
            f"latitude {sample_lat} outside Chicago's expected range "
            "(40, 45) — coordinate order is wrong."
        )
