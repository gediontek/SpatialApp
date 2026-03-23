"""
Configuration constants for OSM Landcover Classification.

All hardcoded values are centralized here for easy modification.
"""

from typing import Any, Dict, List

# Word embedding model to use
WORD_EMBEDDING_MODEL: str = "glove-wiki-gigaword-300"

# Words to exclude from embedding vocabulary
EXCLUDED_WORDS: List[str] = ["yes", "relis"]

# Replacements for OSM tags not found in word embeddings
TAG_REPLACEMENTS: Dict[str, str] = {
    "traffic_island": "road",
    "bare_rock": "rock",
    "building_site": "construction",
    "tree_row": "tree",
    "farmyard": "farmland",
    "animal_keeping": "barn",
    "greenhouse_horticulture": "greenhouse",
    "plant_nursery": "greenhouse",
    "recreation_ground": "recreation",
    "village_green": "grass",
    "winter_sports": "recreation",
}

# Seed categories for classification
# Each category contains representative OSM tags used to compute category centroids
SEED_CATEGORIES: Dict[str, List[str]] = {
    "builtup_area": [
        "garages",
        "education",
        "landfill",
        "industrial",
        "religious",
        "military",
        "commercial",
        "railway",
        "residential",
        "retail",
        "construction",
        "institutional",
        "civic",
        "government",
        "hospital",
        "school",
        "university",
        "parking",
        "depot",
        "port",
        "airport",
        "quarry",
    ],
    "water": [
        "water",
        "basin",
        "wetland",
        "salt_pond",
        "bay",
        "reservoir",
    ],
    "bare_earth": [
        "beach",
        "brownfield",
        "sand",
        "shingle",
    ],
    "forest": [
        "forest",
        "heath",
        "wood",
    ],
    "farmland": [
        "allotments",
        "farmland",
        "farmyard",
        "scrub",
    ],
    "grassland": [
        "flowerbed",
        "grass",
        "grassland",
        "plant_nursery",
        "orchard",
        "village_green",
        "shrubbery",
        "cemetery",
        "greenfield",
        "greenhouse_horticulture",
        "meadow",
        "recreation_ground",
        "park",
        "garden",
        "playground",
        "pitch",
        "golf_course",
    ],
    "aquaculture": [
        "aquaculture",
    ],
}

# Priority values for categories (higher = more priority in overlaps)
CATEGORY_PRIORITY: Dict[str, int] = {
    "aquaculture": 5,
    "forest": 2,
    "farmland": 4,
    "builtup_area": 3,
    "bare_earth": 3,
    "water": 2,
    "grassland": 4,
}

# Priority overrides for specific tags
TAG_PRIORITY: Dict[str, int] = {
    "residential": 1,
    "commercial": 1,
    "industrial": 1,
}

# Color scheme for map visualization (hex colors)
CATEGORY_COLORS: Dict[str, str] = {
    "builtup_area": "#E31A1C",   # Red
    "water": "#1F78B4",          # Blue
    "bare_earth": "#A6CEE3",     # Light blue
    "forest": "#33A02C",         # Green
    "farmland": "#FFFF99",       # Yellow
    "grassland": "#B2DF8A",      # Light green
    "aquaculture": "#6A3D9A",    # Purple
}

# Default color for unknown categories
DEFAULT_COLOR: str = "#808080"  # Gray

# Columns to keep from input shapefile
SHAPEFILE_COLUMNS: List[str] = ["natural", "landuse", "geometry"]

# Clustering parameters
CLUSTERING_CONFIG: Dict[str, Any] = {
    "n_clusters": 10,
    "n_components": 6,
    "popularity_threshold": 0.001,
    "random_state": 0,
}

# Map visualization defaults
MAP_CONFIG: Dict[str, Any] = {
    "zoom_start": 12,
    "tiles": "OpenStreetMap",
    "fill_opacity": 0.6,
    "line_weight": 1,
    "line_color": "black",
}

# Logging configuration
LOGGING_CONFIG: Dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        },
        "simple": {
            "format": "%(levelname)s: %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "simple",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "OSM_auto_label": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}
