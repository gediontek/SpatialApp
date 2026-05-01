"""OSM auto-label integration handlers (v2.1 Plan 12).

Bridges SpatialApp's tool-dispatch layer with the `OSM_auto_label/`
sub-project (ML landcover classification using word embeddings +
spectral clustering).

Three tiers of handlers:

1. **No-dependency**: `handle_evaluate_classifier`, `handle_export_training_data`
   work without `OSM_auto_label`'s heavy deps (gensim, osmnx).

2. **Auto-label-dependent**: `handle_classify_area`, `handle_predict_labels`,
   `handle_train_classifier` require gensim/osmnx. They return a clear
   error message when deps are missing — the rest of the app still
   loads. Tests inject mock classifiers via `_set_test_factories`.

The `OSM_auto_label.config.CATEGORY_COLORS` palette is mirrored here so
responses always carry a colorMap — no import dance for the frontend.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette (mirrored from OSM_auto_label/config.py so frontend always works)
# ---------------------------------------------------------------------------

CATEGORY_COLORS: dict[str, str] = {
    "builtup_area": "#E31A1C",
    "water": "#1F78B4",
    "bare_earth": "#A6CEE3",
    "forest": "#33A02C",
    "farmland": "#FFFF99",
    "grassland": "#B2DF8A",
    "aquaculture": "#6A3D9A",
}
DEFAULT_COLOR = "#808080"

# Maximum features we'll classify in one call (cap the network/model time).
MAX_CLASSIFY_FEATURES = 10_000


# ---------------------------------------------------------------------------
# Test seam: factories that produce the heavy objects.
# Tests can inject lightweight mocks via `_set_test_factories(...)`.
# ---------------------------------------------------------------------------

_classifier_factory: Optional[Callable[[], Any]] = None
_downloader_factory: Optional[Callable[[], Any]] = None


def _set_test_factories(
    classifier_factory: Callable[[], Any] | None = None,
    downloader_factory: Callable[[], Any] | None = None,
) -> None:
    """Test hook: inject mock classifier and/or downloader factories.

    Pass `None` to either to leave it untouched. Pass `False` (== falsy
    but not None) by setting the global directly to clear it.
    """
    global _classifier_factory, _downloader_factory
    if classifier_factory is not None:
        _classifier_factory = classifier_factory
    if downloader_factory is not None:
        _downloader_factory = downloader_factory


def _reset_test_factories() -> None:
    global _classifier_factory, _downloader_factory
    _classifier_factory = None
    _downloader_factory = None


# ---------------------------------------------------------------------------
# Lazy autolabel imports
# ---------------------------------------------------------------------------

def _real_classifier():
    """Return an `OSMLandcoverClassifier` instance, or raise."""
    from OSM_auto_label import OSMLandcoverClassifier  # type: ignore[import-not-found]
    return OSMLandcoverClassifier()


def _real_downloader():
    """Return an object with `from_location(loc)` and `from_bbox(bbox)`.

    Wraps the autolabel module's free functions for a uniform interface.
    """
    from OSM_auto_label import download_osm_landcover, download_by_bbox  # type: ignore[import-not-found]

    class _Downloader:
        def from_location(self, location: str):
            return download_osm_landcover(location)

        def from_bbox(self, bbox: tuple[float, float, float, float]):
            return download_by_bbox(bbox)

    return _Downloader()


def _get_classifier():
    if _classifier_factory is not None:
        return _classifier_factory()
    return _real_classifier()


def _get_downloader():
    if _downloader_factory is not None:
        return _downloader_factory()
    return _real_downloader()


# ---------------------------------------------------------------------------
# GeoDataFrame ↔ GeoJSON helpers (kept tiny + dependency-light)
# ---------------------------------------------------------------------------

def _gdf_to_geojson(gdf, max_features: int = MAX_CLASSIFY_FEATURES) -> dict:
    """Convert a (geo)DataFrame-like object to a GeoJSON FeatureCollection.

    Accepts anything with either:
    - `to_crs` + `to_json` (real GeoDataFrame), or
    - a `__geo_interface__` returning a FeatureCollection-shaped dict.

    Truncates at `max_features`.
    """
    # Real GeoDataFrame path
    if hasattr(gdf, "to_crs") and hasattr(gdf, "to_json"):
        try:
            gdf = gdf.to_crs(epsg=4326)
        except Exception:
            logger.debug("to_crs failed; assuming already 4326", exc_info=True)
        # Truncate first to limit JSON parse cost
        if hasattr(gdf, "iloc"):
            try:
                if len(gdf) > max_features:
                    gdf = gdf.iloc[:max_features]
            except Exception:
                pass
        try:
            data = json.loads(gdf.to_json())
        except Exception:
            logger.warning("to_json failed; falling back to __geo_interface__", exc_info=True)
            data = getattr(gdf, "__geo_interface__", None) or {"type": "FeatureCollection", "features": []}
        return data

    iface = getattr(gdf, "__geo_interface__", None)
    if iface and isinstance(iface, dict) and iface.get("type") == "FeatureCollection":
        feats = iface.get("features", [])[:max_features]
        return {"type": "FeatureCollection", "features": feats}
    raise TypeError("cannot convert object to GeoJSON: missing to_json/__geo_interface__")


def _build_classify_response(
    layer_name: str,
    geojson: dict,
    label_field: str = "predicted_label",
) -> dict:
    """Build a tool response with class counts and a frontend-ready style."""
    feats = geojson.get("features", []) or []
    counts: dict[str, int] = {}
    for f in feats:
        props = (f.get("properties") or {})
        label = props.get(label_field)
        if label is not None:
            counts[str(label)] = counts.get(str(label), 0) + 1
    color_map = {label: CATEGORY_COLORS.get(label, DEFAULT_COLOR) for label in counts}

    return {
        "action": "classify",
        "layer_name": layer_name,
        "geojson": geojson,
        "feature_count": len(feats),
        "class_counts": counts,
        "style": {"colorMap": color_map, "label_field": label_field},
        "legendData": {
            "type": "categorical",
            "title": f"{layer_name} — landcover",
            "entries": [
                {"label": label, "color": color_map[label], "count": counts[label]}
                for label in sorted(counts)
            ],
        },
    }


# ---------------------------------------------------------------------------
# bbox parsing
# ---------------------------------------------------------------------------

def _parse_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    """Parse 'south,west,north,east' or [s,w,n,e]. Returns None on failure."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            return tuple(float(x) for x in raw)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 4:
            return None
        try:
            return tuple(float(p) for p in parts)  # type: ignore[return-value]
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# classify_area
# ---------------------------------------------------------------------------

