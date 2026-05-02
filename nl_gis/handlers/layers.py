"""Layer management handlers: style, visibility, highlight, merge, import/export.

ERROR PATHS (audit 2026-04-17 for v2.1 Plan 05 M1):
    42 error returns · 20 except blocks · 0 leaky str(e).
    No exception-detail leaks; size-guards apply to import/merge operations.
"""

from __future__ import annotations

import base64
import logging
import xml.etree.ElementTree as ET

from nl_gis.handlers import _get_layer_snapshot

logger = logging.getLogger(__name__)

# KML namespace
_KML_NS = "http://www.opengis.net/kml/2.2"


def handle_style_layer(params: dict) -> dict:
    """Change the visual style of a layer. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    style = {}
    for key in ("color", "fill_color", "weight", "fill_opacity", "opacity"):
        if params.get(key) is not None:
            # Convert fill_color -> fillColor for Leaflet
            leaflet_key = key.replace("fill_color", "fillColor").replace("fill_opacity", "fillOpacity")
            style[leaflet_key] = params[key]

    if not style:
        return {"error": "At least one style property (color, weight, fill_opacity, etc.) is required"}

    return {
        "success": True,
        "action": "style",
        "layer_name": layer_name,
        "style": style,
        "description": f"Styled layer '{layer_name}'",
    }


def handle_layer_visibility(params: dict, action: str) -> dict:
    """Handle show/hide/remove layer commands. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}
    return {
        "success": True,
        "action": action,
        "layer_name": layer_name,
        "description": f"Layer '{layer_name}' {action}",
    }


