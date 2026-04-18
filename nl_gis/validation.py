"""GeoJSON validation for import pipelines (v2.1 Plan 10 M4).

Produces a normalized `{valid, warnings, errors, stats, repaired_geojson}`
report when ingesting layers. Permissive by default — repairs what can be
repaired, rejects only what truly can't be parsed.
"""

from __future__ import annotations

import logging
from typing import Any

from shapely.geometry import shape, mapping
from shapely.validation import make_valid, explain_validity

from config import Config

logger = logging.getLogger(__name__)

_DEFAULT_MAX_FEATURES = 10_000


def _get_import_max_features() -> int:
    return getattr(Config, "IMPORT_MAX_FEATURES", _DEFAULT_MAX_FEATURES)


def _empty_report() -> dict:
    return {
        "valid": False,
        "warnings": [],
        "errors": [],
        "stats": {
            "total": 0, "valid_geom": 0, "invalid_geom": 0,
            "null_geom": 0, "duplicates": 0, "repaired": 0,
        },
        "repaired_geojson": None,
    }


def validate_geojson(geojson: Any, auto_repair: bool = True) -> dict:
    """Validate a GeoJSON FeatureCollection and optionally repair geometries.

    Returns a report dict. When `valid` is True the `repaired_geojson` is the
    cleaned version (possibly identical to input). When `valid` is False
    `repaired_geojson` may still be partially repaired — callers decide.
    """
    report = _empty_report()

    if not isinstance(geojson, dict):
        report["errors"].append("Input is not a JSON object.")
        return report
    if geojson.get("type") != "FeatureCollection":
        report["errors"].append(
            "Expected a FeatureCollection; got "
            f"{geojson.get('type')!r}."
        )
        return report
    features = geojson.get("features")
    if not isinstance(features, list):
        report["errors"].append("features must be an array.")
        return report

    max_features = _get_import_max_features()
    truncated_count = 0
    if len(features) > max_features:
        truncated_count = len(features) - max_features
        features = features[:max_features]
        report["warnings"].append(
            f"Truncated from {len(features) + truncated_count} to "
            f"{len(features)} features (limit: IMPORT_MAX_FEATURES={max_features})."
        )

    report["stats"]["total"] = len(features)
    seen_hashes: set[str] = set()
    cleaned_features: list[dict] = []

    for idx, feature in enumerate(features):
        if not isinstance(feature, dict):
            report["warnings"].append(f"Feature {idx}: not an object, skipped.")
            continue
        geom = feature.get("geometry")
        props = feature.get("properties") or {}

        if geom is None:
            report["stats"]["null_geom"] += 1
            if auto_repair:
                continue  # drop null-geom features when repairing
            cleaned_features.append(feature)
            continue

        try:
            shp = shape(geom)
        except Exception as exc:
            report["stats"]["invalid_geom"] += 1
            report["warnings"].append(
                f"Feature {idx}: could not parse geometry ({exc}). Skipped."
            )
            continue

        if not shp.is_valid:
            reason = explain_validity(shp)
            report["stats"]["invalid_geom"] += 1
            if auto_repair:
                try:
                    repaired = make_valid(shp)
                    shp = repaired
                    report["stats"]["repaired"] += 1
                    report["warnings"].append(
                        f"Feature {idx}: repaired invalid geometry ({reason})."
                    )
                except Exception as exc:
                    report["warnings"].append(
                        f"Feature {idx}: could not repair ({exc}). Skipped."
                    )
                    continue
            else:
                report["warnings"].append(
                    f"Feature {idx}: invalid geometry ({reason})."
                )

        # De-duplicate by geometry WKT hash
        geom_hash = shp.wkt
        if geom_hash in seen_hashes:
            report["stats"]["duplicates"] += 1
            if auto_repair:
                continue
        seen_hashes.add(geom_hash)

        cleaned_features.append({
            "type": "Feature",
            "geometry": mapping(shp) if auto_repair else geom,
            "properties": dict(props),
        })

    report["stats"]["valid_geom"] = len(cleaned_features)
    report["repaired_geojson"] = {
        "type": "FeatureCollection",
        "features": cleaned_features,
    }
    # Valid iff we produced at least one feature and no hard errors.
    report["valid"] = bool(cleaned_features) and not report["errors"]
    return report
