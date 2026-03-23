"""
OSM Auto Label - Automated landcover classification from OpenStreetMap data.

This package provides tools for:
- Downloading OSM landuse/natural data via osmnx
- Classifying tags into landcover categories using word embeddings
- Creating interactive map visualizations

Example usage:
    from OSM_auto_label import download_osm_landcover, OSMLandcoverClassifier

    # Download OSM data (auto-saves to data/raw/paris.geojson)
    gdf = download_osm_landcover("Paris, France")

    # Classify (auto-saves to data/classified/paris.geojson)
    classifier = OSMLandcoverClassifier()
    gdf_classified = classifier.process_geodataframe(gdf, name="paris")

    # Launch interactive app to explore data
    from OSM_auto_label.app import run_app
    run_app()
"""

from .classifier import (
    OSMLandcoverClassifier,
    WordEmbeddingError,
    DataLoadError,
    ClassificationError,
)
from .visualizer import (
    LandcoverMapVisualizer,
    VisualizationError,
    visualize_classification,
)
from .downloader import (
    download_osm_landcover,
    download_landuse,
    download_natural,
    download_by_bbox,
    list_example_places,
    list_raw_data,
    list_classified_data,
    load_raw,
    load_classified,
    get_raw_path,
    get_classified_path,
    DownloadError,
)
from . import config

__version__ = "1.0.0"
__all__ = [
    # Downloader
    "download_osm_landcover",
    "download_landuse",
    "download_natural",
    "download_by_bbox",
    "list_example_places",
    "list_raw_data",
    "list_classified_data",
    "load_raw",
    "load_classified",
    "get_raw_path",
    "get_classified_path",
    "DownloadError",
    # Classifier
    "OSMLandcoverClassifier",
    "WordEmbeddingError",
    "DataLoadError",
    "ClassificationError",
    # Visualizer
    "LandcoverMapVisualizer",
    "VisualizationError",
    "visualize_classification",
    # Config
    "config",
]