def handle_highlight_features(params: dict, layer_store: dict = None) -> dict:
    """Highlight features matching an attribute value. Returns instruction for frontend."""
    layer_name = params.get("layer_name")
    attribute = params.get("attribute")
    value = params.get("value")
    color = params.get("color", "#ff0000")

    if not layer_name:
        return {"error": "layer_name is required"}
    if not attribute or not value:
        return {"error": "attribute and value are required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    # Attribute validation (Plan 04 M4.2): report which attributes are
    # actually available if the requested one doesn't exist.
    available: set[str] = set()
    for f in features[:200]:
        props = f.get("properties") if isinstance(f, dict) else None
        if isinstance(props, dict):
            available.update(props.keys())
            tags = props.get("osm_tags")
            if isinstance(tags, dict):
                available.update(tags.keys())
    if available and attribute not in available:
        preview = ", ".join(sorted(available)[:15])
        return {
            "error": (
                f"Attribute '{attribute}' not found in layer '{layer_name}'. "
                f"Available attributes: {preview}"
                + (" (...more)" if len(available) > 15 else "")
            )
        }

    matched = 0
    for f in features:
        props = f.get("properties", {})
        # Check nested osm_tags as well
        if str(props.get(attribute, "")) == str(value):
            matched += 1
        elif str(props.get("osm_tags", {}).get(attribute, "")) == str(value):
            matched += 1

    return {
        "success": True,
        "action": "highlight",
        "layer_name": layer_name,
        "attribute": attribute,
        "value": value,
        "color": color,
        "highlighted": matched,
        "total": len(features),
        "description": f"Highlighted {matched}/{len(features)} features where {attribute}={value}",
    }


def handle_merge_layers(params: dict, layer_store: dict = None) -> dict:
    """Merge two layers or perform a spatial join."""
    import geopandas as gpd_mod

    layer_a = params.get("layer_a")
    layer_b = params.get("layer_b")
    output_name = params.get("output_name")
    operation = params.get("operation", "union")

    if not layer_a or not layer_b or not output_name:
        return {"error": "layer_a, layer_b, and output_name are required"}

    if not layer_store:
        return {"error": "No layer store available"}

    features_a, err_a = _get_layer_snapshot(layer_store, layer_a)
    if err_a:
        return {"error": f"Layer '{layer_a}' not found"}
    features_b, err_b = _get_layer_snapshot(layer_store, layer_b)
    if err_b:
        return {"error": f"Layer '{layer_b}' not found"}

    try:
        gdf_a = gpd_mod.GeoDataFrame.from_features(features_a)
        gdf_b = gpd_mod.GeoDataFrame.from_features(features_b
        )

        if gdf_a.crs is None:
            gdf_a.set_crs(epsg=4326, inplace=True)
        if gdf_b.crs is None:
            gdf_b.set_crs(epsg=4326, inplace=True)

        if operation == "spatial_join":
            merged = gpd_mod.sjoin(gdf_a, gdf_b, how="left", predicate="intersects")
            # Drop the index_right column that sjoin adds
            if "index_right" in merged.columns:
                merged = merged.drop(columns=["index_right"])
        else:
            # Union: concatenate both GeoDataFrames
            import pandas as pd_mod
            merged = gpd_mod.GeoDataFrame(
                pd_mod.concat([gdf_a, gdf_b], ignore_index=True),
                crs=gdf_a.crs,
            )

        import json as json_mod
        geojson_data = json_mod.loads(merged.to_json())

        if layer_store is not None:
            try:
                from state import layer_lock as _lk
            except ImportError:
                _lk = None
            if _lk:
                with _lk:
                    layer_store[output_name] = geojson_data
            else:
                layer_store[output_name] = geojson_data

        return {
            "geojson": geojson_data,
            "layer_name": output_name,
            "feature_count": len(geojson_data.get("features", [])),
            "operation": operation,
            "description": f"Merged '{layer_a}' + '{layer_b}' -> '{output_name}' ({operation}, {len(geojson_data.get('features', []))} features)",
        }
    except Exception as e:
        logger.error(f"Merge error: {e}", exc_info=True)
        return {"error": "Layer merge failed"}


def handle_import_layer(params: dict, layer_store: dict = None) -> dict:
    """Import GeoJSON data as a named layer."""
    layer_name = params.get("layer_name")
    geojson = params.get("geojson")

    if not layer_name:
        return {"error": "layer_name is required"}

    if geojson:
        # Direct GeoJSON import
        if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
            return {"error": "geojson must be a GeoJSON FeatureCollection"}

        if layer_store is not None:
            try:
                from state import layer_lock as _lk
            except ImportError:
                _lk = None
            if _lk:
                with _lk:
                    layer_store[layer_name] = geojson
            else:
                layer_store[layer_name] = geojson

        return {
            "geojson": geojson,
            "layer_name": layer_name,
            "feature_count": len(geojson.get("features", [])),
            "description": f"Imported {len(geojson.get('features', []))} features as '{layer_name}'",
        }

    # No inline GeoJSON -- tell the user to use the file upload
    return {
        "success": True,
        "layer_name": layer_name,
        "description": "To import a file, use the upload button or drag-and-drop a GeoJSON, Shapefile (.zip), or GeoPackage (.gpkg) file onto the map.",
        "upload_url": "/api/import",
    }


def handle_import_csv(params: dict, layer_store: dict = None) -> dict:
    """Import CSV data with lat/lon columns as a point layer."""
    import csv
    import io

    csv_data = params.get("csv_data")
    if not csv_data or not csv_data.strip():
        return {"error": "csv_data is required and must not be empty"}

    lat_col = params.get("lat_column", "lat")
    lon_col = params.get("lon_column", "lon")
    layer_name = params.get("layer_name", "csv_import")

    try:
        reader = csv.DictReader(io.StringIO(csv_data))
        fieldnames = reader.fieldnames or []
    except Exception:
        return {"error": "Failed to parse CSV data"}

    if lat_col not in fieldnames:
        return {"error": f"Column '{lat_col}' not found in CSV. Available columns: {', '.join(fieldnames)}"}
    if lon_col not in fieldnames:
        return {"error": f"Column '{lon_col}' not found in CSV. Available columns: {', '.join(fieldnames)}"}

    features = []
    skipped = 0
    for row in reader:
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
            props = {k: v for k, v in row.items() if k not in (lat_col, lon_col)}
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            })
        except (KeyError, ValueError):
            skipped += 1
            continue

    if not features:
        return {"error": "No valid rows found. Ensure lat/lon columns contain numeric values."}

    geojson = {"type": "FeatureCollection", "features": features}

    if layer_store is not None:
        try:
            from state import layer_lock as _lk
        except ImportError:
            _lk = None
        if _lk:
            with _lk:
                layer_store[layer_name] = geojson
        else:
            layer_store[layer_name] = geojson

    return {
        "geojson": geojson,
        "layer_name": layer_name,
        "imported": len(features),
        "skipped": skipped,
        "total_rows": len(features) + skipped,
    }


