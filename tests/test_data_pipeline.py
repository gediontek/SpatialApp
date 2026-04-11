"""Tests for Milestone 2: Data Pipeline & Formats.

Covers: import_kml, import_geoparquet, export_geoparquet,
        describe_layer, detect_duplicates, clean_layer.
"""

import base64
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.handlers import dispatch_tool, LAYER_PRODUCING_TOOLS


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def layer_store():
    """Layer store with sample layers."""
    return {
        "points": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]},
                    "properties": {"name": "A", "value": 10},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.1, 38.8]},
                    "properties": {"name": "B", "value": 20},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.2, 38.7]},
                    "properties": {"name": "C", "value": 30},
                },
            ],
        },
        "dirty": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]},
                    "properties": {"name": "  Alice  ", "unused": None},
                },
                {
                    "type": "Feature",
                    "geometry": None,
                    "properties": {"name": "NoGeom", "unused": None},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.1, 38.8]},
                    "properties": {"name": "Bob", "unused": None},
                },
            ],
        },
        "duplicates": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]},
                    "properties": {"id": 1},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]},
                    "properties": {"id": 2},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.5, 38.0]},
                    "properties": {"id": 3},
                },
            ],
        },
        "empty_layer": {
            "type": "FeatureCollection",
            "features": [],
        },
    }


SAMPLE_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Test</name>
    <Placemark>
      <name>Point A</name>
      <description>A test point</description>
      <Point>
        <coordinates>-77.0,38.9,0</coordinates>
      </Point>
    </Placemark>
    <Placemark>
      <name>Line B</name>
      <LineString>
        <coordinates>-77.0,38.9,0 -77.1,38.8,0 -77.2,38.7,0</coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Poly C</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>-77.0,38.9,0 -77.1,38.9,0 -77.1,38.8,0 -77.0,38.8,0 -77.0,38.9,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""

