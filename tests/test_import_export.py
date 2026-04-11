"""Tests for import_csv, import_wkt, and export_layer handlers."""

import pytest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nl_gis.handlers import dispatch_tool


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def layer_store():
    """Layer store with a sample layer for export tests."""
    return {
        "buildings": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.0, 38.9]},
                    "properties": {"name": "Building A"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-77.1, 38.8]},
                    "properties": {"name": "Building B"},
                },
            ],
        },
        "empty_layer": {
            "type": "FeatureCollection",
            "features": [],
        },
    }


# ============================================================
# import_csv tests
# ============================================================

class TestImportCSV:
    """Tests for the import_csv tool."""

    def test_happy_path(self):
        csv_data = "name,lat,lon\nAlice,40.7,-74.0\nBob,34.0,-118.2"
        result = dispatch_tool("import_csv", {"csv_data": csv_data}, {})

        assert "error" not in result
        assert result["imported"] == 2
        assert result["layer_name"] == "csv_import"
        fc = result["geojson"]
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 2
        # Check coordinate order is [lon, lat]
        coords = fc["features"][0]["geometry"]["coordinates"]
        assert coords == [-74.0, 40.7]
        # Properties should exclude lat/lon columns
        assert "name" in fc["features"][0]["properties"]
        assert "lat" not in fc["features"][0]["properties"]

    def test_custom_columns(self):
        csv_data = "city,latitude,longitude\nNY,40.7,-74.0"
        result = dispatch_tool("import_csv", {
            "csv_data": csv_data,
            "lat_column": "latitude",
            "lon_column": "longitude",
            "layer_name": "cities",
        }, {})

        assert "error" not in result
        assert result["imported"] == 1
        assert result["layer_name"] == "cities"
        assert result["geojson"]["features"][0]["properties"]["city"] == "NY"

    def test_custom_layer_name(self):
        csv_data = "lat,lon\n1.0,2.0"
        result = dispatch_tool("import_csv", {
            "csv_data": csv_data,
            "layer_name": "my_points",
        }, {})
        assert result["layer_name"] == "my_points"

    def test_empty_csv_data(self):
        result = dispatch_tool("import_csv", {"csv_data": ""}, {})
        assert "error" in result

    def test_none_csv_data(self):
        result = dispatch_tool("import_csv", {}, {})
        assert "error" in result

    def test_missing_lat_column(self):
        csv_data = "name,longitude\nA,1.0"
        result = dispatch_tool("import_csv", {"csv_data": csv_data}, {})
        assert "error" in result
        assert "lat" in result["error"]

    def test_missing_lon_column(self):
        csv_data = "name,lat\nA,1.0"
        result = dispatch_tool("import_csv", {"csv_data": csv_data}, {})
        assert "error" in result
        assert "lon" in result["error"]

    def test_missing_custom_column(self):
        csv_data = "name,lat,lon\nA,1.0,2.0"
        result = dispatch_tool("import_csv", {
            "csv_data": csv_data,
            "lat_column": "latitude",
        }, {})
        assert "error" in result
        assert "latitude" in result["error"]

    def test_skips_invalid_rows(self):
        csv_data = "lat,lon,name\n40.7,-74.0,Good\nnot_a_number,bad,Bad\n34.0,-118.2,Also Good"
        result = dispatch_tool("import_csv", {"csv_data": csv_data}, {})
        assert "error" not in result
        assert result["imported"] == 2

    def test_all_rows_invalid(self):
        csv_data = "lat,lon\nabc,def\nxyz,123abc"
        result = dispatch_tool("import_csv", {"csv_data": csv_data}, {})
        assert "error" in result
        assert "No valid rows" in result["error"]

    def test_stores_in_layer_store(self):
        store = {}
        csv_data = "lat,lon\n1.0,2.0"
        result = dispatch_tool("import_csv", {"csv_data": csv_data}, store)
        assert "csv_import" in store
        assert store["csv_import"]["type"] == "FeatureCollection"

    def test_whitespace_only_csv(self):
        result = dispatch_tool("import_csv", {"csv_data": "   \n  "}, {})
        assert "error" in result


# ============================================================
# import_wkt tests
# ============================================================