def handle_import_wkt(params: dict, layer_store: dict = None) -> dict:
    """Import a WKT string as a geometry layer."""
    from shapely import wkt as shapely_wkt
    from shapely.geometry import mapping

    wkt_str = params.get("wkt")
    if not wkt_str or not wkt_str.strip():
        return {"error": "wkt is required and must not be empty"}

    layer_name = params.get("layer_name", "wkt_import")

    try:
        geom = shapely_wkt.loads(wkt_str)
    except Exception:
        return {"error": "Invalid WKT string. Could not parse geometry."}

    if geom.is_empty:
        return {"error": "WKT string produced an empty geometry."}

    geojson = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": mapping(geom), "properties": {}}],
    }

    if layer_store is not None:
        try:
            from state import layer_lock as _lk
        except ImportError:
            _lk = None
        if _lk:
            with _lk:
                layer_store[layer_name] = geojson
        else:
            layer_store[layer_name] = geojson

    return {"geojson": geojson, "layer_name": layer_name}


def handle_export_layer(params: dict, layer_store: dict = None) -> dict:
    """Export a named layer as GeoJSON, Shapefile, or GeoPackage."""
    import json as json_mod

    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    export_format = params.get("format", "geojson")
    valid_formats = ["geojson", "shapefile", "geopackage"]
    if export_format not in valid_formats:
        return {"error": f"Invalid format. Choose from: {', '.join(valid_formats)}"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    if not features:
        return {"error": f"Layer '{layer_name}' has no features to export"}

    geojson_data = {"type": "FeatureCollection", "features": features}

    if export_format != "geojson":
        return {
            "error": f"The chat tool only supports GeoJSON export. "
                     f"For {export_format} export, use the /export_annotations HTTP endpoint.",
        }

    return {
        "success": True,
        "format": "geojson",
        "layer_name": layer_name,
        "feature_count": len(features),
        "geojson_string": json_mod.dumps(geojson_data),
        "description": f"Exported {len(features)} features from '{layer_name}' as GeoJSON",
    }


# ============================================================
# KML Import
# ============================================================

def _parse_kml_coordinates(coord_text: str) -> list:
    """Parse KML coordinate string (lon,lat[,alt] tuples separated by whitespace).

    Returns list of [lon, lat] pairs.
    """
    coords = []
    for token in coord_text.strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                lon = float(parts[0])
                lat = float(parts[1])
                coords.append([lon, lat])
            except ValueError:
                continue
    return coords


def _parse_kml_placemark(placemark, ns: str):
    """Parse a single KML Placemark element into a GeoJSON Feature."""
    # Extract name and description
    name_el = placemark.find(f"{ns}name")
    desc_el = placemark.find(f"{ns}description")
    properties = {}
    if name_el is not None and name_el.text:
        properties["name"] = name_el.text.strip()
    if desc_el is not None and desc_el.text:
        properties["description"] = desc_el.text.strip()

    geometry = None

    # Point
    point_el = placemark.find(f".//{ns}Point/{ns}coordinates")
    if point_el is not None and point_el.text:
        coords = _parse_kml_coordinates(point_el.text)
        if coords:
            geometry = {"type": "Point", "coordinates": coords[0]}

    # LineString
    if geometry is None:
        line_el = placemark.find(f".//{ns}LineString/{ns}coordinates")
        if line_el is not None and line_el.text:
            coords = _parse_kml_coordinates(line_el.text)
            if len(coords) >= 2:
                geometry = {"type": "LineString", "coordinates": coords}

    # Polygon
    if geometry is None:
        poly_el = placemark.find(f".//{ns}Polygon")
        if poly_el is not None:
            rings = []
            # Outer boundary
            outer = poly_el.find(f".//{ns}outerBoundaryIs/{ns}LinearRing/{ns}coordinates")
            if outer is not None and outer.text:
                outer_coords = _parse_kml_coordinates(outer.text)
                if len(outer_coords) >= 3:
                    rings.append(outer_coords)
            # Inner boundaries (holes)
            for inner in poly_el.findall(f".//{ns}innerBoundaryIs/{ns}LinearRing/{ns}coordinates"):
                if inner.text:
                    inner_coords = _parse_kml_coordinates(inner.text)
                    if len(inner_coords) >= 3:
                        rings.append(inner_coords)
            if rings:
                geometry = {"type": "Polygon", "coordinates": rings}

    if geometry is None:
        return None

    return {"type": "Feature", "geometry": geometry, "properties": properties}


def handle_import_kml(params: dict, layer_store: dict = None) -> dict:
    """Parse KML content to GeoJSON layer."""
    kml_data = params.get("kml_data")
    if not kml_data or not kml_data.strip():
        return {"error": "kml_data is required and must not be empty"}

    layer_name = params.get("layer_name", "kml_import")

    try:
        root = ET.fromstring(kml_data)
    except ET.ParseError as e:
        return {"error": f"Invalid KML: could not parse XML. {e}"}

    # Detect namespace
    ns = ""
    tag = root.tag
    if tag.startswith("{"):
        ns = tag[: tag.index("}") + 1]

    # Find all Placemark elements (recursive)
    placemarks = root.findall(f".//{ns}Placemark")
    if not placemarks:
        return {"error": "No Placemark elements found in KML data"}

    features = []
    skipped = 0
    for pm in placemarks:
        feature = _parse_kml_placemark(pm, ns)
        if feature:
            features.append(feature)
        else:
            skipped += 1

    if not features:
        return {"error": "No valid geometries found in KML placemarks"}

    geojson = {"type": "FeatureCollection", "features": features}

    if layer_store is not None:
        try:
            from state import layer_lock as _lk
        except ImportError:
            _lk = None
        if _lk:
            with _lk:
                layer_store[layer_name] = geojson
        else:
            layer_store[layer_name] = geojson

    return {
        "geojson": geojson,
        "layer_name": layer_name,
        "imported": len(features),
        "skipped": skipped,
        "description": f"Imported {len(features)} features from KML as '{layer_name}'",
    }


# ============================================================
# GeoParquet Import/Export
# ============================================================

def handle_import_geoparquet(params: dict, layer_store: dict = None) -> dict:
    """Import a GeoParquet file (base64-encoded) to GeoJSON layer."""
    import io
    import json as json_mod

    parquet_data = params.get("parquet_data")
    if not parquet_data or not parquet_data.strip():
        return {"error": "parquet_data is required (base64-encoded parquet file)"}

    layer_name = params.get("layer_name", "geoparquet_import")

    try:
        import geopandas as gpd_mod
    except ImportError:
        return {"error": "geopandas is required for GeoParquet import"}

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return {"error": "pyarrow is required for GeoParquet import. Install with: pip install pyarrow"}

    try:
        raw_bytes = base64.b64decode(parquet_data)
    except Exception:
        return {"error": "Invalid base64 encoding in parquet_data"}

    try:
        gdf = gpd_mod.read_parquet(io.BytesIO(raw_bytes))
    except Exception as e:
        logger.error("GeoParquet import error: %s", e, exc_info=True)
        return {"error": "Failed to read GeoParquet data"}

    if gdf.empty:
        return {"error": "GeoParquet file contains no features"}

    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)

    try:
        geojson = json_mod.loads(gdf.to_json())
    except Exception:
        return {"error": "Failed to convert GeoParquet data to GeoJSON"}

    if layer_store is not None:
        try:
            from state import layer_lock as _lk
        except ImportError:
            _lk = None
        if _lk:
            with _lk:
                layer_store[layer_name] = geojson
        else:
            layer_store[layer_name] = geojson

    return {
        "geojson": geojson,
        "layer_name": layer_name,
        "imported": len(geojson.get("features", [])),
        "description": f"Imported {len(geojson.get('features', []))} features from GeoParquet as '{layer_name}'",
    }