def handle_classify_area(params: dict, layer_store: dict | None = None) -> dict:
    """Download OSM features for a location/bbox and classify them."""
    location = params.get("location")
    bbox_raw = params.get("bbox")
    output_name = params.get("output_name") or "classified_area"

    if not location and not bbox_raw:
        return {"error": "Either 'location' or 'bbox' is required"}

    try:
        downloader = _get_downloader()
    except ImportError:
        return {
            "error": "OSM auto-label dependencies not installed. "
                     "Install gensim and osmnx, then restart the server.",
        }
    except Exception as exc:
        logger.error("Failed to initialize downloader", exc_info=True)
        return {"error": f"Downloader unavailable: {exc}"}

    try:
        if location:
            gdf = downloader.from_location(location)
        else:
            bbox = _parse_bbox(bbox_raw)
            if bbox is None:
                return {"error": "Invalid bbox; expected 'south,west,north,east'"}
            gdf = downloader.from_bbox(bbox)
    except Exception as exc:
        logger.error("OSM download failed for classify_area", exc_info=True)
        return {"error": f"OSM download failed: {exc}"}

    try:
        classifier = _get_classifier()
    except ImportError:
        return {"error": "OSM auto-label dependencies not installed (gensim missing)."}
    except Exception as exc:
        logger.error("Failed to initialize classifier", exc_info=True)
        return {"error": f"Classifier unavailable: {exc}"}

    try:
        classified = classifier.process_geodataframe(gdf, name=output_name)
    except Exception as exc:
        logger.error("Classification failed", exc_info=True)
        return {"error": f"Classification failed: {exc}"}

    try:
        geojson = _gdf_to_geojson(classified)
    except Exception as exc:
        logger.error("GeoJSON conversion failed", exc_info=True)
        return {"error": f"Could not convert classified data to GeoJSON: {exc}"}

    return _build_classify_response(output_name, geojson)


# ---------------------------------------------------------------------------
# predict_labels
# ---------------------------------------------------------------------------

def handle_predict_labels(params: dict, layer_store: dict | None = None) -> dict:
    """Run classification on an existing layer."""
    from nl_gis.handlers import _get_layer_snapshot

    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    output_name = params.get("output_name") or f"{layer_name}_classified"

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' is empty"}

    if len(features) > MAX_CLASSIFY_FEATURES:
        return {
            "error": (
                f"Layer '{layer_name}' has {len(features)} features; "
                f"classify_area cap is {MAX_CLASSIFY_FEATURES}. Filter the "
                f"layer first or split into smaller bbox regions."
            ),
        }

    try:
        classifier = _get_classifier()
    except ImportError:
        return {"error": "OSM auto-label dependencies not installed (gensim missing)."}
    except Exception as exc:
        logger.error("Failed to initialize classifier", exc_info=True)
        return {"error": f"Classifier unavailable: {exc}"}

    fc = {"type": "FeatureCollection", "features": features}

    # Try the GDF path first (real classifier expects it). If geopandas
    # isn't importable, build a duck-typed wrapper for mocked tests.
    gdf = _features_to_gdf_or_wrapper(fc)

    try:
        classified = classifier.process_geodataframe(gdf, name=output_name)
    except Exception as exc:
        logger.error("Classification failed", exc_info=True)
        return {"error": f"Classification failed: {exc}"}

    try:
        geojson = _gdf_to_geojson(classified)
    except Exception as exc:
        logger.error("GeoJSON conversion failed", exc_info=True)
        return {"error": f"Could not convert classified data to GeoJSON: {exc}"}

    return _build_classify_response(output_name, geojson)


