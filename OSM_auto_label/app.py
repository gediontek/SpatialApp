"""
Interactive Visualizer App for OSM Landcover data.

A local web app with file browser, search, and OSM data fetching capabilities.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

import folium
from folium.plugins import Fullscreen, MiniMap, MousePosition

try:
    from flask import Flask, render_template_string, jsonify, request
except ImportError:
    Flask = None

import geopandas as gpd

from . import config
from .downloader import _get_data_dir

# Configure module logger
logger = logging.getLogger(__name__)


def _get_color(category: str) -> str:
    """Get color for a category."""
    return config.CATEGORY_COLORS.get(category, config.DEFAULT_COLOR)


def create_map_html(
    gdf: Optional[gpd.GeoDataFrame] = None,
    title: str = "Map",
    center: Optional[list] = None,
    zoom: int = 4
) -> str:
    """
    Create an HTML map from a GeoDataFrame.

    Args:
        gdf: GeoDataFrame to visualize (None for empty map)
        title: Title for the map
        center: Optional [lat, lon] center point
        zoom: Initial zoom level

    Returns:
        HTML string
    """
    # Default center (Europe)
    if center is None:
        center = [48.8566, 2.3522]  # Paris

    if gdf is not None and len(gdf) > 0:
        # Ensure WGS84
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Calculate center from bounds
        bounds = gdf.total_bounds
        center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
        zoom = 12

    # Create map
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")

    # Add tile layers
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satellite",
        overlay=False,
    ).add_to(m)

    folium.TileLayer(
        tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap",
        name="Terrain",
        overlay=False,
    ).add_to(m)

    # Add data layer if provided
    if gdf is not None and len(gdf) > 0:
        # Check if classified (has classname) or raw
        is_classified = "classname" in gdf.columns

        if is_classified:
            # Style by category with distinct colors
            def style_function(feature):
                category = feature["properties"].get("classname", "unknown")
                return {
                    "fillColor": _get_color(category),
                    "color": "#333",
                    "weight": 1,
                    "fillOpacity": 0.7,
                }

            tooltip_fields = ["classname", "landuse"]
            tooltip_aliases = ["Category:", "Original Tag:"]
        else:
            # Raw data - assign unique random color to each polygon
            import hashlib

            # Generate a unique color for each feature based on index
            def generate_color(index: int) -> str:
                """Generate a vibrant color from an index using golden ratio."""
                # Use golden ratio for good color distribution
                golden_ratio = 0.618033988749895
                hue = (index * golden_ratio) % 1.0
                # Convert HSL to RGB (saturation=0.7, lightness=0.5)
                s, l = 0.7, 0.5
                c = (1 - abs(2 * l - 1)) * s
                x = c * (1 - abs((hue * 6) % 2 - 1))
                m = l - c / 2

                if hue < 1/6:
                    r, g, b = c, x, 0
                elif hue < 2/6:
                    r, g, b = x, c, 0
                elif hue < 3/6:
                    r, g, b = 0, c, x
                elif hue < 4/6:
                    r, g, b = 0, x, c
                elif hue < 5/6:
                    r, g, b = x, 0, c
                else:
                    r, g, b = c, 0, x

                r, g, b = int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)
                return f"#{r:02x}{g:02x}{b:02x}"

            # Pre-generate colors for each feature
            feature_colors = {i: generate_color(i) for i in range(len(gdf))}

            # Add index to GeoDataFrame for color lookup
            gdf = gdf.copy()
            gdf["_color_idx"] = range(len(gdf))

            def style_function(feature):
                idx = feature["properties"].get("_color_idx", 0)
                color = feature_colors.get(idx, "#3388ff")
                return {
                    "fillColor": color,
                    "color": "#333",
                    "weight": 1,
                    "fillOpacity": 0.6,
                }

            # Determine which fields exist
            tooltip_fields = []
            tooltip_aliases = []
            if "landuse" in gdf.columns:
                tooltip_fields.append("landuse")
                tooltip_aliases.append("Landuse:")
            if "natural" in gdf.columns:
                tooltip_fields.append("natural")
                tooltip_aliases.append("Natural:")

        # Convert to GeoJSON
        geojson_data = json.loads(gdf.to_json())

        # Add layer
        folium.GeoJson(
            geojson_data,
            name=title,
            style_function=style_function,
            tooltip=folium.GeoJsonTooltip(
                fields=tooltip_fields,
                aliases=tooltip_aliases,
                sticky=True,
            ) if tooltip_fields else None,
        ).add_to(m)

        # Add legend for classified data
        if is_classified:
            categories = gdf["classname"].unique()
            legend_html = """
            <div style="
                position: fixed;
                bottom: 50px;
                right: 50px;
                width: 180px;
                background-color: white;
                z-index: 9999;
                font-size: 12px;
                border: 2px solid #999;
                border-radius: 8px;
                padding: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            ">
            <p style="margin: 0 0 10px 0; font-weight: bold; font-size: 14px; border-bottom: 1px solid #ddd; padding-bottom: 8px;">Landcover Classes</p>
            """
            for cat in sorted(categories):
                color = _get_color(cat)
                legend_html += f"""
                <p style="margin: 4px 0; display: flex; align-items: center;">
                    <span style="background-color: {color}; width: 16px; height: 16px;
                        display: inline-block; margin-right: 8px; border: 1px solid #333; border-radius: 2px;"></span>
                    <span style="font-size: 12px;">{cat}</span>
                </p>
                """
            legend_html += "</div>"
            m.get_root().html.add_child(folium.Element(legend_html))
        else:
            # Legend for raw data
            legend_html = f"""
            <div style="
                position: fixed;
                bottom: 50px;
                right: 50px;
                width: 200px;
                background-color: white;
                z-index: 9999;
                font-size: 12px;
                border: 2px solid #999;
                border-radius: 8px;
                padding: 12px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            ">
            <p style="margin: 0 0 8px 0; font-weight: bold; font-size: 14px;">Raw OSM Data</p>
            <p style="margin: 4px 0; font-size: 11px; color: #666;">
                <strong>{len(gdf)}</strong> unclassified polygons from OpenStreetMap.
                Each polygon has a unique color.
                <br><br>
                Hover to see landuse/natural tags.
            </p>
            </div>
            """
            m.get_root().html.add_child(folium.Element(legend_html))

    # Add controls
    Fullscreen(position="topleft").add_to(m)
    MiniMap(toggle_display=True).add_to(m)
    MousePosition(position="topright", prefix="Coords:").add_to(m)
    folium.LayerControl(position="topright").add_to(m)

    # Get the full HTML
    return m.get_root().render()


# HTML template for the app
APP_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>OSM Landcover Viewer</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"/>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
        }

        .container { display: flex; height: 100vh; }

        .sidebar {
            width: 320px;
            background: #16213e;
            border-right: 1px solid #0f3460;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .sidebar-header {
            padding: 20px;
            background: #0f3460;
            border-bottom: 1px solid #1a1a2e;
        }

        .sidebar-header h1 {
            font-size: 18px;
            color: #e94560;
            margin-bottom: 5px;
        }

        .sidebar-header p {
            font-size: 12px;
            color: #888;
        }

        /* Search Section */
        .search-section {
            padding: 15px;
            background: #1a1a2e;
            border-bottom: 1px solid #0f3460;
        }

        .search-section h3 {
            font-size: 12px;
            color: #888;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .search-box {
            display: flex;
            gap: 8px;
            margin-bottom: 10px;
        }

        .search-box input {
            flex: 1;
            padding: 10px 12px;
            border: 1px solid #0f3460;
            border-radius: 6px;
            background: #16213e;
            color: #eee;
            font-size: 14px;
        }

        .search-box input:focus {
            outline: none;
            border-color: #e94560;
        }

        .search-box input::placeholder {
            color: #666;
        }

        .btn-row {
            display: flex;
            gap: 8px;
        }

        .btn {
            flex: 1;
            padding: 10px 15px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.2s;
        }

        .btn-pan {
            background: #0f3460;
            color: #eee;
        }

        .btn-pan:hover {
            background: #1a4a7a;
        }

        .btn-fetch {
            background: #e94560;
            color: white;
        }

        .btn-fetch:hover {
            background: #ff6b6b;
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* File Browser Section */
        .file-browser {
            flex: 1;
            overflow-y: auto;
            padding: 15px;
        }

        .file-browser h3 {
            font-size: 12px;
            color: #888;
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .path-bar {
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 8px 10px;
            background: #0f3460;
            border-radius: 6px;
            margin-bottom: 10px;
            font-size: 12px;
            color: #888;
            overflow-x: auto;
            white-space: nowrap;
        }

        .path-segment {
            color: #e94560;
            cursor: pointer;
        }

        .path-segment:hover {
            text-decoration: underline;
        }

        .file-list {
            list-style: none;
        }

        .file-item {
            display: flex;
            align-items: center;
            padding: 10px 12px;
            margin: 4px 0;
            background: #1a1a2e;
            border: 1px solid #0f3460;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 13px;
        }

        .file-item:hover {
            background: #0f3460;
            border-color: #e94560;
        }

        .file-item.selected {
            background: #0f3460;
            border-color: #e94560;
        }

        .file-item .icon {
            margin-right: 10px;
            font-size: 16px;
        }

        .file-item .name {
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .file-item .size {
            font-size: 11px;
            color: #666;
        }

        .file-item.folder .icon { color: #ffd700; }
        .file-item.geojson .icon { color: #4ecdc4; }
        .file-item.shapefile .icon { color: #ff6b6b; }

        /* Load Button */
        .load-section {
            padding: 15px;
            background: #0f3460;
            border-top: 1px solid #1a1a2e;
        }

        .btn-load {
            width: 100%;
            padding: 12px;
            background: #4ecdc4;
            color: #1a1a2e;
            font-weight: 600;
        }

        .btn-load:hover {
            background: #45b7aa;
        }

        /* Map Container */
        .map-container {
            flex: 1;
            position: relative;
            background: #1a1a2e;
        }

        .map-container iframe {
            width: 100%;
            height: 100%;
            border: none;
        }

        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: #666;
        }

        .empty-state p {
            margin: 10px 0;
        }

        .loading-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(26, 26, 46, 0.9);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }

        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid #0f3460;
            border-top-color: #e94560;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .loading-text {
            margin-top: 15px;
            color: #888;
            font-size: 14px;
        }

        /* Status messages */
        .status-bar {
            padding: 10px 15px;
            background: #0f3460;
            font-size: 12px;
            color: #888;
            border-top: 1px solid #1a1a2e;
        }

        .status-bar.success { color: #4ecdc4; }
        .status-bar.error { color: #e94560; }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <div class="sidebar-header">
                <h1>OSM Landcover Viewer</h1>
                <p>Browse, fetch, and visualize landcover data</p>
            </div>

            <div class="search-section">
                <h3>Search Location</h3>
                <div class="search-box">
                    <input type="text" id="search-input" placeholder="Enter city name (e.g., Berlin, Germany)">
                </div>
                <div class="btn-row">
                    <button class="btn btn-pan" onclick="panToLocation()">Pan</button>
                    <button class="btn btn-fetch" onclick="fetchOSMData()">Fetch OSM</button>
                </div>
            </div>

            <div class="file-browser">
                <h3>File Browser</h3>
                <div class="path-bar" id="path-bar">
                    <span class="path-segment" onclick="navigateTo('')">data</span>
                </div>
                <ul class="file-list" id="file-list">
                    <!-- Files loaded dynamically -->
                </ul>
            </div>

            <div class="load-section">
                <button class="btn btn-load" id="load-btn" onclick="loadSelectedFile()" disabled>
                    Select a file to load
                </button>
            </div>

            <div class="status-bar" id="status-bar">Ready</div>
        </div>

        <div class="map-container" id="map-container">
            <div class="empty-state">
                <p style="font-size: 48px;">🗺️</p>
                <p>Select a file from the browser or fetch data from OSM</p>
            </div>
        </div>
    </div>

    <script>
        let currentPath = '';
        let selectedFile = null;

        // Initialize
        document.addEventListener('DOMContentLoaded', function() {
            navigateTo('');

            // Enter key triggers search
            document.getElementById('search-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    fetchOSMData();
                }
            });
        });

        function setStatus(message, type = '') {
            const bar = document.getElementById('status-bar');
            bar.textContent = message;
            bar.className = 'status-bar ' + type;
        }

        function showLoading(message = 'Loading...') {
            document.getElementById('map-container').innerHTML = `
                <div class="loading-overlay">
                    <div class="spinner"></div>
                    <div class="loading-text">${message}</div>
                </div>
            `;
        }

        function navigateTo(path) {
            currentPath = path;
            selectedFile = null;
            updateLoadButton();

            fetch('/api/browse?path=' + encodeURIComponent(path))
                .then(r => r.json())
                .then(data => {
                    updatePathBar(data.current_path);
                    updateFileList(data.items);
                })
                .catch(err => {
                    setStatus('Error loading directory: ' + err, 'error');
                });
        }

        function updatePathBar(pathParts) {
            const bar = document.getElementById('path-bar');
            let html = '<span class="path-segment" onclick="navigateTo(\\'\\')">data</span>';
            let fullPath = '';

            for (const part of pathParts) {
                fullPath += (fullPath ? '/' : '') + part;
                const p = fullPath;
                html += ` / <span class="path-segment" onclick="navigateTo('${p}')">${part}</span>`;
            }

            bar.innerHTML = html;
        }

        function updateFileList(items) {
            const list = document.getElementById('file-list');

            if (items.length === 0) {
                list.innerHTML = '<li style="color: #666; padding: 20px; text-align: center;">No files found</li>';
                return;
            }

            let html = '';
            for (const item of items) {
                const icon = item.is_dir ? '📁' : (item.name.endsWith('.geojson') ? '🗺️' : '📄');
                const typeClass = item.is_dir ? 'folder' : (item.name.endsWith('.geojson') ? 'geojson' : 'shapefile');
                const size = item.size ? formatSize(item.size) : '';

                html += `
                    <li class="file-item ${typeClass}"
                        data-path="${item.path}"
                        data-is-dir="${item.is_dir}"
                        onclick="selectItem(this, '${item.path}', ${item.is_dir})">
                        <span class="icon">${icon}</span>
                        <span class="name">${item.name}</span>
                        <span class="size">${size}</span>
                    </li>
                `;
            }

            list.innerHTML = html;
        }

        function formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        }

        function selectItem(element, path, isDir) {
            if (isDir) {
                navigateTo(path);
                return;
            }

            // Deselect previous
            document.querySelectorAll('.file-item').forEach(el => el.classList.remove('selected'));

            // Select new
            element.classList.add('selected');
            selectedFile = path;
            updateLoadButton();
        }

        function updateLoadButton() {
            const btn = document.getElementById('load-btn');
            if (selectedFile) {
                btn.disabled = false;
                btn.textContent = 'Load on Map';
            } else {
                btn.disabled = true;
                btn.textContent = 'Select a file to load';
            }
        }

        function loadSelectedFile() {
            if (!selectedFile) return;

            showLoading('Loading map data...');
            setStatus('Loading ' + selectedFile.split('/').pop() + '...');

            fetch('/load?path=' + encodeURIComponent(selectedFile))
                .then(r => {
                    if (!r.ok) throw new Error('Failed to load file');
                    return r.text();
                })
                .then(html => {
                    document.getElementById('map-container').innerHTML =
                        '<iframe srcdoc="' + html.replace(/"/g, '&quot;') + '"></iframe>';
                    setStatus('Loaded: ' + selectedFile.split('/').pop(), 'success');
                })
                .catch(err => {
                    document.getElementById('map-container').innerHTML = `
                        <div class="empty-state">
                            <p style="font-size: 48px;">❌</p>
                            <p>Error loading file: ${err.message}</p>
                        </div>
                    `;
                    setStatus('Error: ' + err.message, 'error');
                });
        }

        function panToLocation() {
            const query = document.getElementById('search-input').value.trim();
            if (!query) {
                setStatus('Please enter a location name', 'error');
                return;
            }

            setStatus('Searching for ' + query + '...');
            showLoading('Searching for location...');

            fetch('/api/geocode?q=' + encodeURIComponent(query))
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        throw new Error(data.error);
                    }
                    // Load empty map centered on location
                    fetch('/api/empty-map?lat=' + data.lat + '&lon=' + data.lon + '&zoom=12')
                        .then(r => r.text())
                        .then(html => {
                            document.getElementById('map-container').innerHTML =
                                '<iframe srcdoc="' + html.replace(/"/g, '&quot;') + '"></iframe>';
                            setStatus('Centered on: ' + data.display_name, 'success');
                        });
                })
                .catch(err => {
                    document.getElementById('map-container').innerHTML = `
                        <div class="empty-state">
                            <p style="font-size: 48px;">🔍</p>
                            <p>Location not found: ${err.message}</p>
                        </div>
                    `;
                    setStatus('Location not found', 'error');
                });
        }

        function fetchOSMData() {
            const query = document.getElementById('search-input').value.trim();
            if (!query) {
                setStatus('Please enter a location name', 'error');
                return;
            }

            setStatus('Fetching OSM data for ' + query + '...');
            showLoading('Fetching landcover data from OpenStreetMap...<br><br>This may take a minute for large areas.');

            fetch('/api/fetch-osm', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ place: query })
            })
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        throw new Error(data.error);
                    }

                    // Refresh file browser
                    navigateTo('raw');

                    // Load the new file
                    selectedFile = data.path;
                    loadSelectedFile();

                    setStatus('Fetched ' + data.features + ' features for ' + data.name, 'success');
                })
                .catch(err => {
                    document.getElementById('map-container').innerHTML = `
                        <div class="empty-state">
                            <p style="font-size: 48px;">❌</p>
                            <p>Error fetching data: ${err.message}</p>
                        </div>
                    `;
                    setStatus('Fetch error: ' + err.message, 'error');
                });
        }
    </script>
</body>
</html>
"""


