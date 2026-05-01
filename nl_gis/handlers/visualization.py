"""Visualization handlers (v2.1 Plan 11).

Backend tool handlers for advanced visualization:

- choropleth_map: classify a numeric attribute into buckets and return a
  per-feature color map (no frontend dependency for the data; the
  rendering frontend reads `styleMap` and `legendData`).
- chart: aggregate attributes into bar/pie/histogram/scatter datasets in
  Chart.js-compatible shape.
- animate_layer: group features by a temporal attribute into time steps.
- visualize_3d: compute per-feature heights for 3D extrusion.

These handlers are pure-Python and require only `numpy`. They do not
mutate any layer in `state.layer_store`. They produce a structured
response that the frontend can render.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from nl_gis.handlers import _get_layer_snapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Color ramps
# ---------------------------------------------------------------------------

# ColorBrewer-inspired palettes. Sequential = light->dark single hue.
# Diverging = dark / light midpoint / dark. Qualitative = distinct hues.
_SEQUENTIAL_5 = ["#feebe2", "#fbb4b9", "#f768a1", "#c51b8a", "#7a0177"]
_DIVERGING_5 = ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c"]
_QUALITATIVE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _interpolate(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((
        r1 + (r2 - r1) * t,
        g1 + (g2 - g1) * t,
        b1 + (b2 - b1) * t,
    ))


def _generate_color_ramp(ramp: str | list, num_classes: int) -> list[str]:
    """Generate `num_classes` hex colors from a named ramp or custom list."""
    if isinstance(ramp, list) and ramp:
        # Custom: cycle/truncate to fit num_classes
        if len(ramp) >= num_classes:
            # Pick evenly spaced indices so we span the user's full ramp.
            indices = np.linspace(0, len(ramp) - 1, num_classes).astype(int)
            return [ramp[i] for i in indices]
        # Linearly interpolate the custom ramp to num_classes
        result = []
        for i in range(num_classes):
            t = i / max(1, num_classes - 1)
            # Position in the source ramp
            src_t = t * (len(ramp) - 1)
            lo = int(np.floor(src_t))
            hi = min(len(ramp) - 1, lo + 1)
            local_t = src_t - lo
            result.append(_interpolate(ramp[lo], ramp[hi], local_t))
        return result

    if not isinstance(ramp, str):
        ramp = "sequential"
    name = ramp.lower()

    if name == "qualitative":
        # Cycle the categorical palette
        return [_QUALITATIVE[i % len(_QUALITATIVE)] for i in range(num_classes)]

    if name == "diverging":
        # Anchor on diverging palette ends + middle, interpolate linearly
        anchors = _DIVERGING_5
    else:
        anchors = _SEQUENTIAL_5

    if num_classes <= 1:
        return [anchors[len(anchors) // 2]]

    result = []
    for i in range(num_classes):
        t = i / (num_classes - 1)
        idx = t * (len(anchors) - 1)
        lo = int(np.floor(idx))
        hi = min(len(anchors) - 1, lo + 1)
        local = idx - lo
        result.append(_interpolate(anchors[lo], anchors[hi], local))
    return result


# ---------------------------------------------------------------------------
# Class-break methods
# ---------------------------------------------------------------------------

def _class_breaks(
    values: np.ndarray, method: str, num_classes: int,
    manual: list[float] | None = None,
) -> list[float]:
    """Return monotonically increasing class breaks of length num_classes+1.

    Falls back to equal_interval if the chosen method cannot be computed
    (e.g. all values identical → degenerate breaks).
    """
    method = (method or "quantile").lower()
    if method == "manual":
        if not manual or len(manual) < 2:
            raise ValueError("manual breaks require >= 2 values")
        return sorted(float(v) for v in manual)

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("no numeric values to classify")

    vmin = float(np.min(finite))
    vmax = float(np.max(finite))
    if vmin == vmax:
        # Degenerate: single value. Spread breaks symmetrically.
        return [vmin] + [vmin] * num_classes

    if method == "equal_interval":
        return list(np.linspace(vmin, vmax, num_classes + 1))

    if method == "natural_breaks":
        try:
            import jenkspy  # type: ignore[import-not-found]
        except Exception:
            logger.info("jenkspy not installed; falling back to quantile")
            method = "quantile"
        else:
            try:
                breaks = jenkspy.jenks_breaks(finite.tolist(), n_classes=num_classes)
                return list(breaks)
            except Exception:
                logger.info("jenkspy failed; falling back to quantile", exc_info=True)
                method = "quantile"

    if method == "quantile":
        qs = np.linspace(0, 100, num_classes + 1)
        breaks = np.percentile(finite, qs)
        # Ensure strictly non-decreasing (percentile can repeat)
        breaks = np.maximum.accumulate(breaks)
        return list(breaks)

    raise ValueError(f"unknown classification method: {method}")


def _classify_values(values: np.ndarray, breaks: list[float]) -> list[int | None]:
    """Assign each value to a class index in [0, len(breaks)-1).

    Returns None for non-finite values. Values equal to the last break go
    in the last class (closed interval).
    """
    out: list[int | None] = []
    upper_idx = len(breaks) - 2
    for v in values:
        if not np.isfinite(v):
            out.append(None)
            continue
        # Bisect: first break greater than v
        idx = int(np.searchsorted(breaks, v, side="right")) - 1
        if idx < 0:
            idx = 0
        elif idx > upper_idx:
            idx = upper_idx
        out.append(idx)
    return out


# ---------------------------------------------------------------------------
# choropleth_map
# ---------------------------------------------------------------------------

def handle_choropleth_map(params: dict, layer_store: dict | None) -> dict:
    """Classify a numeric attribute and return per-feature colors."""
    layer_name = params.get("layer_name")
    attribute = params.get("attribute")
    if not layer_name:
        return {"error": "layer_name is required"}
    if not attribute:
        return {"error": "attribute is required"}

    method = params.get("method", "quantile")
    num_classes = int(params.get("num_classes", 5))
    if num_classes < 2:
        return {"error": "num_classes must be >= 2"}
    if num_classes > 9:
        return {"error": "num_classes must be <= 9"}

    color_ramp = params.get("color_ramp", "sequential")
    manual_breaks = params.get("breaks")

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' is empty"}

    # Extract numeric values per feature; track non-numeric/missing.
    raw_values: list[float] = []
    for f in features:
        v = (f.get("properties") or {}).get(attribute)
        try:
            if v is None or v == "":
                raw_values.append(float("nan"))
            else:
                raw_values.append(float(v))
        except (TypeError, ValueError):
            raw_values.append(float("nan"))

    values = np.array(raw_values, dtype=float)
    if not np.any(np.isfinite(values)):
        return {"error": f"attribute '{attribute}' has no numeric values"}

    try:
        breaks = _class_breaks(values, method, num_classes, manual=manual_breaks)
    except ValueError as exc:
        return {"error": str(exc)}

    colors = _generate_color_ramp(color_ramp, num_classes)
    class_idx = _classify_values(values, breaks)

    style_map = {}
    legend_entries = []
    counts = [0] * num_classes
    missing = 0
    for i, idx in enumerate(class_idx):
        if idx is None:
            missing += 1
            continue
        style_map[i] = colors[idx]
        counts[idx] += 1

    for i in range(num_classes):
        legend_entries.append({
            "color": colors[i],
            "min": float(breaks[i]),
            "max": float(breaks[i + 1]),
            "count": counts[i],
            "label": f"{breaks[i]:.2f} – {breaks[i+1]:.2f}",
        })

    return {
        "action": "choropleth",
        "layer_name": layer_name,
        "attribute": attribute,
        "method": method,
        "breaks": [float(b) for b in breaks],
        "colors": colors,
        "styleMap": style_map,
        "missing_count": missing,
        "feature_count": len(features),
        "legendData": {
            "type": "choropleth",
            "title": f"{layer_name} — {attribute}",
            "entries": legend_entries,
        },
    }


# ---------------------------------------------------------------------------
# chart
# ---------------------------------------------------------------------------

def _coerce_numeric(values: list[Any]) -> list[float]:
    out = []
    for v in values:
        try:
            if v is None or v == "":
                continue
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def handle_chart(params: dict, layer_store: dict | None) -> dict:
    """Produce a Chart.js-compatible dataset from a layer."""
    layer_name = params.get("layer_name")
    chart_type = (params.get("chart_type") or "bar").lower()
    attribute = params.get("attribute")
    if not layer_name:
        return {"error": "layer_name is required"}
    if chart_type not in {"bar", "pie", "histogram", "scatter"}:
        return {"error": f"chart_type must be one of bar|pie|histogram|scatter (got {chart_type!r})"}
    if not attribute:
        return {"error": "attribute is required"}

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' is empty"}

    props = [(f.get("properties") or {}) for f in features]

    if chart_type in {"bar", "pie"}:
        group_by = params.get("group_by") or attribute
        agg = (params.get("aggregation") or "count").lower()
        groups: dict[Any, list[float]] = {}
        for p in props:
            key = p.get(group_by)
            if key is None or key == "":
                continue
            try:
                v = float(p.get(attribute)) if agg != "count" else 0.0
            except (TypeError, ValueError):
                if agg == "count":
                    v = 0.0
                else:
                    continue
            groups.setdefault(key, []).append(v)

        if not groups:
            return {"error": f"no values found for {group_by!r} grouping"}

        labels = sorted(groups.keys(), key=lambda k: str(k))
        if agg == "count":
            data = [len(groups[k]) for k in labels]
        elif agg == "sum":
            data = [float(np.sum(groups[k])) for k in labels]
        elif agg == "mean":
            data = [float(np.mean(groups[k])) if groups[k] else 0.0 for k in labels]
        else:
            return {"error": f"unknown aggregation: {agg}"}

        return {
            "action": "chart",
            "chart_type": chart_type,
            "layer_name": layer_name,
            "labels": [str(k) for k in labels],
            "datasets": [{"label": f"{agg}({attribute})", "data": data}],
            "title": f"{chart_type.title()} — {agg}({attribute}) by {group_by}",
        }

    if chart_type == "histogram":
        num_bins = int(params.get("num_bins", 10))
        if num_bins < 1:
            return {"error": "num_bins must be >= 1"}
        values = _coerce_numeric([p.get(attribute) for p in props])
        if not values:
            return {"error": f"attribute '{attribute}' has no numeric values"}
        counts, edges = np.histogram(values, bins=num_bins)
        labels = [f"{edges[i]:.2f}–{edges[i+1]:.2f}" for i in range(num_bins)]
        return {
            "action": "chart",
            "chart_type": "histogram",
            "layer_name": layer_name,
            "labels": labels,
            "edges": [float(e) for e in edges],
            "datasets": [{"label": f"count({attribute})", "data": [int(c) for c in counts]}],
            "title": f"Histogram — {attribute} ({num_bins} bins)",
        }

    # scatter
    x_attr = params.get("x_attribute")
    if not x_attr:
        return {"error": "scatter requires x_attribute"}
    points = []
    for p in props:
        try:
            x = p.get(x_attr)
            y = p.get(attribute)
            if x is None or y is None or x == "" or y == "":
                continue
            points.append({"x": float(x), "y": float(y)})
        except (TypeError, ValueError):
            continue
    if not points:
        return {"error": f"no numeric pairs for {x_attr}/{attribute}"}
    return {
        "action": "chart",
        "chart_type": "scatter",
        "layer_name": layer_name,
        "datasets": [{"label": f"{attribute} vs {x_attr}", "data": points}],
        "title": f"Scatter — {attribute} vs {x_attr}",
    }


# ---------------------------------------------------------------------------
# animate_layer
# ---------------------------------------------------------------------------

# Cap on time steps. Plans calls this out as a known degradation point —
# beyond this threshold we aggregate by binning unique timestamps.
MAX_ANIMATION_STEPS = 100


def _parse_time(raw: Any) -> Any:
    """Best-effort parse to a sortable comparable. Strings that look like
    dates remain strings and sort lexicographically; numbers stay numbers.
    Returns None on failure.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    return s


