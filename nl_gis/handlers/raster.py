"""Raster handlers: info, point value, zonal statistics, profile, classify.

v2.1 Plan 08. Operates on TIFs in Config.RASTER_DIR (default ./sample_rasters/).
Depends on rasterio (already in requirements.txt). Handlers degrade gracefully
with a clear error if rasterio is not importable.

ERROR PATHS (audit 2026-04-18 for v2.1 Plan 05 M1):
    Pure new module; every handler uses the same error return shape
    (`{"error": str}`). No leaky exception paths.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from config import Config
from nl_gis.geo_utils import ValidatedPoint, geodesic_distance

logger = logging.getLogger(__name__)


# Import rasterio lazily so the rest of the app still works if GDAL is broken.
try:
    import rasterio  # type: ignore
    import rasterio.mask  # type: ignore
    import rasterio.features  # type: ignore
    from rasterio.warp import transform as warp_transform  # type: ignore
    import numpy as np  # type: ignore
    _RASTERIO_OK = True
    _RASTERIO_ERR: str | None = None
except ImportError as _e:  # pragma: no cover — environmental
    _RASTERIO_OK = False
    _RASTERIO_ERR = str(_e)
    logger.warning("rasterio unavailable: %s. Raster tools will return errors.", _e)


_RASTER_EXTENSIONS = {".tif", ".tiff"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_rasterio() -> dict | None:
    """Return an error result if rasterio is unavailable, else None."""
    if not _RASTERIO_OK:
        return {"error": f"Raster support unavailable: {_RASTERIO_ERR}"}
    return None


def _safe_raster_path(name: str) -> tuple[str | None, str | None]:
    """Resolve a raster name to an absolute path, blocking traversal.

    Returns (abs_path, None) on success or (None, error_message) on failure.
    """
    if not name:
        return None, "raster filename is required"
    base = os.path.abspath(Config.RASTER_DIR)
    candidate = os.path.abspath(os.path.join(base, name))
    # Prevent ../ escapes.
    if os.path.commonpath([candidate, base]) != base:
        return None, f"Invalid raster path: '{name}'"
    if not os.path.exists(candidate):
        return None, f"Raster not found: '{name}' (check Config.RASTER_DIR)"
    ext = os.path.splitext(candidate)[1].lower()
    if ext not in _RASTER_EXTENSIONS:
        return None, f"Unsupported extension: '{ext}' (expected .tif or .tiff)"
    return candidate, None


def _open_raster(name: str):
    """Open a raster by filename. Returns (dataset, None) or (None, error)."""
    err = _require_rasterio()
    if err:
        return None, err["error"]

    path, path_err = _safe_raster_path(name)
    if path_err:
        return None, path_err

    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > Config.MAX_RASTER_SIZE_MB:
        return None, (
            f"Raster '{name}' is {size_mb:.1f} MB, exceeds "
            f"MAX_RASTER_SIZE_MB={Config.MAX_RASTER_SIZE_MB}."
        )

    try:
        ds = rasterio.open(path)
        return ds, None
    except Exception as e:
        logger.warning("Failed to open raster %s: %s", name, e, exc_info=True)
        return None, f"Could not open raster '{name}'."


def _list_available_rasters() -> list[dict]:
    """Return a list of `{"name": str, "size_mb": float}` for tifs in RASTER_DIR."""
    base = Config.RASTER_DIR
    if not os.path.isdir(base):
        return []
    out = []
    for fname in sorted(os.listdir(base)):
        if os.path.splitext(fname)[1].lower() not in _RASTER_EXTENSIONS:
            continue
        path = os.path.join(base, fname)
        try:
            size_mb = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            continue
        out.append({"name": fname, "size_mb": round(size_mb, 2)})
    return out


def _to_wgs84_bounds(ds) -> list[float]:
    """Return [south, west, north, east] in WGS84 for a rasterio dataset."""
    # ds.bounds is (left, bottom, right, top) in raster CRS
    left, bottom, right, top = ds.bounds
    src_crs = ds.crs
    # Convert corner lon/lat using rasterio.warp.transform
    xs = [left, right]
    ys = [bottom, top]
    if src_crs is None or src_crs.to_epsg() == 4326:
        return [round(bottom, 6), round(left, 6), round(top, 6), round(right, 6)]
    lon_w, lat_s = warp_transform(src_crs, "EPSG:4326", [xs[0]], [ys[0]])
    lon_e, lat_n = warp_transform(src_crs, "EPSG:4326", [xs[1]], [ys[1]])
    return [
        round(float(lat_s[0]), 6),
        round(float(lon_w[0]), 6),
        round(float(lat_n[0]), 6),
        round(float(lon_e[0]), 6),
    ]


def _project_lonlat_to_raster_crs(ds, lat: float, lon: float) -> tuple[float, float]:
    """Convert WGS84 (lat,lon) to the raster's native CRS (x, y)."""
    src_crs = ds.crs
    if src_crs is None or src_crs.to_epsg() == 4326:
        return lon, lat
    xs, ys = warp_transform("EPSG:4326", src_crs, [lon], [lat])
    return float(xs[0]), float(ys[0])


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def handle_raster_info(params: dict) -> dict:
    """Return metadata for a raster, or list available rasters."""
    err = _require_rasterio()
    if err:
        return err

    name = params.get("raster")
    if not name:
        return {
            "available_rasters": _list_available_rasters(),
            "raster_dir": Config.RASTER_DIR,
        }

    ds, open_err = _open_raster(name)
    if open_err:
        return {"error": open_err}
    try:
        epsg = ds.crs.to_epsg() if ds.crs else None
        resx, resy = ds.res
        return {
            "raster": name,
            "crs": f"EPSG:{epsg}" if epsg else str(ds.crs),
            "resolution": [resx, resy],
            "width": ds.width,
            "height": ds.height,
            "bands": ds.count,
            "dtype": str(ds.dtypes[0]) if ds.dtypes else "unknown",
            "nodata": ds.nodata,
            "bounds_wgs84": _to_wgs84_bounds(ds),
        }
    finally:
        ds.close()