class TestImportWKT:
    """Tests for the import_wkt tool."""

    def test_point(self):
        result = dispatch_tool("import_wkt", {"wkt": "POINT (30 10)"}, {})
        assert "error" not in result
        assert result["layer_name"] == "wkt_import"
        geom = result["geojson"]["features"][0]["geometry"]
        assert geom["type"] == "Point"
        assert list(geom["coordinates"]) == [30.0, 10.0]

    def test_polygon(self):
        result = dispatch_tool("import_wkt", {
            "wkt": "POLYGON ((30 10, 40 40, 20 40, 10 20, 30 10))",
        }, {})
        assert "error" not in result
        geom = result["geojson"]["features"][0]["geometry"]
        assert geom["type"] == "Polygon"

    def test_linestring(self):
        result = dispatch_tool("import_wkt", {
            "wkt": "LINESTRING (30 10, 10 30, 40 40)",
        }, {})
        assert "error" not in result
        geom = result["geojson"]["features"][0]["geometry"]
        assert geom["type"] == "LineString"

    def test_multipolygon(self):
        wkt = "MULTIPOLYGON (((30 20, 45 40, 10 40, 30 20)), ((15 5, 40 10, 10 20, 5 10, 15 5)))"
        result = dispatch_tool("import_wkt", {"wkt": wkt}, {})
        assert "error" not in result
        geom = result["geojson"]["features"][0]["geometry"]
        assert geom["type"] == "MultiPolygon"

    def test_custom_layer_name(self):
        result = dispatch_tool("import_wkt", {
            "wkt": "POINT (0 0)",
            "layer_name": "my_geom",
        }, {})
        assert result["layer_name"] == "my_geom"

    def test_empty_wkt(self):
        result = dispatch_tool("import_wkt", {"wkt": ""}, {})
        assert "error" in result

    def test_none_wkt(self):
        result = dispatch_tool("import_wkt", {}, {})
        assert "error" in result

    def test_invalid_wkt(self):
        result = dispatch_tool("import_wkt", {"wkt": "NOT_A_GEOMETRY (1 2 3)"}, {})
        assert "error" in result

    def test_garbage_wkt(self):
        result = dispatch_tool("import_wkt", {"wkt": "hello world"}, {})
        assert "error" in result

    def test_stores_in_layer_store(self):
        store = {}
        result = dispatch_tool("import_wkt", {"wkt": "POINT (1 2)"}, store)
        assert "wkt_import" in store
        assert len(store["wkt_import"]["features"]) == 1

    def test_empty_geometry(self):
        result = dispatch_tool("import_wkt", {"wkt": "GEOMETRYCOLLECTION EMPTY"}, {})
        assert "error" in result
        assert "empty" in result["error"].lower()


# ============================================================
# export_layer tests
# ============================================================

class TestExportLayer:
    """Tests for the export_layer tool."""

    def test_export_geojson(self, layer_store):
        result = dispatch_tool("export_layer", {
            "layer_name": "buildings",
            "format": "geojson",
        }, layer_store)

        assert "error" not in result
        assert result["success"] is True
        assert result["format"] == "geojson"
        assert result["feature_count"] == 2
        # Verify geojson_string is valid JSON
        parsed = json.loads(result["geojson_string"])
        assert parsed["type"] == "FeatureCollection"
        assert len(parsed["features"]) == 2

    def test_export_geojson_default_format(self, layer_store):
        result = dispatch_tool("export_layer", {
            "layer_name": "buildings",
        }, layer_store)
        assert "error" not in result
        assert result["format"] == "geojson"

    def test_export_shapefile(self, layer_store):
        result = dispatch_tool("export_layer", {
            "layer_name": "buildings",
            "format": "shapefile",
        }, layer_store)
        assert "error" not in result
        assert result["format"] == "shapefile"
        assert result["file_path"].endswith(".shp")
        assert os.path.exists(result["file_path"])

    def test_export_geopackage(self, layer_store):
        result = dispatch_tool("export_layer", {
            "layer_name": "buildings",
            "format": "geopackage",
        }, layer_store)
        assert "error" not in result
        assert result["format"] == "geopackage"
        assert result["file_path"].endswith(".gpkg")
        assert os.path.exists(result["file_path"])

    def test_missing_layer_name(self, layer_store):
        result = dispatch_tool("export_layer", {}, layer_store)
        assert "error" in result

    def test_nonexistent_layer(self, layer_store):
        result = dispatch_tool("export_layer", {
            "layer_name": "does_not_exist",
        }, layer_store)
        assert "error" in result

    def test_empty_layer(self, layer_store):
        result = dispatch_tool("export_layer", {
            "layer_name": "empty_layer",
        }, layer_store)
        assert "error" in result

    def test_invalid_format(self, layer_store):
        result = dispatch_tool("export_layer", {
            "layer_name": "buildings",
            "format": "csv",
        }, layer_store)
        assert "error" in result

    def test_no_layer_store(self):
        result = dispatch_tool("export_layer", {
            "layer_name": "buildings",
        }, None)
        assert "error" in result


# ============================================================
# dispatch_tool registration tests
# ============================================================

class TestDispatchRegistration:
    """Verify new tools are registered in dispatch_tool."""

    def test_import_csv_registered(self):
        """import_csv should not raise ValueError for unknown tool."""
        result = dispatch_tool("import_csv", {"csv_data": "lat,lon\n1,2"}, {})
        assert "error" not in result

    def test_import_wkt_registered(self):
        result = dispatch_tool("import_wkt", {"wkt": "POINT (0 0)"}, {})
        assert "error" not in result

    def test_export_layer_registered(self):
        store = {"x": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}}
        ]}}
        result = dispatch_tool("export_layer", {"layer_name": "x"}, store)
        assert "error" not in result


# ============================================================
# LAYER_PRODUCING_TOOLS membership
# ============================================================

class TestLayerProducingTools:
    """Verify import tools are in LAYER_PRODUCING_TOOLS and export is not."""

    def test_import_csv_is_layer_producing(self):
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        assert "import_csv" in LAYER_PRODUCING_TOOLS

    def test_import_wkt_is_layer_producing(self):
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        assert "import_wkt" in LAYER_PRODUCING_TOOLS

    def test_export_layer_is_not_layer_producing(self):
        from nl_gis.handlers import LAYER_PRODUCING_TOOLS
        assert "export_layer" not in LAYER_PRODUCING_TOOLS