def handle_animate_layer(params: dict, layer_store: dict | None) -> dict:
    """Group features by a temporal attribute into ordered time steps."""
    layer_name = params.get("layer_name")
    time_attribute = params.get("time_attribute")
    if not layer_name:
        return {"error": "layer_name is required"}
    if not time_attribute:
        return {"error": "time_attribute is required"}

    interval_ms = int(params.get("interval_ms", 1000))
    if interval_ms < 50:
        interval_ms = 50
    cumulative = bool(params.get("cumulative", False))

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' is empty"}

    grouped: dict[Any, list[int]] = {}
    missing = 0
    for i, f in enumerate(features):
        t = _parse_time((f.get("properties") or {}).get(time_attribute))
        if t is None:
            missing += 1
            continue
        grouped.setdefault(t, []).append(i)

    if not grouped:
        return {"error": f"no parsable values for time_attribute '{time_attribute}'"}

    sorted_keys = sorted(grouped.keys(), key=lambda k: (isinstance(k, str), k))

    # Degradation when more than MAX_ANIMATION_STEPS unique values: bin them.
    binned = False
    if len(sorted_keys) > MAX_ANIMATION_STEPS:
        binned = True
        bin_size = (len(sorted_keys) + MAX_ANIMATION_STEPS - 1) // MAX_ANIMATION_STEPS
        new_steps: list[dict] = []
        for i in range(0, len(sorted_keys), bin_size):
            chunk = sorted_keys[i:i + bin_size]
            indices: list[int] = []
            for k in chunk:
                indices.extend(grouped[k])
            label = f"{chunk[0]} – {chunk[-1]}" if len(chunk) > 1 else str(chunk[0])
            new_steps.append({
                "time": str(chunk[0]),
                "label": label,
                "feature_indices": sorted(indices),
            })
        steps = new_steps
    else:
        steps = [
            {"time": str(k), "label": str(k), "feature_indices": sorted(grouped[k])}
            for k in sorted_keys
        ]

    return {
        "action": "animate",
        "layer_name": layer_name,
        "time_attribute": time_attribute,
        "interval_ms": interval_ms,
        "cumulative": cumulative,
        "missing_count": missing,
        "feature_count": len(features),
        "binned": binned,
        "time_steps": steps,
    }