def handle_raster_value(params: dict) -> dict:
    """Sample raster value(s) at a single point."""
    err = _require_rasterio()
    if err:
        return err

    name = params.get("raster")
    if not name:
        return {"error": "raster is required"}

    lat = params.get("lat")
    lon = params.get("lon")
    location = params.get("location")
    if (lat is None or lon is None) and location:
        from nl_gis.handlers.navigation import handle_geocode
        geo = handle_geocode({"query": location})
        if "error" in geo:
            return {"error": f"Could not geocode location: {geo['error']}"}
        lat = geo["lat"]; lon = geo["lon"]
    if lat is None or lon is None:
        return {"error": "Provide lat + lon or location"}

    try:
        vp = ValidatedPoint(lat=float(lat), lon=float(lon))
    except (TypeError, ValueError) as e:
        return {"error": f"Invalid coordinates: {e}"}

    ds, open_err = _open_raster(name)
    if open_err:
        return {"error": open_err}
    try:
        x, y = _project_lonlat_to_raster_crs(ds, vp.lat, vp.lon)
        left, bottom, right, top = ds.bounds
        if not (left <= x <= right and bottom <= y <= top):
            return {"error": "Point is outside the raster extent"}
        values = list(next(ds.sample([(x, y)])))
        row, col = ds.index(x, y)
        return {
            "raster": name,
            "lat": vp.lat,
            "lon": vp.lon,
            "values": [float(v) if v is not None else None for v in values],
            "bands": ds.count,
            "pixel_row": int(row),
            "pixel_col": int(col),
        }
    finally:
        ds.close()