def _features_to_gdf_or_wrapper(fc: dict):
    """Convert a FeatureCollection dict to a GeoDataFrame, or a wrapper.

    Tests that don't have geopandas installed receive a wrapper exposing
    `__geo_interface__` and `to_crs`/`to_json` no-ops.
    """
    try:
        import geopandas as gpd  # type: ignore[import-not-found]
    except ImportError:
        return _GeoJSONWrapper(fc)

    try:
        return gpd.GeoDataFrame.from_features(fc.get("features", []), crs="EPSG:4326")
    except Exception:
        logger.debug("from_features failed; returning wrapper", exc_info=True)
        return _GeoJSONWrapper(fc)


class _GeoJSONWrapper:
    """Lightweight stand-in for a GeoDataFrame in tests / no-geopandas envs."""

    def __init__(self, fc: dict):
        self._fc = fc

    def to_crs(self, *args, **kwargs):
        return self

    def to_json(self):
        return json.dumps(self._fc)

    @property
    def __geo_interface__(self) -> dict:
        return self._fc

    def __len__(self) -> int:
        return len(self._fc.get("features", []))


# ---------------------------------------------------------------------------
# train_classifier (annotation-based seed update — not real ML retraining)
# ---------------------------------------------------------------------------

def handle_train_classifier(params: dict, layer_store: dict | None = None) -> dict:
    """Update the classifier's seed categories using user-corrected labels.

    Implementation note: the underlying `OSMLandcoverClassifier` uses
    fixed seed categories from a config dict. "Training" here means
    extracting unique OSM tag → category mappings from a user-labeled
    layer and persisting them as a custom seed file the classifier can
    optionally consume. Renamed from "train" to "update" semantically.
    """
    from nl_gis.handlers import _get_layer_snapshot

    layer_name = params.get("layer_name")
    label_attribute = params.get("label_attribute") or "category_name"
    output_model_name = params.get("output_model_name") or "user_seeds"
    if not layer_name:
        return {"error": "layer_name is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' is empty"}

    seeds: dict[str, list[str]] = {}
    sample_count = 0
    for f in features:
        props = (f.get("properties") or {})
        label = props.get(label_attribute)
        if not label:
            continue
        # Source tag: prefer a representative OSM key/value, fall back to
        # any non-meta property.
        tag = (
            props.get("osm_tags", {}).get("landuse")
            or props.get("osm_tags", {}).get("natural")
            or props.get("feature_type")
            or props.get("predicted_label")
        )
        if not tag:
            continue
        seeds.setdefault(str(label), [])
        if str(tag) not in seeds[str(label)]:
            seeds[str(label)].append(str(tag))
        sample_count += 1

    if not seeds:
        return {
            "error": (
                f"No usable training samples in '{layer_name}'. "
                f"Each feature needs '{label_attribute}' AND one of "
                f"osm_tags.landuse / osm_tags.natural / feature_type / predicted_label."
            ),
        }

    # Best-effort persistence — non-fatal on permission errors.
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "OSM_auto_label", "data",
    )
    out_dir = os.path.normpath(out_dir)
    saved_path: str | None = None
    try:
        os.makedirs(out_dir, exist_ok=True)
        saved_path = os.path.join(out_dir, f"custom_seeds_{output_model_name}.json")
        with open(saved_path, "w", encoding="utf-8") as fh:
            json.dump(seeds, fh, indent=2)
    except OSError as exc:
        logger.warning("Could not persist custom seeds: %s", exc)
        saved_path = None

    return {
        "action": "train_classifier",
        "model_name": output_model_name,
        "training_samples": sample_count,
        "categories": sorted(seeds.keys()),
        "seeds": seeds,
        "saved_path": saved_path,
        "success": True,
    }


# ---------------------------------------------------------------------------
# export_training_data
# ---------------------------------------------------------------------------

