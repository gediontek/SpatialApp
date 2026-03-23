# OSM Auto Label

Automated landcover classification from OpenStreetMap data using word embeddings.

This tool downloads OSM landuse/natural polygon data, classifies tags into landcover categories using GloVe word vectors, and generates interactive map visualizations.

## Features

- Download OSM data via osmnx (by place name or bounding box)
- Classify OSM tags into 7 landcover categories using semantic similarity
- Generate interactive Leaflet maps with multiple tile layers
- Export classified data as shapefiles

## Landcover Categories

| Category | Description |
|----------|-------------|
| builtup_area | Residential, commercial, industrial, construction |
| water | Water bodies, wetlands, reservoirs |
| bare_earth | Beaches, sand, brownfield |
| forest | Forests, woods, heath |
| farmland | Agricultural land, allotments |
| grassland | Grass, meadows, parks, cemeteries |
| aquaculture | Fish farms, aquaculture facilities |

## Installation

### Option A: Using venv (Python virtual environment)

```bash
# Navigate to project directory
cd /path/to/OSM

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows

# Install dependencies
pip install -r OSM_auto_label/requirements.txt
```

### Option B: Using conda

```bash
# Create conda environment
conda create -n geo_env python=3.10
conda activate geo_env

# Install dependencies
pip install -r OSM_auto_label/requirements.txt
```

### Verify installation

```bash
python -c "from OSM_auto_label import download_osm_landcover; print('Installation successful!')"
```

## Usage

### Quick Start

```bash
# Activate your environment
source venv/bin/activate  # or: conda activate geo_env

# Download and classify a city (auto-saves to data/ folders)
python -c "
from OSM_auto_label import download_osm_landcover, OSMLandcoverClassifier

gdf = download_osm_landcover('Paris, France')
classifier = OSMLandcoverClassifier()
gdf_classified = classifier.process_geodataframe(gdf, name='paris')
"

# Launch the interactive viewer app
python -m OSM_auto_label.app
# Open http://127.0.0.1:5000 in your browser
```

### Python API

```python
from OSM_auto_label import (
    download_osm_landcover,
    OSMLandcoverClassifier,
    load_classified,
    list_raw_data,
    list_classified_data,
)

# 1. Download OSM data (auto-saves to data/raw/paris.geojson)
gdf = download_osm_landcover("Paris, France")

# 2. Classify landcover (auto-saves to data/classified/paris.geojson)
classifier = OSMLandcoverClassifier()
gdf_classified = classifier.process_geodataframe(gdf, name="paris")

# 3. List available data
list_raw_data()        # [Path('data/raw/paris.geojson'), ...]
list_classified_data() # [Path('data/classified/paris.geojson'), ...]

# 4. Load existing classified data
gdf = load_classified("paris")
```

### Interactive Viewer App

Launch the web-based viewer to explore your data:

```bash
python -m OSM_auto_label.app
```

Then open http://127.0.0.1:5000 in your browser. Features:
- Sidebar listing all raw and classified data files
- Click any file to load it on the map
- Multiple tile layers (OpenStreetMap, Satellite, Terrain)
- Color-coded categories with legend for classified data
- Tooltips and popups on hover/click

### Command Line (with existing shapefile)

```bash
python -m OSM_auto_label.main -i input.shp -o output.shp -m map.html
```

Options:
- `-i, --input`: Input shapefile path (required)
- `-o, --output`: Output classified shapefile path (required)
- `-m, --map`: Output HTML map path (optional)
- `--cluster`: Run clustering analysis
- `--category-layers`: Create separate map layers per category
- `-q, --quiet`: Suppress output

### Download by Bounding Box

```python
from OSM_auto_label import download_by_bbox

# Download a specific area
gdf = download_by_bbox(
    north=46.78, south=46.76,
    east=23.60, west=23.58
)
```

## Data Directory Structure

Data is automatically organized into folders:

```
OSM_auto_label/
├── data/
│   ├── raw/              # Downloaded OSM data (GeoJSON)
│   │   └── paris.geojson
│   └── classified/       # Classified output (GeoJSON)
│       └── paris.geojson
├── venv/                 # Virtual environment
└── *.py                  # Package modules
```

## Customization

### Custom Categories

```python
custom_categories = {
    "urban": ["residential", "commercial", "industrial"],
    "vegetation": ["forest", "grass", "meadow"],
    "water": ["water", "wetland"],
}

classifier = OSMLandcoverClassifier(seed_categories=custom_categories)
```

### Custom Colors

```python
custom_colors = {
    "urban": "#FF6B6B",
    "vegetation": "#4ECDC4",
    "water": "#45B7D1",
}

visualizer = LandcoverMapVisualizer(colors=custom_colors)
```

### Configuration

All default values are in `config.py`:
- `SEED_CATEGORIES`: Category definitions
- `TAG_REPLACEMENTS`: Mappings for unmapped OSM tags
- `CATEGORY_COLORS`: Visualization colors
- `CATEGORY_PRIORITY`: Priority for overlapping features

## Project Structure

```
OSM_auto_label/           # Project root
├── data/
│   ├── raw/              # Raw OSM downloads (GeoJSON)
│   └── classified/       # Classified outputs (GeoJSON)
├── venv/                 # Virtual environment
├── __init__.py           # Package exports
├── config.py             # Configuration constants
├── classifier.py         # OSMLandcoverClassifier
├── visualizer.py         # LandcoverMapVisualizer
├── downloader.py         # osmnx download utilities
├── app.py                # Interactive web viewer
├── main.py               # CLI entry point
├── example.ipynb         # Jupyter notebook example
├── requirements.txt      # Dependencies
└── README.md             # This file
```

## How It Works

1. **Download**: Fetches landuse and natural polygon features from OSM via Overpass API
2. **Preprocess**: Filters to polygons, merges natural tags into landuse column
3. **Embed**: Maps OSM tags to GloVe word vectors (300-dimensional)
4. **Classify**: Computes category centroids from seed words, assigns each tag to nearest category
5. **Export**: Saves classified shapefile and interactive HTML map

## Requirements

- Python 3.9+
- See `requirements.txt` for full dependencies

## Example Places

```python
from OSM_auto_label import list_example_places

list_example_places()
# bucharest: Bucharest, Romania
# cluj: Cluj-Napoca, Romania
# timisoara: Timișoara, Romania
# brasov: Brașov, Romania
# constanta: Constanța, Romania
```

## Troubleshooting

### "No module named 'geopandas'"
Install dependencies: `pip install -r requirements.txt`

### "osmnx is required"
Install osmnx: `pip install osmnx`

### Import error with relative imports
Don't run module files directly. Use:
```bash
python -m OSM_auto_label.main ...
```
or import in Python:
```python
from OSM_auto_label import ...
```

### Download timeout
For large areas, increase timeout:
```python
gdf = download_osm_landcover("Romania", timeout=300)
```
Or use a smaller area (city instead of country).

## License

MIT