def handle_raster_statistics(params: dict, layer_store: dict | None = None) -> dict:
    """Global or zonal statistics for a raster band.

    Global mode: `{"raster": name, "band": 1, "derivative": "slope|aspect|hillshade" (optional)}`
    Zonal mode: add `layer_name` to compute stats per polygon feature.
    """
    err = _require_rasterio()
    if err:
        return err

    name = params.get("raster")
    if not name:
        return {"error": "raster is required"}
    band = int(params.get("band", 1))
    layer_name = params.get("layer_name")
    derivative = params.get("derivative")

    ds, open_err = _open_raster(name)
    if open_err:
        return {"error": open_err}

    try:
        # --- Zonal statistics mode --------------------------------------
        if layer_name:
            return _zonal_stats(ds, name, band, layer_name, layer_store, derivative)

        # --- Global statistics mode -------------------------------------
        arr = ds.read(band, masked=True)
        if derivative in ("slope", "aspect", "hillshade"):
            arr = _compute_dem_derivative(ds, derivative, band)
        data = arr.compressed() if hasattr(arr, "compressed") else np.asarray(arr).ravel()
        data = data[np.isfinite(data)]
        if data.size == 0:
            return {"error": "No valid pixel values (all nodata or NaN)"}
        return {
            "raster": name,
            "band": band,
            "derivative": derivative,
            "min": float(np.min(data)),
            "max": float(np.max(data)),
            "mean": float(np.mean(data)),
            "std": float(np.std(data)),
            "median": float(np.median(data)),
            "count": int(data.size),
        }
    finally:
        ds.close()


def _zonal_stats(
    ds,
    raster_name: str,
    band: int,
    layer_name: str,
    layer_store: dict | None,
    derivative: str | None,
) -> dict:
    from nl_gis.handlers import _get_layer_snapshot  # local import breaks cycle
    if not layer_store:
        return {"error": "No layer store available for zonal stats"}
    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' has no features"}

    # If derivative requested, pre-compute the derived band into an in-memory array.
    derived_array = None
    if derivative:
        derived_array = _compute_dem_derivative(ds, derivative, band)

    from shapely.geometry import shape as shp_shape, mapping as shp_mapping
    from shapely.ops import transform as shp_transform
    import pyproj

    to_raster_crs = None
    if ds.crs and ds.crs.to_epsg() != 4326:
        project = pyproj.Transformer.from_crs("EPSG:4326", ds.crs, always_xy=True).transform
        to_raster_crs = project

    output_features = []
    for f in features:
        geom = f.get("geometry")
        if not geom:
            continue
        try:
            shp = shp_shape(geom)
            if to_raster_crs is not None:
                shp = shp_transform(to_raster_crs, shp)
        except Exception:
            continue

        try:
            # Mask the original band (or use derived_array indexed with window)
            if derived_array is not None:
                # derive-from-full-array path: mask with rasterio.features.geometry_mask
                from rasterio.features import geometry_mask
                mask = geometry_mask(
                    [shp_mapping(shp)],
                    transform=ds.transform,
                    invert=True,
                    out_shape=(ds.height, ds.width),
                )
                data = derived_array[mask]
            else:
                out_image, _ = rasterio.mask.mask(
                    ds, [shp_mapping(shp)], crop=True, indexes=band, filled=False
                )
                # out_image has shape (H, W) with masked nodata pixels
                arr = out_image if hasattr(out_image, "compressed") else np.asarray(out_image)
                data = arr.compressed() if hasattr(arr, "compressed") else arr.ravel()
        except Exception as exc:
            logger.debug("Zonal mask failed: %s", exc)
            continue

        data = np.asarray(data)
        data = data[np.isfinite(data)]
        new_props = dict(f.get("properties") or {})
        if data.size == 0:
            new_props["raster_count"] = 0
        else:
            new_props.update({
                "raster_min": float(np.min(data)),
                "raster_max": float(np.max(data)),
                "raster_mean": float(np.mean(data)),
                "raster_std": float(np.std(data)),
                "raster_count": int(data.size),
            })
        output_features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": new_props,
        })

    output_name = f"zonal_{raster_name}_on_{layer_name}".replace(".", "_")
    return {
        "geojson": {"type": "FeatureCollection", "features": output_features},
        "layer_name": output_name,
        "feature_count": len(output_features),
        "raster": raster_name,
        "band": band,
        "derivative": derivative,
    }