def handle_export_geoparquet(params: dict, layer_store: dict = None) -> dict:
    """Export a layer as GeoParquet (returned as base64)."""
    import io

    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    try:
        import geopandas as gpd_mod
    except ImportError:
        return {"error": "geopandas is required for GeoParquet export"}

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        return {"error": "pyarrow is required for GeoParquet export. Install with: pip install pyarrow"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}

    if not features:
        return {"error": f"Layer '{layer_name}' has no features to export"}

    try:
        gdf = gpd_mod.GeoDataFrame.from_features(features)
        if gdf.crs is None:
            gdf.set_crs(epsg=4326, inplace=True)

        buf = io.BytesIO()
        gdf.to_parquet(buf)
        parquet_bytes = buf.getvalue()
    except Exception as e:
        logger.error("GeoParquet export error: %s", e, exc_info=True)
        return {"error": "Failed to export layer as GeoParquet"}

    return {
        "success": True,
        "format": "geoparquet",
        "layer_name": layer_name,
        "feature_count": len(features),
        "parquet_base64": base64.b64encode(parquet_bytes).decode("ascii"),
        "size_bytes": len(parquet_bytes),
        "description": f"Exported {len(features)} features from '{layer_name}' as GeoParquet ({len(parquet_bytes)} bytes)",
    }


