"""Spatial context extraction — layer metadata, reference tracking, viewport hints.

This module provides library helpers used to enrich the LLM's view of the map
state. Helpers are CONDITIONALLY applied by the chat layer (only when the user's
message contains keywords that signal the context is relevant) rather than
unconditionally injected into every prompt — v2.1 Plan 02 showed that
unconditional prompt enrichment regresses Gemini 2.5 Flash.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Patterns that suggest the user is referring to something previously on the
# map. Scan is case-insensitive.
ANAPHORIC_PATTERNS = [
    "this", "that", "those", "these", "it",
    "the results", "the layer", "the same",
    "that area", "this region", "here",
    "them", "their",
]

# Keywords that signal the query needs attribute-level knowledge of the
# target layer. When any of these appear, chat.py should expand the
# metadata section beyond the default cap.
ATTRIBUTE_AWARE_KEYWORDS = {
    "color", "style", "filter", "highlight", "show only", "hide",
    "taller", "larger", "greater", "above", "below", "less than",
    "smaller", "over", "under", "between",
}


# ---------------------------------------------------------------------------
# Layer metadata extraction
# ---------------------------------------------------------------------------


def extract_layer_metadata(
    layer_name: str,
    geojson: dict,
    max_features_sample: int = 100,
    max_attributes: int = 20,
    max_samples_per_attribute: int = 5,
) -> dict:
    """Summarize a GeoJSON layer: count, geometry types, bbox, attribute schema.

    Samples attributes from the first `max_features_sample` features to stay fast
    on large layers. Caps attributes at `max_attributes` to limit prompt size.
    """
    features = geojson.get("features") if isinstance(geojson, dict) else None
    features = features or []
    count = len(features)

    meta = {
        "name": layer_name,
        "feature_count": count,
        "geometry_types": set(),
        "bbox": None,
        "attributes": {},
        "attributes_truncated": False,
    }

    if count == 0:
        return meta

    # Geometry types — fast scan, just string reads
    for f in features:
        g = f.get("geometry") if isinstance(f, dict) else None
        if g and isinstance(g, dict):
            t = g.get("type")
            if t:
                meta["geometry_types"].add(t)

    # Bounding box — try Shapely for correctness; fallback to coordinate scan.
    meta["bbox"] = _compute_bbox(features)

    # Attribute schema — sample from first N features.
    sample = features[:max_features_sample]
    attr_values: dict[str, list] = {}
    for f in sample:
        props = f.get("properties") if isinstance(f, dict) else None
        if not isinstance(props, dict):
            continue
        for k, v in props.items():
            if v is None:
                continue
            attr_values.setdefault(k, []).append(v)
            if len(attr_values) > max_attributes:
                # Don't let a pathological layer explode memory — stop collecting
                # NEW attribute keys once we hit the cap.
                break

    sorted_keys = list(attr_values.keys())
    if len(sorted_keys) > max_attributes:
        meta["attributes_truncated"] = True
        sorted_keys = sorted_keys[:max_attributes]

    for k in sorted_keys:
        values = attr_values[k]
        inferred_type = _infer_attr_type(values[0])
        unique = list({_safe_hashable(v) for v in values if v is not None})
        meta["attributes"][k] = {
            "type": inferred_type,
            "sample_values": unique[:max_samples_per_attribute],
            "unique_count": len(unique),
        }

    return meta


def _safe_hashable(v: Any) -> Any:
    """Return a hashable version of v for set dedup, or repr fallback."""
    try:
        hash(v)
        return v
    except TypeError:
        return repr(v)


def _infer_attr_type(v: Any) -> str:
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, (list, tuple)):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


def _compute_bbox(features: list) -> list | None:
    """Compute [south, west, north, east] from GeoJSON features.

    Tries shapely.unary_union for correctness; falls back to a manual coord
    scan if shapely chokes on mixed/invalid geometries.
    """
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union

        geoms = []
        for f in features:
            g = f.get("geometry") if isinstance(f, dict) else None
            if g:
                try:
                    geoms.append(shape(g))
                except Exception:
                    continue
        if not geoms:
            return None
        union = unary_union(geoms)
        if not hasattr(union, "bounds") or union.is_empty:
            return None
        minx, miny, maxx, maxy = union.bounds
        return [round(miny, 6), round(minx, 6), round(maxy, 6), round(maxx, 6)]
    except Exception:
        return _bbox_fallback(features)


def _bbox_fallback(features: list) -> list | None:
    """Manual coordinate scan when Shapely fails."""
    minx = miny = float("inf")
    maxx = maxy = float("-inf")

    def visit(coords):
        nonlocal minx, miny, maxx, maxy
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            x, y = coords[0], coords[1]
            if x < minx: minx = x
            if x > maxx: maxx = x
            if y < miny: miny = y
            if y > maxy: maxy = y
        else:
            for c in coords:
                visit(c)

    for f in features:
        g = f.get("geometry") if isinstance(f, dict) else None
        if not g:
            continue
        coords = g.get("coordinates")
        visit(coords)

    if minx == float("inf"):
        return None
    return [round(miny, 6), round(minx, 6), round(maxy, 6), round(maxx, 6)]


# ---------------------------------------------------------------------------
# Layer summary formatting
# ---------------------------------------------------------------------------


def format_layer_summary(metadata: dict, max_chars: int = 200) -> str:
    """Format one layer's metadata as a compact human-readable line."""
    name = metadata.get("name", "<unnamed>")
    count = metadata.get("feature_count", 0)
    geom_types = metadata.get("geometry_types") or set()
    geom = "/".join(sorted(geom_types)) if geom_types else "?"
    bbox = metadata.get("bbox")
    bbox_str = (
        f"bbox=[{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}]" if bbox else "bbox=?"
    )

    attrs = metadata.get("attributes") or {}
    attr_descs = []
    for k, info in list(attrs.items())[:5]:  # max 5 attrs in the summary line
        attr_descs.append(f"{k}({info.get('type', '?')}, {info.get('unique_count', 0)}u)")
    attr_str = ", ".join(attr_descs) if attr_descs else "no attrs"

    summary = f"{name} ({count} features, {geom}, {bbox_str}, attrs: {attr_str})"

    if len(summary) > max_chars:
        return summary[: max_chars - 3] + "..."
    return summary