def handle_raster_profile(params: dict) -> dict:
    """Sample raster values along a line between two points."""
    err = _require_rasterio()
    if err:
        return err

    name = params.get("raster")
    if not name:
        return {"error": "raster is required"}
    num_samples = int(params.get("num_samples", 100))
    num_samples = max(2, min(num_samples, 500))

    from_point, from_name, ferr = _resolve_profile_point(params, "from")
    if ferr:
        return {"error": ferr}
    to_point, to_name, terr = _resolve_profile_point(params, "to")
    if terr:
        return {"error": terr}

    ds, open_err = _open_raster(name)
    if open_err:
        return {"error": open_err}
    try:
        # Linear interpolation in WGS84 — simple enough for short profiles.
        lats = np.linspace(from_point.lat, to_point.lat, num_samples)
        lons = np.linspace(from_point.lon, to_point.lon, num_samples)
        samples = []
        total_distance = geodesic_distance(from_point, to_point)
        for i, (la, lo) in enumerate(zip(lats, lons)):
            x, y = _project_lonlat_to_raster_crs(ds, la, lo)
            left, bottom, right, top = ds.bounds
            if not (left <= x <= right and bottom <= y <= top):
                samples.append({"distance_m": float(i * total_distance / (num_samples - 1)), "value": None, "lat": float(la), "lon": float(lo)})
                continue
            try:
                values = list(next(ds.sample([(x, y)])))
                v = float(values[0]) if values else None
            except Exception:
                v = None
            samples.append({
                "distance_m": float(i * total_distance / (num_samples - 1)),
                "value": v,
                "lat": float(la),
                "lon": float(lo),
            })

        valid_values = [s["value"] for s in samples if s["value"] is not None and np.isfinite(s["value"])]
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[s["lon"], s["lat"]] for s in samples],
                },
                "properties": {
                    "raster": name,
                    "num_samples": num_samples,
                    "total_distance_m": total_distance,
                },
            }],
        }
        return {
            "profile": samples,
            "min_value": float(min(valid_values)) if valid_values else None,
            "max_value": float(max(valid_values)) if valid_values else None,
            "total_distance_m": float(total_distance),
            "geojson": geojson,
            "layer_name": f"profile_{name}".replace(".", "_"),
            "from": {"lat": from_point.lat, "lon": from_point.lon, "name": from_name},
            "to": {"lat": to_point.lat, "lon": to_point.lon, "name": to_name},
        }
    finally:
        ds.close()


def _resolve_profile_point(params: dict, which: str):
    """Resolve `{which}_point` dict or `{which}_location` string into a ValidatedPoint."""
    pt = params.get(f"{which}_point") or {}
    loc = params.get(f"{which}_location")
    lat = pt.get("lat") if isinstance(pt, dict) else None
    lon = pt.get("lon") if isinstance(pt, dict) else None
    name = None
    if lat is not None and lon is not None:
        try:
            return ValidatedPoint(lat=float(lat), lon=float(lon)), None, None
        except (TypeError, ValueError) as e:
            return None, None, f"Invalid {which}_point: {e}"
    if loc:
        from nl_gis.handlers.navigation import handle_geocode
        geo = handle_geocode({"query": loc})
        if "error" in geo:
            return None, None, f"Could not geocode {which}_location: {geo['error']}"
        try:
            return ValidatedPoint(lat=geo["lat"], lon=geo["lon"]), geo.get("display_name"), None
        except (TypeError, ValueError) as e:
            return None, None, f"Invalid geocode result for {which}_location: {e}"
    return None, None, f"Provide {which}_point (lat,lon) or {which}_location"