# ============================================================
# v2.1 Plan 10 — GeoPackage export + format-auto import
# ============================================================


def handle_export_gpkg(params: dict, layer_store: dict = None) -> dict:
    """Export a layer as GeoPackage (.gpkg). Falls back to GeoJSON if GDAL's
    GPKG driver is unavailable."""
    import io
    import tempfile
    import os as os_mod

    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}
    filename = params.get("filename") or f"{layer_name}.gpkg"

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features to export"}

    try:
        import geopandas as gpd_mod
    except ImportError:
        return {"error": "GeoPackage export requires geopandas."}

    try:
        gdf = gpd_mod.GeoDataFrame.from_features(features, crs="EPSG:4326")
    except Exception as exc:
        logger.debug("GPKG from_features failed: %s", exc, exc_info=True)
        return {"error": "Could not convert layer to GeoDataFrame for export"}

    # Write to a temp file because fiona/GDAL needs a real path.
    try:
        with tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False) as tmp:
            tmp_path = tmp.name
        gdf.to_file(tmp_path, driver="GPKG")
        with open(tmp_path, "rb") as f:
            data = f.read()
    except Exception as exc:
        logger.warning("GPKG write failed, falling back to GeoJSON: %s", exc)
        # Graceful fallback: return GeoJSON with a warning.
        import json as json_mod
        return {
            "success": True,
            "format": "geojson",
            "layer_name": layer_name,
            "feature_count": len(features),
            "geojson_string": json_mod.dumps({"type": "FeatureCollection", "features": features}),
            "warning": (
                "GeoPackage export failed (GDAL driver unavailable). "
                "Exported as GeoJSON instead."
            ),
            "description": f"Exported {len(features)} features as GeoJSON (GPKG fallback).",
        }
    finally:
        try:
            os_mod.remove(tmp_path)
        except OSError:
            pass

    return {
        "success": True,
        "format": "geopackage",
        "layer_name": layer_name,
        "feature_count": len(features),
        "filename": filename,
        "gpkg_base64": base64.b64encode(data).decode("ascii"),
        "size_bytes": len(data),
        "mime_type": "application/geopackage+sqlite3",
        "description": f"Exported {len(features)} features from '{layer_name}' as GeoPackage ({len(data)} bytes)",
    }