KML_NO_NS = """<?xml version="1.0" encoding="UTF-8"?>
<kml>
  <Document>
    <Placemark>
      <name>NoNS</name>
      <Point>
        <coordinates>1.0,2.0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""


# ============================================================
# import_kml tests
# ============================================================

class TestImportKML:
    """Tests for the import_kml tool."""

    def test_happy_path_all_types(self):
        result = dispatch_tool("import_kml", {"kml_data": SAMPLE_KML}, {})
        assert "error" not in result
        assert result["imported"] == 3
        assert result["layer_name"] == "kml_import"
        fc = result["geojson"]
        assert fc["type"] == "FeatureCollection"
        types = {f["geometry"]["type"] for f in fc["features"]}
        assert types == {"Point", "LineString", "Polygon"}

    def test_point_coordinates(self):
        result = dispatch_tool("import_kml", {"kml_data": SAMPLE_KML}, {})
        point_feature = [f for f in result["geojson"]["features"]
                         if f["geometry"]["type"] == "Point"][0]
        # KML uses lon,lat — should be preserved as GeoJSON [lon, lat]
        assert point_feature["geometry"]["coordinates"] == [-77.0, 38.9]

    def test_properties_extracted(self):
        result = dispatch_tool("import_kml", {"kml_data": SAMPLE_KML}, {})
        point_feature = [f for f in result["geojson"]["features"]
                         if f["geometry"]["type"] == "Point"][0]
        assert point_feature["properties"]["name"] == "Point A"
        assert point_feature["properties"]["description"] == "A test point"

    def test_custom_layer_name(self):
        result = dispatch_tool("import_kml", {
            "kml_data": SAMPLE_KML,
            "layer_name": "my_kml",
        }, {})
        assert result["layer_name"] == "my_kml"

    def test_empty_kml_data(self):
        result = dispatch_tool("import_kml", {"kml_data": ""}, {})
        assert "error" in result

    def test_none_kml_data(self):
        result = dispatch_tool("import_kml", {}, {})
        assert "error" in result

    def test_invalid_xml(self):
        result = dispatch_tool("import_kml", {"kml_data": "<not valid xml"}, {})
        assert "error" in result

    def test_no_placemarks(self):
        kml = '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document></Document></kml>'
        result = dispatch_tool("import_kml", {"kml_data": kml}, {})
        assert "error" in result
        assert "Placemark" in result["error"]

    def test_kml_no_namespace(self):
        result = dispatch_tool("import_kml", {"kml_data": KML_NO_NS}, {})
        assert "error" not in result
        assert result["imported"] == 1

    def test_stores_in_layer_store(self):
        store = {}
        dispatch_tool("import_kml", {"kml_data": SAMPLE_KML}, store)
        assert "kml_import" in store
        assert store["kml_import"]["type"] == "FeatureCollection"

    def test_polygon_with_hole(self):
        kml = """<?xml version="1.0"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Placemark>
            <Polygon>
              <outerBoundaryIs><LinearRing><coordinates>
                0,0 10,0 10,10 0,10 0,0
              </coordinates></LinearRing></outerBoundaryIs>
              <innerBoundaryIs><LinearRing><coordinates>
                2,2 8,2 8,8 2,8 2,2
              </coordinates></LinearRing></innerBoundaryIs>
            </Polygon>
          </Placemark>
        </kml>"""
        result = dispatch_tool("import_kml", {"kml_data": kml}, {})
        assert "error" not in result
        poly = result["geojson"]["features"][0]["geometry"]
        assert poly["type"] == "Polygon"
        assert len(poly["coordinates"]) == 2  # outer + inner ring


# ============================================================
# import_geoparquet / export_geoparquet tests
# ============================================================

class TestGeoParquet:
    """Tests for GeoParquet import/export round-trip."""

    def _has_pyarrow(self):
        try:
            import pyarrow  # noqa: F401
            return True
        except ImportError:
            return False

    def test_export_geoparquet(self, layer_store):
        if not self._has_pyarrow():
            pytest.skip("pyarrow not installed")
        result = dispatch_tool("export_geoparquet", {"layer_name": "points"}, layer_store)
        assert "error" not in result
        assert result["success"] is True
        assert result["feature_count"] == 3
        assert "parquet_base64" in result
        assert result["size_bytes"] > 0

    def test_export_missing_layer(self, layer_store):
        if not self._has_pyarrow():
            pytest.skip("pyarrow not installed")
        result = dispatch_tool("export_geoparquet", {"layer_name": "nope"}, layer_store)
        assert "error" in result

    def test_export_empty_layer(self, layer_store):
        if not self._has_pyarrow():
            pytest.skip("pyarrow not installed")
        result = dispatch_tool("export_geoparquet", {"layer_name": "empty_layer"}, layer_store)
        assert "error" in result

    def test_export_missing_layer_name(self):
        result = dispatch_tool("export_geoparquet", {}, {})
        assert "error" in result

    def test_roundtrip(self, layer_store):
        if not self._has_pyarrow():
            pytest.skip("pyarrow not installed")
        # Export
        export_result = dispatch_tool("export_geoparquet", {"layer_name": "points"}, layer_store)
        assert "error" not in export_result

        # Import
        import_result = dispatch_tool("import_geoparquet", {
            "parquet_data": export_result["parquet_base64"],
            "layer_name": "reimported",
        }, layer_store)
        assert "error" not in import_result
        assert import_result["imported"] == 3
        assert "reimported" in layer_store

    def test_import_empty_data(self):
        result = dispatch_tool("import_geoparquet", {"parquet_data": ""}, {})
        assert "error" in result

    def test_import_invalid_base64(self):
        if not self._has_pyarrow():
            pytest.skip("pyarrow not installed")
        result = dispatch_tool("import_geoparquet", {"parquet_data": "not-valid-b64!!!"}, {})
        assert "error" in result

    def test_import_valid_base64_but_not_parquet(self):
        if not self._has_pyarrow():
            pytest.skip("pyarrow not installed")
        data = base64.b64encode(b"this is not parquet data").decode()
        result = dispatch_tool("import_geoparquet", {"parquet_data": data}, {})
        assert "error" in result


# ============================================================
# describe_layer tests
# ============================================================

class TestDescribeLayer:
    """Tests for the describe_layer tool."""

    def test_happy_path(self, layer_store):
        result = dispatch_tool("describe_layer", {"layer_name": "points"}, layer_store)
        assert "error" not in result
        assert result["feature_count"] == 3
        assert "Point" in result["geometry_types"]
        assert result["crs"] == "EPSG:4326"
        assert result["bbox"] is not None
        assert len(result["bbox"]) == 4
        # Attribute stats
        attrs = result["attributes"]
        assert "name" in attrs
        assert "value" in attrs
        assert attrs["value"]["type"] == "numeric"
        assert attrs["value"]["min"] == 10
        assert attrs["value"]["max"] == 30
        assert attrs["value"]["mean"] == 20.0
        assert attrs["name"]["type"] == "string"

    def test_empty_layer(self, layer_store):
        result = dispatch_tool("describe_layer", {"layer_name": "empty_layer"}, layer_store)
        assert "error" not in result
        assert result["feature_count"] == 0

    def test_missing_layer(self, layer_store):
        result = dispatch_tool("describe_layer", {"layer_name": "nope"}, layer_store)
        assert "error" in result

    def test_missing_layer_name(self):
        result = dispatch_tool("describe_layer", {}, {})
        assert "error" in result

    def test_null_counts(self, layer_store):
        result = dispatch_tool("describe_layer", {"layer_name": "dirty"}, layer_store)
        attrs = result["attributes"]
        assert attrs["unused"]["null_count"] == 3
        assert attrs["unused"]["type"] == "null"


# ============================================================
# detect_duplicates tests
# ============================================================

class TestDetectDuplicates:
    """Tests for the detect_duplicates tool."""

    def test_exact_duplicates(self, layer_store):
        result = dispatch_tool("detect_duplicates", {"layer_name": "duplicates"}, layer_store)
        assert "error" not in result
        assert result["total_duplicates"] == 1
        assert len(result["duplicate_groups"]) == 1
        group = result["duplicate_groups"][0]
        assert group["duplicates"][0]["type"] == "exact"

    def test_no_duplicates(self, layer_store):
        result = dispatch_tool("detect_duplicates", {"layer_name": "points"}, layer_store)
        assert "error" not in result
        assert result["total_duplicates"] == 0

    def test_near_duplicates(self):
        store = {
            "near": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                        "properties": {},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [0.000005, 0.0]},
                        "properties": {},
                    },
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [10.0, 10.0]},
                        "properties": {},
                    },
                ],
            }
        }
        # 0.000005 degrees ~ 0.55m at equator, threshold 1m should catch it
        result = dispatch_tool("detect_duplicates", {
            "layer_name": "near",
            "threshold_m": 1,
        }, store)
        assert "error" not in result
        assert result["total_duplicates"] >= 1

    def test_missing_layer(self, layer_store):
        result = dispatch_tool("detect_duplicates", {"layer_name": "nope"}, layer_store)
        assert "error" in result

    def test_single_feature(self):
        store = {
            "one": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}},
                ],
            }
        }
        result = dispatch_tool("detect_duplicates", {"layer_name": "one"}, store)
        assert "error" not in result
        assert result["total_duplicates"] == 0


# ============================================================
# clean_layer tests
# ============================================================

class TestCleanLayer:
    """Tests for the clean_layer tool."""

    def test_removes_null_geometry(self, layer_store):
        result = dispatch_tool("clean_layer", {"layer_name": "dirty"}, layer_store)
        assert "error" not in result
        report = result["report"]
        assert report["null_geometries_removed"] == 1
        assert report["cleaned_count"] == 2

    def test_strips_whitespace(self, layer_store):
        result = dispatch_tool("clean_layer", {"layer_name": "dirty"}, layer_store)
        report = result["report"]
        assert report["whitespace_values_trimmed"] >= 1
        # Check actual value was trimmed
        cleaned = result["geojson"]["features"]
        names = [f["properties"]["name"] for f in cleaned]
        assert "Alice" in names  # was "  Alice  "

    def test_removes_all_null_attrs(self, layer_store):
        result = dispatch_tool("clean_layer", {"layer_name": "dirty"}, layer_store)
        report = result["report"]
        assert "unused" in report["all_null_attributes_removed"]
        # Verify attribute is gone from features
        for f in result["geojson"]["features"]:
            assert "unused" not in f["properties"]

    def test_custom_output_name(self, layer_store):
        result = dispatch_tool("clean_layer", {
            "layer_name": "dirty",
            "output_name": "sparkly_clean",
        }, layer_store)
        assert result["layer_name"] == "sparkly_clean"
        assert "sparkly_clean" in layer_store

    def test_default_output_name(self, layer_store):
        result = dispatch_tool("clean_layer", {"layer_name": "dirty"}, layer_store)
        assert result["layer_name"] == "dirty_cleaned"

    def test_missing_layer(self, layer_store):
        result = dispatch_tool("clean_layer", {"layer_name": "nope"}, layer_store)
        assert "error" in result

    def test_empty_layer(self, layer_store):
        result = dispatch_tool("clean_layer", {"layer_name": "empty_layer"}, layer_store)
        assert "error" in result

    def test_produces_layer(self, layer_store):
        """clean_layer result includes geojson + layer_name."""
        result = dispatch_tool("clean_layer", {"layer_name": "dirty"}, layer_store)
        assert "geojson" in result
        assert result["geojson"]["type"] == "FeatureCollection"


# ============================================================
# Dispatch + LAYER_PRODUCING_TOOLS registration
# ============================================================

class TestMilestone2Registration:
    """Verify all Milestone 2 tools are registered."""

    def test_import_kml_registered(self):
        result = dispatch_tool("import_kml", {"kml_data": SAMPLE_KML}, {})
        assert "error" not in result

    def test_describe_layer_registered(self):
        store = {"x": {"type": "FeatureCollection", "features": []}}
        result = dispatch_tool("describe_layer", {"layer_name": "x"}, store)
        assert "error" not in result

    def test_detect_duplicates_registered(self):
        store = {"x": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}},
        ]}}
        result = dispatch_tool("detect_duplicates", {"layer_name": "x"}, store)
        assert "error" not in result

    def test_clean_layer_registered(self):
        store = {"x": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}},
        ]}}
        result = dispatch_tool("clean_layer", {"layer_name": "x"}, store)
        assert "error" not in result

    def test_layer_producing_tools(self):
        assert "import_kml" in LAYER_PRODUCING_TOOLS
        assert "import_geoparquet" in LAYER_PRODUCING_TOOLS
        assert "clean_layer" in LAYER_PRODUCING_TOOLS
        # export/describe/detect are NOT layer-producing
        assert "export_geoparquet" not in LAYER_PRODUCING_TOOLS
        assert "describe_layer" not in LAYER_PRODUCING_TOOLS
        assert "detect_duplicates" not in LAYER_PRODUCING_TOOLS


# ============================================================
# Tool schema presence
# ============================================================

class TestToolSchemas:
    """Verify tool schemas exist."""

    def test_all_milestone2_tools_have_schemas(self):
        from nl_gis.tools import get_tool_definitions
        tool_names = {t["name"] for t in get_tool_definitions()}
        expected = {
            "import_kml", "import_geoparquet", "export_geoparquet",
            "describe_layer", "detect_duplicates", "clean_layer",
        }
        for name in expected:
            assert name in tool_names, f"Missing schema for {name}"