# ---------------------------------------------------------------------------
# visualize_3d
# ---------------------------------------------------------------------------

def handle_visualize_3d(params: dict, layer_store: dict | None) -> dict:
    """Compute per-feature heights for 3D extrusion."""
    layer_name = params.get("layer_name")
    if not layer_name:
        return {"error": "layer_name is required"}

    height_attribute = params.get("height_attribute") or "height"
    height_multiplier = float(params.get("height_multiplier", 3.0))
    default_height = float(params.get("default_height", 10.0))

    features, err = _get_layer_snapshot(layer_store, layer_name)
    if err:
        return {"error": err}
    if not features:
        return {"error": f"Layer '{layer_name}' is empty"}

    annotated = []
    skipped_non_polygon = 0
    used_default = 0
    for f in features:
        geom = f.get("geometry") or {}
        gtype = geom.get("type")
        if gtype not in {"Polygon", "MultiPolygon"}:
            skipped_non_polygon += 1
            continue
        props = dict(f.get("properties") or {})
        raw = props.get(height_attribute)
        h_m: float | None = None
        try:
            if raw is not None and raw != "":
                h_m = float(raw)
        except (TypeError, ValueError):
            # Fall back to building:levels if obvious
            try:
                levels = float(props.get("building:levels"))
                h_m = levels * height_multiplier
            except (TypeError, ValueError):
                h_m = None
        if h_m is None:
            # Try building:levels as the canonical fallback
            try:
                levels = float(props.get("building:levels"))
                h_m = levels * height_multiplier
            except (TypeError, ValueError):
                h_m = default_height
                used_default += 1
        props["_height_m"] = float(h_m)
        annotated.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })

    if not annotated:
        return {"error": "no polygon geometries found for 3D visualization"}

    return {
        "action": "3d_buildings",
        "layer_name": layer_name,
        "height_attribute": height_attribute,
        "height_multiplier": height_multiplier,
        "default_height": default_height,
        "skipped_non_polygon": skipped_non_polygon,
        "used_default_count": used_default,
        "feature_count": len(annotated),
        "geojson": {"type": "FeatureCollection", "features": annotated},
    }
