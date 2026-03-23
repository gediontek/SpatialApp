"""Pydantic schemas for NL-to-GIS tool inputs and outputs."""

from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# Tool Input Schemas
# ============================================================

class GeocodeInput(BaseModel):
    """Input for geocoding a place name."""
    query: str = Field(..., description="Place name or address to geocode")


class FetchOSMInput(BaseModel):
    """Input for fetching OSM features."""
    feature_type: str = Field(..., description="OSM feature type: building, forest, water, park, grass, farmland, residential, commercial, industrial, road, river, lake")
    category_name: str = Field(..., description="Label to assign to fetched features")
    bbox: Optional[str] = Field(None, description="Bounding box as 'south,west,north,east'. If not provided, uses location.")
    location: Optional[str] = Field(None, description="Place name to geocode for bbox. Used if bbox not provided.")


class MapCommandInput(BaseModel):
    """Input for map navigation/control commands."""
    action: str = Field(..., description="Map action: pan, zoom, fit_bounds, change_basemap")
    lat: Optional[float] = Field(None, description="Latitude for pan action")
    lon: Optional[float] = Field(None, description="Longitude for pan action")
    zoom: Optional[int] = Field(None, description="Zoom level (1-20)")
    bbox: Optional[list] = Field(None, description="Bounding box [south, west, north, east] for fit_bounds")
    basemap: Optional[str] = Field(None, description="Basemap type: osm, satellite")


class CalculateAreaInput(BaseModel):
    """Input for area calculation."""
    layer_name: Optional[str] = Field(None, description="Name of layer to calculate area for")
    geometry: Optional[dict] = Field(None, description="GeoJSON geometry to calculate area of")


class MeasureDistanceInput(BaseModel):
    """Input for measuring distance between two points."""
    from_point: Optional[dict] = Field(None, description="Start point as {lat, lon} or null if from_location is used")
    to_point: Optional[dict] = Field(None, description="End point as {lat, lon} or null if to_location is used")
    from_location: Optional[str] = Field(None, description="Start location name (geocoded if from_point not provided)")
    to_location: Optional[str] = Field(None, description="End location name (geocoded if to_point not provided)")


# ============================================================
# Tool Output Schemas
# ============================================================

class GeocodeResult(BaseModel):
    """Output from geocoding."""
    lat: float
    lon: float
    display_name: str
    bbox: Optional[list] = None


class MapCommandResult(BaseModel):
    """Output from map command."""
    success: bool
    action: str
    description: str


class AreaResult(BaseModel):
    """Output from area calculation."""
    total_area_sq_m: float
    total_area_sq_km: float
    total_area_acres: float
    feature_count: int
    per_feature: Optional[list] = None


class DistanceResult(BaseModel):
    """Output from distance measurement."""
    distance_m: float
    distance_km: float
    distance_mi: float
    from_name: Optional[str] = None
    to_name: Optional[str] = None