# ---------------------------------------------------------------------------
# Reference tracker
# ---------------------------------------------------------------------------


@dataclass
class ReferenceEntry:
    turn: int
    type: str  # "layer" | "location" | "result"
    name: str
    metadata: dict = field(default_factory=dict)


class ReferenceTracker:
    """Ordered ring buffer of recent references the LLM might be pointing at.

    Used to resolve anaphors like 'those buildings', 'that area' to the
    concrete layer or location the user most likely means.
    """

    def __init__(self, capacity: int = 20):
        self._entries: deque[ReferenceEntry] = deque(maxlen=capacity)
        self.capacity = capacity

    def add(self, entry: ReferenceEntry) -> None:
        self._entries.append(entry)

    def get_recent(self, n: int = 3) -> list[ReferenceEntry]:
        return list(self._entries)[-n:]

    def all(self) -> list[ReferenceEntry]:
        return list(self._entries)

    def resolve(self, reference_text: str) -> ReferenceEntry | None:
        """Heuristic pattern-matching against recorded references.

        Returns None when the reference is ambiguous or no entry matches —
        the LLM makes the final call in that case.
        """
        if not reference_text or not self._entries:
            return None
        text = reference_text.lower()

        # (4) Specific: "the {substring of layer name}"
        for entry in reversed(self._entries):
            if entry.type != "layer":
                continue
            name_low = entry.name.lower()
            # Split underscore/hyphen-separated layer names into word tokens
            for token in re.split(r"[_\-\s]+", name_low):
                if token and len(token) > 2 and f"the {token}" in text:
                    return entry

        # (3) "that area" / "this region" / "here" -> last location or last layer
        if any(p in text for p in ("that area", "this region", "here", "this area")):
            for entry in reversed(self._entries):
                if entry.type == "location":
                    return entry
            # Fall back to most recent layer (its bbox approximates the area)
            for entry in reversed(self._entries):
                if entry.type == "layer":
                    return entry

        # (1)+(2) Generic anaphors -> most recent layer
        generic_hits = (
            "this layer", "that layer", "those", "these", "the results",
            "the layer", "the same", "them", "their",
        )
        if any(p in text for p in generic_hits):
            for entry in reversed(self._entries):
                if entry.type == "layer":
                    return entry

        # "it" — only when no stronger signal — still prefer most recent layer
        if re.search(r"\bit\b", text):
            for entry in reversed(self._entries):
                if entry.type == "layer":
                    return entry

        return None


# ---------------------------------------------------------------------------
# Viewport formatting
# ---------------------------------------------------------------------------


def format_viewport_hint(map_context: dict | None) -> str:
    """Return a compact hint string for the current map viewport, or ''."""
    if not isinstance(map_context, dict):
        return ""
    bounds = map_context.get("bounds")
    center = map_context.get("center")
    parts = []
    if isinstance(bounds, dict):
        s = bounds.get("south"); w = bounds.get("west")
        n = bounds.get("north"); e = bounds.get("east")
        if None not in (s, w, n, e):
            parts.append(f"viewport bbox=[{s},{w},{n},{e}]")
    if isinstance(center, dict):
        lat = center.get("lat"); lng = center.get("lng") or center.get("lon")
        if lat is not None and lng is not None:
            parts.append(f"center=({lat},{lng})")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Attribute access helpers (for handler validation)
# ---------------------------------------------------------------------------


def get_layer_attribute_names(
    layer_store: dict,
    layer_name: str,
    layer_lock=None,
) -> list[str]:
    """Return the sorted unique attribute names present on a layer.

    Empty list if the layer doesn't exist or has no features. Uses the
    supplied lock for thread-safe access when provided.
    """
    def _snapshot():
        return layer_store.get(layer_name)

    if layer_lock is not None:
        with layer_lock:
            layer = _snapshot()
    else:
        layer = _snapshot()

    if not isinstance(layer, dict):
        return []
    features = layer.get("features") or []
    keys: set[str] = set()
    for f in features[:200]:  # sample
        props = f.get("properties") if isinstance(f, dict) else None
        if isinstance(props, dict):
            keys.update(props.keys())
    return sorted(keys)


# ---------------------------------------------------------------------------
# Reference detection — light scanner for anaphoric terms
# ---------------------------------------------------------------------------


def contains_anaphor(message: str) -> bool:
    """Fast check: does this message contain any anaphoric reference?"""
    if not message:
        return False
    text = message.lower()
    return any(p in text for p in ANAPHORIC_PATTERNS)


def needs_attribute_context(message: str) -> bool:
    """Does this message need attribute-level knowledge of a layer?"""
    if not message:
        return False
    text = message.lower()
    return any(kw in text for kw in ATTRIBUTE_AWARE_KEYWORDS)
