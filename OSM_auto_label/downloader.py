"""
OSM data download utilities using osmnx.

Provides functions to download landuse and natural polygons from OpenStreetMap.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import geopandas as gpd
import pandas as pd

try:
    import osmnx as ox
except ImportError:
    ox = None

# Configure module logger
logger = logging.getLogger(__name__)


class DownloadError(Exception):
    """Raised when OSM data download fails."""
    pass


# Default tags for landcover classification
DEFAULT_LANDUSE_TAGS: Dict[str, bool] = {
    "landuse": True,
}

DEFAULT_NATURAL_TAGS: Dict[str, bool] = {
    "natural": True,
}

# Common city/region examples
EXAMPLE_PLACES = {
    "bucharest": "Bucharest, Romania",
    "cluj": "Cluj-Napoca, Romania",
    "timisoara": "Timișoara, Romania",
    "brasov": "Brașov, Romania",
    "constanta": "Constanța, Romania",
    "paris": "Paris, France",
    "london": "London, UK",
    "berlin": "Berlin, Germany",
    "amsterdam": "Amsterdam, Netherlands",
    "rome": "Rome, Italy",
}

# Default data directories (relative to package root)
def _get_data_dir() -> Path:
    """Get the data directory path."""
    # data folder is in the same directory as this file
    return Path(__file__).parent / "data"

def _get_raw_dir() -> Path:
    """Get the raw data directory path."""
    return _get_data_dir() / "raw"

def _get_classified_dir() -> Path:
    """Get the classified data directory path."""
    return _get_data_dir() / "classified"

def _place_to_filename(place: str) -> str:
    """Convert a place name to a valid filename."""
    # Take first part before comma, lowercase, replace spaces with underscores
    name = place.split(",")[0].strip().lower()
    # Remove special characters
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s]+', '_', name)
    return name


def _check_osmnx() -> None:
    """Check if osmnx is installed."""
    if ox is None:
        raise ImportError(
            "osmnx is required for downloading OSM data. "
            "Install it with: pip install osmnx"
        )


def download_landuse(
    place: str,
    tags: Optional[Dict[str, bool]] = None,
    timeout: int = 180,
) -> gpd.GeoDataFrame:
    """
    Download landuse polygons for a place.

    Args:
        place: Place name (e.g., "Bucharest, Romania")
        tags: OSM tags to download (default: {"landuse": True})
        timeout: Request timeout in seconds

    Returns:
        GeoDataFrame with landuse polygons

    Raises:
        DownloadError: If download fails
    """
    _check_osmnx()

    if tags is None:
        tags = DEFAULT_LANDUSE_TAGS.copy()

    logger.info(f"Downloading landuse data for: {place}")
    logger.debug(f"Tags: {tags}")

    try:
        ox.settings.timeout = timeout
        gdf = ox.features_from_place(place, tags=tags)

        # Filter to polygons only
        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

        logger.info(f"Downloaded {len(gdf)} landuse features")
        return gdf

    except Exception as e:
        raise DownloadError(f"Failed to download landuse data: {e}") from e


def download_natural(
    place: str,
    tags: Optional[Dict[str, bool]] = None,
    timeout: int = 180,
) -> gpd.GeoDataFrame:
    """
    Download natural polygons for a place.

    Args:
        place: Place name (e.g., "Bucharest, Romania")
        tags: OSM tags to download (default: {"natural": True})
        timeout: Request timeout in seconds

    Returns:
        GeoDataFrame with natural polygons

    Raises:
        DownloadError: If download fails
    """
    _check_osmnx()

    if tags is None:
        tags = DEFAULT_NATURAL_TAGS.copy()

    logger.info(f"Downloading natural data for: {place}")
    logger.debug(f"Tags: {tags}")

    try:
        ox.settings.timeout = timeout
        gdf = ox.features_from_place(place, tags=tags)

        # Filter to polygons only
        gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

        logger.info(f"Downloaded {len(gdf)} natural features")
        return gdf

    except Exception as e:
        raise DownloadError(f"Failed to download natural data: {e}") from e


def download_osm_landcover(
    place: str,
    include_landuse: bool = True,
    include_natural: bool = True,
    timeout: int = 180,
    output_path: Optional[str | Path] = None,
    save_raw: bool = True,
) -> gpd.GeoDataFrame:
    """
    Download combined landuse and natural polygons for landcover classification.

    Args:
        place: Place name (e.g., "Bucharest, Romania", "Cluj-Napoca, Romania")
        include_landuse: Whether to include landuse tags
        include_natural: Whether to include natural tags
        timeout: Request timeout in seconds
        output_path: Optional custom path to save (overrides auto-save)
        save_raw: If True, automatically saves to data/raw/{place}.geojson

    Returns:
        GeoDataFrame with landuse and natural columns, ready for classification

    Raises:
        DownloadError: If download fails

    Example:
        >>> gdf = download_osm_landcover("Paris, France")
        >>> # Saved to data/raw/paris.geojson
    """
    _check_osmnx()

    logger.info("=" * 50)
    logger.info(f"Downloading OSM landcover data for: {place}")
    logger.info("=" * 50)

    gdfs = []

    # Download landuse
    if include_landuse:
        try:
            gdf_landuse = download_landuse(place, timeout=timeout)
            if len(gdf_landuse) > 0:
                gdfs.append(gdf_landuse)
        except DownloadError as e:
            logger.warning(f"{e}")

    # Download natural
    if include_natural:
        try:
            gdf_natural = download_natural(place, timeout=timeout)
            if len(gdf_natural) > 0:
                gdfs.append(gdf_natural)
        except DownloadError as e:
            logger.warning(f"{e}")

    if not gdfs:
        raise DownloadError(f"No data downloaded for {place}")

    # Combine datasets
    logger.info("Combining datasets...")
    gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))

    # Keep only relevant columns
    cols_to_keep = ["geometry"]
    if "landuse" in gdf.columns:
        cols_to_keep.append("landuse")
    if "natural" in gdf.columns:
        cols_to_keep.append("natural")

    # Add missing columns if needed
    if "landuse" not in gdf.columns:
        gdf["landuse"] = None
    if "natural" not in gdf.columns:
        gdf["natural"] = None

    gdf = gdf[["landuse", "natural", "geometry"]].copy()

    # Remove duplicates based on geometry
    gdf = gdf.drop_duplicates(subset=["geometry"])

    # Filter to polygons only (safety check)
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

    # Convert MultiPolygon to Polygon if possible
    def to_polygon(geom):
        if geom is None:
            return None
        if geom.geom_type == "MultiPolygon":
            if geom.is_empty or len(geom.geoms) == 0:
                return None
            # Return largest polygon
            return max(geom.geoms, key=lambda g: g.area)
        return geom

    gdf["geometry"] = gdf["geometry"].apply(to_polygon)
    # Remove rows with None geometry after conversion
    gdf = gdf[gdf["geometry"].notna()].copy()

    logger.info(f"Total features: {len(gdf)}")
    logger.info(f"Unique landuse tags: {gdf['landuse'].nunique()}")
    logger.info(f"Unique natural tags: {gdf['natural'].nunique()}")

    # Determine save path
    if output_path:
        save_path = Path(output_path)
    elif save_raw:
        filename = _place_to_filename(place) + ".geojson"
        save_path = _get_raw_dir() / filename
    else:
        save_path = None

    # Save as GeoJSON
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(save_path, driver="GeoJSON")
        logger.info(f"Saved to: {save_path}")

    return gdf


def download_by_bbox(
    north: float,
    south: float,
    east: float,
    west: float,
    include_landuse: bool = True,
    include_natural: bool = True,
    timeout: int = 180,
    output_path: Optional[str | Path] = None,
) -> gpd.GeoDataFrame:
    """
    Download OSM landcover data by bounding box.

    Args:
        north: Northern latitude
        south: Southern latitude
        east: Eastern longitude
        west: Western longitude
        include_landuse: Whether to include landuse tags
        include_natural: Whether to include natural tags
        timeout: Request timeout in seconds
        output_path: Optional path to save as shapefile

    Returns:
        GeoDataFrame with landuse and natural columns

    Example:
        >>> # Small area in Cluj-Napoca
        >>> gdf = download_by_bbox(
        ...     north=46.78, south=46.76,
        ...     east=23.60, west=23.58
        ... )
    """
    _check_osmnx()

    logger.info("=" * 50)
    logger.info(f"Downloading OSM data for bbox:")
    logger.info(f"  N: {north}, S: {south}, E: {east}, W: {west}")
    logger.info("=" * 50)

    ox.settings.timeout = timeout
    gdfs = []

    try:
        if include_landuse:
            logger.info("Downloading landuse...")
            gdf_landuse = ox.features_from_bbox(
                bbox=(north, south, east, west),
                tags=DEFAULT_LANDUSE_TAGS,
            )
            gdf_landuse = gdf_landuse[
                gdf_landuse.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            ]
            gdfs.append(gdf_landuse)
            logger.info(f"  Got {len(gdf_landuse)} landuse features")

        if include_natural:
            logger.info("Downloading natural...")
            gdf_natural = ox.features_from_bbox(
                bbox=(north, south, east, west),
                tags=DEFAULT_NATURAL_TAGS,
            )
            gdf_natural = gdf_natural[
                gdf_natural.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
            ]
            gdfs.append(gdf_natural)
            logger.info(f"  Got {len(gdf_natural)} natural features")

    except Exception as e:
        raise DownloadError(f"Failed to download data: {e}") from e

    if not gdfs:
        raise DownloadError("No data downloaded")

    # Combine and clean
    gdf = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))

    if "landuse" not in gdf.columns:
        gdf["landuse"] = None
    if "natural" not in gdf.columns:
        gdf["natural"] = None

    gdf = gdf[["landuse", "natural", "geometry"]].copy()
    gdf = gdf.drop_duplicates(subset=["geometry"])

    # Convert MultiPolygon to Polygon
    def to_polygon(geom):
        if geom is None:
            return None
        if geom.geom_type == "MultiPolygon":
            if geom.is_empty or len(geom.geoms) == 0:
                return None
            return max(geom.geoms, key=lambda g: g.area)
        return geom

    gdf["geometry"] = gdf["geometry"].apply(to_polygon)
    gdf = gdf[gdf["geometry"].notna()].copy()
    gdf = gdf[gdf.geometry.geom_type == "Polygon"]

    logger.info(f"Total features: {len(gdf)}")

    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        gdf.to_file(output_path)
        logger.info(f"Saved to: {output_path}")

    return gdf


def list_example_places() -> Dict[str, str]:
    """
    List example places that can be used for download.

    Returns:
        Dictionary of short name -> full place name
    """
    logger.info("Example places:")
    for short, full in EXAMPLE_PLACES.items():
        logger.info(f"  {short}: {full}")
    return EXAMPLE_PLACES


def list_raw_data() -> List[Path]:
    """
    List all raw GeoJSON files in data/raw.

    Returns:
        List of file paths
    """
    raw_dir = _get_raw_dir()
    if not raw_dir.exists():
        return []
    files = sorted(raw_dir.glob("*.geojson"))
    return files


def list_classified_data() -> List[Path]:
    """
    List all classified GeoJSON files in data/classified.

    Returns:
        List of file paths
    """
    classified_dir = _get_classified_dir()
    if not classified_dir.exists():
        return []
    files = sorted(classified_dir.glob("*.geojson"))
    return files


def load_raw(name: str) -> gpd.GeoDataFrame:
    """
    Load raw data by name (without extension).

    Args:
        name: Name of the file (e.g., "paris" for paris.geojson)

    Returns:
        GeoDataFrame
    """
    path = _get_raw_dir() / f"{name}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"Raw data not found: {path}")
    return gpd.read_file(path)


def load_classified(name: str) -> gpd.GeoDataFrame:
    """
    Load classified data by name (without extension).

    Args:
        name: Name of the file (e.g., "paris" for paris.geojson)

    Returns:
        GeoDataFrame
    """
    path = _get_classified_dir() / f"{name}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"Classified data not found: {path}")
    return gpd.read_file(path)


def get_raw_path(name: str) -> Path:
    """Get path for a raw data file."""
    return _get_raw_dir() / f"{name}.geojson"


def get_classified_path(name: str) -> Path:
    """Get path for a classified data file."""
    return _get_classified_dir() / f"{name}.geojson"