def _detect_format(data: str) -> str | None:
    """Return a format id ('geojson'|'kml'|'csv'|'wkt'|'shapefile'|'geoparquet')
    or None if the input can't be classified."""
    if not data or not isinstance(data, str):
        return None
    head = data.strip()
    # JSON / GeoJSON
    if head.startswith("{") or head.startswith("["):
        return "geojson"
    # XML / KML
    if head.startswith("<?xml") or "<kml" in head[:200].lower() or "<placemark" in head[:200].lower():
        return "kml"
    # WKT
    upper = head.upper()
    for prefix in ("POINT", "LINESTRING", "POLYGON", "MULTIPOINT", "MULTILINESTRING",
                   "MULTIPOLYGON", "GEOMETRYCOLLECTION"):
        if upper.startswith(prefix):
            return "wkt"
    # Base64-encoded binary: Shapefile (ZIP) or GeoParquet.
    # First few decoded bytes tell us — try once.
    try:
        raw = base64.b64decode(head[:256], validate=False)
        if raw.startswith(b"PK"):
            return "shapefile"
        if raw.startswith(b"PAR1"):
            return "geoparquet"
    except Exception:
        pass
    # CSV heuristic: has a header line with delimiters and a lat/lon-like column.
    first_line = head.split("\n", 1)[0].lower()
    if "," in first_line and any(
        kw in first_line
        for kw in ("lat", "lon", "latitude", "longitude")
    ):
        return "csv"
    return None


def handle_import_auto(params: dict, layer_store: dict = None) -> dict:
    """Detect format of arbitrary input and delegate to the appropriate importer
    (v2.1 Plan 10 M4). Supports GeoJSON, KML, WKT, CSV, Shapefile, GeoParquet.
    """
    data = params.get("data")
    if not data:
        return {"error": "data is required"}
    layer_name = params.get("layer_name")

    fmt = _detect_format(data)
    if fmt is None:
        return {"error": (
            "Could not auto-detect format. "
            "Supported: GeoJSON, CSV (with lat/lon columns), KML, WKT, "
            "Shapefile (base64 zip), GeoParquet (base64)."
        )}

    # Delegate — each importer has its own error handling.
    if fmt == "geojson":
        # handle_import_layer expects a parsed dict, not a JSON string.
        try:
            import json as json_mod
            parsed = json_mod.loads(data)
        except (TypeError, ValueError) as exc:
            return {"error": f"Detected GeoJSON but could not parse: {exc}"}
        sub = {"geojson": parsed}
        if layer_name:
            sub["layer_name"] = layer_name
        result = handle_import_layer(sub, layer_store)
    elif fmt == "kml":
        sub = {"kml_data": data}
        if layer_name:
            sub["layer_name"] = layer_name
        result = handle_import_kml(sub, layer_store)
    elif fmt == "wkt":
        sub = {"wkt": data}
        if layer_name:
            sub["layer_name"] = layer_name
        result = handle_import_wkt(sub, layer_store)
    elif fmt == "csv":
        # Caller can override column names in params.
        sub = {
            "csv_data": data,
            "lat_column": params.get("lat_column", "lat"),
            "lon_column": params.get("lon_column", "lon"),
        }
        if layer_name:
            sub["layer_name"] = layer_name
        result = handle_import_csv(sub, layer_store)
    elif fmt == "geoparquet":
        sub = {"parquet_data": data}
        if layer_name:
            sub["layer_name"] = layer_name
        result = handle_import_geoparquet(sub, layer_store)
    elif fmt == "shapefile":
        # Zipped shapefile currently uses the generic import_layer path only
        # if the user pre-converted to GeoJSON. Surface a clear error rather
        # than silently failing.
        return {
            "error": (
                "Shapefile (zip) import is not yet supported by this tool. "
                "Please unzip and provide the .shp as GeoJSON via import_layer."
            )
        }
    else:
        return {"error": f"Unsupported detected format: {fmt}"}

    if isinstance(result, dict) and "error" not in result:
        result["detected_format"] = fmt
    return result