def handle_raster_classify(params: dict, layer_store: dict | None = None) -> dict:
    """Reclassify a raster into polygon features by breakpoints."""
    err = _require_rasterio()
    if err:
        return err

    name = params.get("raster")
    if not name:
        return {"error": "raster is required"}
    breaks = params.get("breaks")
    if not isinstance(breaks, list) or len(breaks) < 1:
        return {"error": "breaks must be a non-empty list of numbers"}
    try:
        breaks = sorted(float(b) for b in breaks)
    except (TypeError, ValueError):
        return {"error": "breaks must all be numeric"}

    labels = params.get("labels")
    if labels and not isinstance(labels, list):
        return {"error": "labels must be a list of strings"}
    band = int(params.get("band", 1))

    ds, open_err = _open_raster(name)
    if open_err:
        return {"error": open_err}
    try:
        arr = ds.read(band, masked=True)
        data = np.asarray(arr)
        classified = np.digitize(data, breaks).astype("int32")
        # Build a same-shape bool mask of valid pixels. When rasterio has no
        # nodata, arr.mask is a scalar `False` — expand it to a full array.
        if hasattr(arr, "mask") and np.ndim(arr.mask) > 0:
            mask = ~np.asarray(arr.mask)
        else:
            mask = np.isfinite(data)
        mask = mask.astype("uint8")
        features = []
        count = 0
        max_features = Config.MAX_FEATURES_PER_LAYER
        for geom, cls_val in rasterio.features.shapes(
            classified, mask=mask, transform=ds.transform
        ):
            if count >= max_features:
                break
            cls_idx = int(cls_val)
            props: dict[str, Any] = {"class": cls_idx}
            if labels:
                if 0 <= cls_idx < len(labels):
                    props["label"] = labels[cls_idx]
            # Convert geom to WGS84 if needed
            geom_wgs84 = _geom_to_wgs84(geom, ds.crs) if ds.crs else geom
            features.append({
                "type": "Feature",
                "geometry": geom_wgs84,
                "properties": props,
            })
            count += 1

        output_name = f"classified_{name}".replace(".", "_")
        return {
            "geojson": {"type": "FeatureCollection", "features": features},
            "layer_name": output_name,
            "feature_count": len(features),
            "raster": name,
            "band": band,
            "breaks": breaks,
            "class_count": len(breaks) + 1,
            "truncated": count >= max_features,
        }
    finally:
        ds.close()


def _geom_to_wgs84(geom: dict, src_crs) -> dict:
    """Transform a GeoJSON geometry from src_crs to EPSG:4326."""
    if src_crs is None or src_crs.to_epsg() == 4326:
        return geom
    import pyproj
    from shapely.geometry import shape as shp_shape, mapping as shp_mapping
    from shapely.ops import transform as shp_transform

    project = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True).transform
    try:
        s = shp_shape(geom)
        s2 = shp_transform(project, s)
        return shp_mapping(s2)
    except Exception:
        return geom


# ---------------------------------------------------------------------------
# DEM derivatives
# ---------------------------------------------------------------------------


def _compute_dem_derivative(ds, derivative_type: str, band: int = 1):
    """Compute slope (degrees), aspect (0-360°), or hillshade (0-255) from a band."""
    arr = ds.read(band).astype("float64")
    resx, resy = ds.res
    # numpy.gradient returns (dy, dx) — note y increases downward in array but
    # the geospatial y axis usually points north; we just want relative slope,
    # so the sign difference cancels in slope computation. For aspect we flip.
    dy, dx = np.gradient(arr, resy, resx)
    if derivative_type == "slope":
        slope_rad = np.arctan(np.hypot(dx, dy))
        return np.degrees(slope_rad)
    if derivative_type == "aspect":
        aspect_rad = np.arctan2(-dy, dx)
        aspect_deg = (np.degrees(aspect_rad) + 360.0) % 360.0
        return aspect_deg
    if derivative_type == "hillshade":
        azimuth_deg = 315.0
        altitude_deg = 45.0
        az = np.radians(azimuth_deg)
        alt = np.radians(altitude_deg)
        slope = np.arctan(np.hypot(dx, dy))
        aspect = np.arctan2(-dy, dx)
        shade = (
            np.sin(alt) * np.cos(slope)
            + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
        )
        return np.clip(shade * 255.0, 0, 255)
    raise ValueError(f"Unknown derivative: {derivative_type}")