def create_app() -> "Flask":
    """Create the Flask application."""
    if Flask is None:
        raise ImportError("Flask is required for the app. Install with: pip install flask")

    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(APP_TEMPLATE)

    @app.route("/api/browse")
    def browse():
        """Browse the data directory."""
        rel_path = request.args.get("path", "")
        data_dir = _get_data_dir()

        # Security: ensure we stay within data directory
        if rel_path:
            full_path = (data_dir / rel_path).resolve()
            try:
                full_path.relative_to(data_dir.resolve())
            except ValueError:
                return jsonify({"error": "Access denied"}), 403
        else:
            full_path = data_dir

        if not full_path.exists():
            full_path.mkdir(parents=True, exist_ok=True)

        items = []
        try:
            for item in sorted(full_path.iterdir()):
                if item.name.startswith('.'):
                    continue

                item_info = {
                    "name": item.name,
                    "path": str(item.relative_to(data_dir)),
                    "is_dir": item.is_dir(),
                }

                if item.is_file():
                    # Only show geospatial files
                    if item.suffix.lower() in ['.geojson', '.shp', '.gpkg']:
                        item_info["size"] = item.stat().st_size
                        items.append(item_info)
                else:
                    items.append(item_info)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        # Parse current path for breadcrumbs
        path_parts = [p for p in rel_path.split('/') if p] if rel_path else []

        return jsonify({
            "current_path": path_parts,
            "items": items
        })

    @app.route("/load")
    def load_file():
        """Load a geospatial file and return map HTML."""
        path = request.args.get("path")
        if not path:
            return "No path provided", 400

        data_dir = _get_data_dir()

        # Handle both relative and absolute paths
        if os.path.isabs(path):
            full_path = Path(path).resolve()
        else:
            full_path = (data_dir / path).resolve()

        # Security: Validate path is within allowed data directories
        try:
            full_path.relative_to(data_dir.resolve())
        except ValueError:
            return "Access denied: path outside data directory", 403

        if not full_path.exists():
            return "File not found", 404

        # Security: Only allow geospatial files
        if full_path.suffix.lower() not in ['.geojson', '.shp', '.gpkg']:
            return "Only geospatial files are allowed", 403

        try:
            gdf = gpd.read_file(full_path)
            html = create_map_html(gdf, title=full_path.stem)
            return html
        except Exception as e:
            return f"Error loading file: {e}", 500

    @app.route("/api/geocode")
    def geocode():
        """Geocode a place name using Nominatim."""
        query = request.args.get("q", "")
        if not query:
            return jsonify({"error": "No query provided"}), 400

        try:
            import urllib.request
            import urllib.parse

            url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=1"
            req = urllib.request.Request(url, headers={"User-Agent": "OSM-Auto-Label/1.0"})

            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

            if not data:
                return jsonify({"error": "Location not found"}), 404

            result = data[0]
            return jsonify({
                "lat": float(result["lat"]),
                "lon": float(result["lon"]),
                "display_name": result["display_name"]
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/empty-map")
    def empty_map():
        """Return an empty map centered on coordinates."""
        lat = request.args.get("lat", 48.8566, type=float)
        lon = request.args.get("lon", 2.3522, type=float)
        zoom = request.args.get("zoom", 12, type=int)

        html = create_map_html(None, center=[lat, lon], zoom=zoom)
        return html

    @app.route("/api/fetch-osm", methods=["POST"])
    def fetch_osm():
        """Fetch OSM landcover data for a place."""
        data = request.get_json()
        place = data.get("place", "") if data else ""

        if not place:
            return jsonify({"error": "No place provided"}), 400

        try:
            from .downloader import download_osm_landcover, _place_to_filename

            gdf = download_osm_landcover(place, timeout=300)

            name = _place_to_filename(place)
            raw_path = _get_data_dir() / "raw" / f"{name}.geojson"

            return jsonify({
                "success": True,
                "name": name,
                "features": len(gdf),
                "path": str(raw_path.relative_to(_get_data_dir()))
            })
        except Exception as e:
            logger.exception(f"Error fetching OSM data: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/files")
    def api_files():
        """Legacy API for listing files."""
        from .downloader import list_raw_data, list_classified_data
        return jsonify({
            "raw": [{"name": f.stem, "path": str(f)} for f in list_raw_data()],
            "classified": [{"name": f.stem, "path": str(f)} for f in list_classified_data()],
        })

    return app


def run_app(host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
    """
    Run the interactive visualizer app.

    Args:
        host: Host to bind to
        port: Port to run on
        debug: Enable debug mode
    """
    app = create_app()
    logger.info("=" * 50)
    logger.info("OSM Landcover Viewer")
    logger.info("=" * 50)
    logger.info(f"Open your browser to: http://{host}:{port}")
    logger.info("Press Ctrl+C to stop the server")
    logger.info("=" * 50)
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_app(debug=True)
