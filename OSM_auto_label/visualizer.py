"""
Visualization module for OSM Landcover data.

Provides interactive Leaflet/Folium map visualization with vector overlay.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import folium
from folium.plugins import MiniMap, Fullscreen, MousePosition
import geopandas as gpd

from . import config

# Configure module logger
logger = logging.getLogger(__name__)


class VisualizationError(Exception):
    """Raised when visualization operations fail."""
    pass


class LandcoverMapVisualizer:
    """
    Interactive Leaflet map visualizer for landcover classification results.

    Creates interactive maps with vector overlays, legends, and various
    map controls for exploring classified landcover data.
    """

    def __init__(
        self,
        colors: Optional[Dict[str, str]] = None,
        default_color: str = config.DEFAULT_COLOR,
    ) -> None:
        """
        Initialize the visualizer.

        Args:
            colors: Dictionary mapping category names to hex colors
            default_color: Color to use for unknown categories
        """
        self.colors = colors or config.CATEGORY_COLORS
        self.default_color = default_color

    def create_map(
        self,
        gdf: gpd.GeoDataFrame,
        center: Optional[Tuple[float, float]] = None,
        zoom_start: int = config.MAP_CONFIG["zoom_start"],
        tiles: str = config.MAP_CONFIG["tiles"],
    ) -> folium.Map:
        """
        Create a base Folium map centered on the data.

        Args:
            gdf: GeoDataFrame with geometry to visualize
            center: Optional (lat, lon) center point
            zoom_start: Initial zoom level
            tiles: Base tile layer name

        Returns:
            Configured Folium Map object
        """
        # Calculate center from data bounds if not provided
        if center is None:
            bounds = gdf.total_bounds  # [minx, miny, maxx, maxy]
            center = (
                (bounds[1] + bounds[3]) / 2,  # lat
                (bounds[0] + bounds[2]) / 2,  # lon
            )

        # Create base map
        m = folium.Map(
            location=center,
            zoom_start=zoom_start,
            tiles=tiles,
            control_scale=True,
        )

        return m

    def add_tile_layers(self, m: folium.Map) -> folium.Map:
        """
        Add additional tile layer options to the map.

        Args:
            m: Folium Map object

        Returns:
            Map with additional tile layers
        """
        # Add satellite imagery option
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri",
            name="Satellite",
            overlay=False,
        ).add_to(m)

        # Add terrain option
        folium.TileLayer(
            tiles="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
            attr="OpenTopoMap",
            name="Terrain",
            overlay=False,
        ).add_to(m)

        # Add dark mode option
        folium.TileLayer(
            tiles="https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png",
            attr="Stadia Maps",
            name="Dark Mode",
            overlay=False,
        ).add_to(m)

        return m

    def add_vector_layer(
        self,
        m: folium.Map,
        gdf: gpd.GeoDataFrame,
        layer_name: str = "Landcover",
        style_by: str = "classname",
        fill_opacity: float = config.MAP_CONFIG["fill_opacity"],
        line_weight: int = config.MAP_CONFIG["line_weight"],
        line_color: str = config.MAP_CONFIG["line_color"],
    ) -> folium.Map:
        """
        Add vector overlay layer to the map (optimized for large datasets).

        Args:
            m: Folium Map object
            gdf: GeoDataFrame with classified features
            layer_name: Name for the layer in layer control
            style_by: Column name to use for styling
            fill_opacity: Fill opacity (0-1)
            line_weight: Border line weight
            line_color: Border line color

        Returns:
            Map with vector overlay
        """
        # Ensure CRS is WGS84 for Leaflet
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Create style function
        def style_function(feature):
            category = feature["properties"].get(style_by, "unknown")
            return {
                "fillColor": self.colors.get(category, self.default_color),
                "color": line_color,
                "weight": line_weight,
                "fillOpacity": fill_opacity,
            }

        # Create highlight function for hover effect
        def highlight_function(feature):
            return {
                "weight": 3,
                "color": "#666",
                "fillOpacity": 0.8,
            }

        # Create popup function
        def popup_function(feature):
            props = feature["properties"]
            html = "<div style='font-family: Arial, sans-serif;'>"
            html += f"<h4 style='margin: 0 0 8px 0; color: #333;'>{props.get('classname', 'Unknown')}</h4>"
            html += "<table style='border-collapse: collapse;'>"

            fields = [
                ("Landuse Tag", "landuse"),
                ("Class Value", "classvalue"),
                ("Priority", "priority"),
            ]

            for label, key in fields:
                if key in props:
                    html += f"<tr><td style='padding: 2px 8px 2px 0; color: #666;'>{label}:</td>"
                    html += f"<td style='padding: 2px 0;'><strong>{props[key]}</strong></td></tr>"

            html += "</table></div>"
            return html

        # Convert to GeoJSON (more efficient than row-by-row)
        geojson_data = json.loads(gdf.to_json())

        # Add GeoJson layer with popups
        geojson_layer = folium.GeoJson(
            geojson_data,
            name=layer_name,
            style_function=style_function,
            highlight_function=highlight_function,
            tooltip=folium.GeoJsonTooltip(
                fields=["classname", "landuse"],
                aliases=["Category:", "Tag:"],
                localize=True,
                sticky=True,
                style="""
                    background-color: white;
                    border: 2px solid black;
                    border-radius: 3px;
                    box-shadow: 3px 3px 3px rgba(0,0,0,0.3);
                    font-size: 12px;
                    padding: 5px;
                """,
            ),
        )

        # Add popups to each feature
        folium.GeoJsonPopup(
            fields=["classname", "landuse", "classvalue", "priority"],
            aliases=["Category", "OSM Tag", "Class Value", "Priority"],
            localize=True,
            labels=True,
            max_width=300,
        ).add_to(geojson_layer)

        geojson_layer.add_to(m)

        return m

    def add_category_layers(
        self,
        m: folium.Map,
        gdf: gpd.GeoDataFrame,
        fill_opacity: float = config.MAP_CONFIG["fill_opacity"],
    ) -> folium.Map:
        """
        Add separate toggleable layers for each category.

        Args:
            m: Folium Map object
            gdf: GeoDataFrame with classified features
            fill_opacity: Fill opacity (0-1)

        Returns:
            Map with category-specific layers
        """
        # Ensure CRS is WGS84
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Create a feature group for each category
        categories = gdf["classname"].unique()

        for category in sorted(categories):
            category_gdf = gdf[gdf["classname"] == category]
            color = self.colors.get(category, self.default_color)

            # Create feature group
            fg = folium.FeatureGroup(name=f"{category} ({len(category_gdf)})")

            # Add features
            geojson_data = json.loads(category_gdf.to_json())
            folium.GeoJson(
                geojson_data,
                style_function=lambda x, c=color: {
                    "fillColor": c,
                    "color": "black",
                    "weight": 1,
                    "fillOpacity": fill_opacity,
                },
                tooltip=folium.GeoJsonTooltip(
                    fields=["landuse"],
                    aliases=["Tag:"],
                    sticky=True,
                ),
            ).add_to(fg)

            fg.add_to(m)

        return m

    def add_legend(
        self,
        m: folium.Map,
        title: str = "Landcover Classes",
        categories: Optional[List[str]] = None,
    ) -> folium.Map:
        """
        Add a legend to the map.

        Args:
            m: Folium Map object
            title: Legend title
            categories: List of categories to show (defaults to all)

        Returns:
            Map with legend
        """
        if categories is None:
            categories = list(self.colors.keys())

        legend_html = f"""
        <div style="
            position: fixed;
            bottom: 50px;
            right: 50px;
            width: 180px;
            background-color: white;
            z-index: 9999;
            font-size: 13px;
            border: 2px solid #999;
            border-radius: 5px;
            padding: 10px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
        ">
        <p style="margin: 0 0 8px 0; font-weight: bold; font-size: 14px; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
            {title}
        </p>
        """

        for category in categories:
            color = self.colors.get(category, self.default_color)
            legend_html += f"""
            <p style="margin: 4px 0; display: flex; align-items: center;">
                <span style="
                    background-color: {color};
                    width: 18px;
                    height: 14px;
                    display: inline-block;
                    margin-right: 8px;
                    border: 1px solid #333;
                    border-radius: 2px;
                "></span>
                {category}
            </p>
            """

        legend_html += "</div>"

        m.get_root().html.add_child(folium.Element(legend_html))

        return m

    def add_controls(self, m: folium.Map) -> folium.Map:
        """
        Add map controls (fullscreen, minimap, mouse position).

        Args:
            m: Folium Map object

        Returns:
            Map with controls
        """
        # Fullscreen control
        Fullscreen(
            position="topleft",
            title="Fullscreen",
            title_cancel="Exit Fullscreen",
        ).add_to(m)

        # Minimap
        MiniMap(
            tile_layer="OpenStreetMap",
            position="bottomleft",
            toggle_display=True,
        ).add_to(m)

        # Mouse position display
        MousePosition(
            position="topright",
            separator=" | ",
            prefix="Coordinates:",
            num_digits=5,
        ).add_to(m)

        # Layer control
        folium.LayerControl(
            position="topright",
            collapsed=True,
        ).add_to(m)

        return m

    def create_landcover_map(
        self,
        gdf: gpd.GeoDataFrame,
        output_path: Optional[str | Path] = None,
        center: Optional[Tuple[float, float]] = None,
        zoom_start: int = config.MAP_CONFIG["zoom_start"],
        show_category_layers: bool = False,
        add_tile_options: bool = True,
    ) -> folium.Map:
        """
        Create a complete interactive landcover map.

        Args:
            gdf: Classified GeoDataFrame
            output_path: Optional path to save HTML file
            center: Optional (lat, lon) center point
            zoom_start: Initial zoom level
            show_category_layers: If True, add separate toggleable category layers
            add_tile_options: If True, add additional tile layer options

        Returns:
            Complete Folium Map object
        """
        logger.info("Creating interactive landcover map...")

        # Validate input
        required_cols = ["geometry", "classname", "landuse"]
        missing = [col for col in required_cols if col not in gdf.columns]
        if missing:
            raise VisualizationError(f"Missing required columns: {missing}")

        # Create base map
        m = self.create_map(gdf, center=center, zoom_start=zoom_start)

        # Add tile layer options
        if add_tile_options:
            m = self.add_tile_layers(m)

        # Add vector data
        if show_category_layers:
            m = self.add_category_layers(m, gdf)
        else:
            m = self.add_vector_layer(m, gdf)

        # Add legend and controls
        m = self.add_legend(m)
        m = self.add_controls(m)

        # Save if path provided
        if output_path:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            m.save(str(output_path))
            logger.info(f"Map saved to: {output_path}")

        return m

    def create_comparison_map(
        self,
        gdf_list: List[gpd.GeoDataFrame],
        names: List[str],
        output_path: Optional[str | Path] = None,
    ) -> folium.Map:
        """
        Create a map comparing multiple classification results.

        Args:
            gdf_list: List of classified GeoDataFrames
            names: Names for each dataset
            output_path: Optional path to save HTML file

        Returns:
            Folium Map with comparison layers
        """
        if len(gdf_list) != len(names):
            raise VisualizationError("Number of GeoDataFrames must match number of names")

        # Use first GeoDataFrame for centering
        m = self.create_map(gdf_list[0])
        m = self.add_tile_layers(m)

        # Add each dataset as a layer
        for gdf, name in zip(gdf_list, names):
            self.add_vector_layer(m, gdf, layer_name=name)

        m = self.add_legend(m)
        m = self.add_controls(m)

        if output_path:
            output_path = Path(output_path)
            m.save(str(output_path))
            logger.info(f"Comparison map saved to: {output_path}")

        return m


def visualize_classification(
    gdf: gpd.GeoDataFrame,
    output_path: str | Path = "landcover_map.html",
    **kwargs,
) -> folium.Map:
    """
    Convenience function to create a landcover visualization.

    Args:
        gdf: Classified GeoDataFrame
        output_path: Path to save HTML file
        **kwargs: Additional arguments passed to create_landcover_map

    Returns:
        Folium Map object
    """
    visualizer = LandcoverMapVisualizer()
    return visualizer.create_landcover_map(gdf, output_path=output_path, **kwargs)