def handle_export_training_data(params: dict, layer_store: dict | None = None) -> dict:
    """Export annotations as a labeled training dataset."""
    fmt = (params.get("format") or "geojson").lower()
    output_name = params.get("output_name") or "training"
    if fmt not in {"geojson", "csv"}:
        return {"error": f"format must be 'geojson' or 'csv' (got {fmt!r})"}

    # Local import to avoid circulars at module load.
    try:
        import state as state_mod  # noqa: F401  (used as state_mod below)
        annotations = []
        if state_mod.db is not None:
            try:
                annotations = state_mod.db.get_annotations()
            except Exception:
                logger.debug("state.db.get_annotations failed", exc_info=True)
                annotations = []
        if not annotations:
            # Fall back to module-level annotation list (legacy)
            annotations = list(getattr(state_mod, "geo_coco_annotations", []) or [])
    except Exception:
        annotations = []

    # Optional explicit override (lets tests inject an annotation list).
    if "annotations" in params and isinstance(params["annotations"], list):
        annotations = params["annotations"]

    if not annotations:
        return {"error": "No annotations available for export"}

    features = []
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        category = ann.get("category_name") or ann.get("label") or "unlabeled"
        geom = ann.get("geometry") or ann.get("geometry_json")
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except json.JSONDecodeError:
                continue
        if not isinstance(geom, dict):
            continue
        props = {"category_name": str(category)}
        if "color" in ann:
            props["color"] = ann["color"]
        if "source" in ann:
            props["source"] = ann["source"]
        features.append({"type": "Feature", "geometry": geom, "properties": props})

    if not features:
        return {"error": "No usable annotation geometries found"}

    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "OSM_auto_label", "data",
    )
    out_dir = os.path.normpath(out_dir)
    saved_path: str | None = None
    fc = {"type": "FeatureCollection", "features": features}
    try:
        os.makedirs(out_dir, exist_ok=True)
        if fmt == "geojson":
            saved_path = os.path.join(out_dir, f"training_{output_name}.geojson")
            with open(saved_path, "w", encoding="utf-8") as fh:
                json.dump(fc, fh)
        else:  # csv
            saved_path = os.path.join(out_dir, f"training_{output_name}.csv")
            with open(saved_path, "w", encoding="utf-8") as fh:
                fh.write("category_name,geometry_wkt\n")
                for feat in features:
                    cat = feat["properties"]["category_name"]
                    wkt = _geometry_to_wkt(feat["geometry"])
                    cat_safe = cat.replace('"', '""')
                    fh.write(f'"{cat_safe}","{wkt}"\n')
    except OSError as exc:
        logger.warning("Could not persist training data: %s", exc)
        saved_path = None

    return {
        "action": "export_training_data",
        "format": fmt,
        "model_name": output_name,
        "sample_count": len(features),
        "saved_path": saved_path,
        "geojson": fc if fmt == "geojson" else None,
    }


def _geometry_to_wkt(geom: dict) -> str:
    """Best-effort WKT serializer for the formats we encounter in annotations."""
    try:
        from shapely.geometry import shape  # type: ignore[import-not-found]
        return shape(geom).wkt
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# evaluate_classifier
# ---------------------------------------------------------------------------

def handle_evaluate_classifier(params: dict, layer_store: dict | None = None) -> dict:
    """Compute accuracy + per-class precision/recall/F1 + confusion matrix."""
    from nl_gis.handlers import _get_layer_snapshot

    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}
    label_attribute = params.get("label_attribute") or "category_name"
    predicted_attribute = params.get("predicted_attribute") or "predicted_label"

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' is empty"}

    pairs: list[tuple[str, str]] = []
    for f in features:
        props = (f.get("properties") or {})
        truth = props.get(label_attribute)
        pred = props.get(predicted_attribute)
        if truth is None or pred is None:
            continue
        pairs.append((str(truth), str(pred)))

    if not pairs:
        return {
            "error": (
                f"No features have both '{label_attribute}' and "
                f"'{predicted_attribute}' set."
            ),
        }

    classes = sorted({c for pair in pairs for c in pair})
    confusion = {t: {p: 0 for p in classes} for t in classes}
    correct = 0
    for truth, pred in pairs:
        confusion[truth][pred] += 1
        if truth == pred:
            correct += 1

    accuracy = correct / len(pairs)

    per_class: dict[str, dict[str, float]] = {}
    for c in classes:
        tp = confusion[c][c]
        fp = sum(confusion[other][c] for other in classes if other != c)
        fn = sum(confusion[c][other] for other in classes if other != c)
        support = sum(confusion[c].values())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_class[c] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }

    return {
        "action": "evaluate_classifier",
        "layer_name": layer_name,
        "accuracy": round(accuracy, 4),
        "total_evaluated": len(pairs),
        "per_class": per_class,
        "confusion_matrix": confusion,
        "classes": classes,
    }
