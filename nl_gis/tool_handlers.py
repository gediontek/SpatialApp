"""Backward-compatible re-export. All handlers now live in nl_gis.handlers."""
# These imports are needed so that existing test patches like
# @patch("nl_gis.tool_handlers.requests.get") continue to work.
import requests  # noqa: F401
from services.cache import geocode_cache, overpass_cache  # noqa: F401
from services.rate_limiter import nominatim_limiter, overpass_limiter  # noqa: F401

from nl_gis.handlers import *  # noqa: F401,F403
from nl_gis.handlers import dispatch_tool, LAYER_PRODUCING_TOOLS  # explicit
from nl_gis.handlers import (  # explicit re-exports for private helpers
    _resolve_point,
    _resolve_point_from_object,
    _safe_geojson_to_shapely,
    _get_layer_snapshot,
    _get_layer_geometries,
    _osm_to_geojson,
    _classify_landcover_work,
    OSM_FEATURE_MAPPINGS,
)
from nl_gis.handlers.analysis import MAX_BUFFER_DISTANCE_M  # noqa: F401
