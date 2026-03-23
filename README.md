# Spatial Labeler

A web-based spatial labeling tool built with Flask and Leaflet.js, allowing users to upload raster images, draw annotations, and fetch OpenStreetMap (OSM) data.

## Features

- **Raster Upload**: Upload GeoTIFF images and overlay them on the map.
- **Drawing Tools**: Draw polygons, rectangles, and circles with customizable categories and colors.
- **OSM Data Fetching**: Query and display OSM data based on specified keys and values.
- **Annotation Management**: Save, view, clear, and finalize annotations.
- **Responsive UI**: Sidebar with controls and a table view for annotations.
- **Logging**: Comprehensive logging for debugging and monitoring.

## Installation

1. **Clone the repository**:

    ```bash
    git clone https://github.com/yourusername/SpatialApp.git
    cd SpatialApp
    ```

2. **Create a virtual environment**:

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3. **Install dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

4. **Initialize `annotations.geojson`**:

    Ensure that `labels/annotations.geojson` exists and is properly formatted. If not, the application will initialize it automatically.

5. **Run the application**:

    ```bash
    python app.py
    ```

6. **Access the application**:

    Open your browser and navigate to `http://127.0.0.1:5000/`.

## Folder Structure


## Usage

1. **Upload Raster**:
   - Use the upload form in the sidebar to upload a GeoTIFF image.
   - The image will be overlaid on the map, and the map view will adjust to fit the image bounds.

2. **Draw Annotations**:
   - Select drawing tools from the map toolbar to create annotations (polygons, rectangles, circles).
   - Assign categories and colors as needed.
   - Annotations are saved automatically and displayed in the annotations table.

3. **Fetch OSM Data**:
   - Input key and value parameters (e.g., `key: building`, `key_value: yes`) to fetch relevant OSM data within the current map bounds.
   - Fetched data will be added as annotations and displayed on the map.

4. **Manage Annotations**:
   - **Clear**: Remove all current annotations.
   - **Open Saved**: View saved annotations in a new tab.
   - **Finalize**: Save all annotations permanently (creates a backup).

## Logging

- **Log File**: All logs are stored in `logs/app.log`.
- **Logging Levels**:
  - **INFO**: General information about application events.
  - **DEBUG**: Detailed debugging information.
  - **WARNING**: Alerts about potential issues.
  - **ERROR**: Errors that occur during application runtime.

## License

[MIT](LICENSE)

## Acknowledgements

- [Flask](https://flask.palletsprojects.com/)
- [Leaflet.js](https://leafletjs.com/)
- [Leaflet.draw](https://leaflet.github.io/Leaflet.draw/)
- [OpenStreetMap](https://www.openstreetmap.org/)
- [Rasterio](https://rasterio.readthedocs.io/)
- [GeoPandas](https://geopandas.org/)
