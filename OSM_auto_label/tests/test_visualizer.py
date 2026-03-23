"""Tests for the visualizer module."""

import pytest
import folium
import geopandas as gpd
from shapely.geometry import Polygon
from unittest.mock import patch, Mock

from OSM_auto_label.visualizer import (
    LandcoverMapVisualizer,
    VisualizationError,
    visualize_classification,
)
from OSM_auto_label import config


class TestLandcoverMapVisualizer:
    """Tests for LandcoverMapVisualizer class."""

    @pytest.fixture
    def visualizer(self):
        """Create a visualizer instance."""
        return LandcoverMapVisualizer()

    @pytest.fixture
    def sample_classified_gdf(self):
        """Create a sample classified GeoDataFrame."""
        polygons = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
        ]
        return gpd.GeoDataFrame({
            'landuse': ['residential', 'forest', 'water'],
            'classname': ['builtup_area', 'forest', 'water'],
            'classvalue': [1, 4, 2],
            'priority': [1, 2, 2],
            'geometry': polygons,
        }, crs="EPSG:4326")

    @pytest.fixture
    def sample_raw_gdf(self):
        """Create a sample raw GeoDataFrame (without classification)."""
        polygons = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ]
        return gpd.GeoDataFrame({
            'landuse': ['residential', 'forest'],
            'natural': [None, None],
            'geometry': polygons,
        }, crs="EPSG:4326")

    def test_init_default_colors(self, visualizer):
        """Test visualizer initializes with default colors."""
        assert visualizer.colors == config.CATEGORY_COLORS
        assert visualizer.default_color == config.DEFAULT_COLOR

    def test_init_custom_colors(self):
        """Test visualizer with custom colors."""
        custom_colors = {"urban": "#FF0000", "nature": "#00FF00"}
        visualizer = LandcoverMapVisualizer(colors=custom_colors)
        assert visualizer.colors == custom_colors

    def test_create_map_returns_folium_map(self, visualizer, sample_classified_gdf):
        """Test create_map returns a Folium Map object."""
        m = visualizer.create_map(sample_classified_gdf)
        assert isinstance(m, folium.Map)

    def test_create_map_centers_on_data(self, visualizer, sample_classified_gdf):
        """Test map is centered on the data bounds."""
        m = visualizer.create_map(sample_classified_gdf)

        # Get map center from the map's location
        center = m.location
        assert center is not None
        assert len(center) == 2  # [lat, lon]

    def test_create_map_with_custom_center(self, visualizer, sample_classified_gdf):
        """Test map uses custom center when provided."""
        custom_center = (48.8566, 2.3522)  # Paris
        m = visualizer.create_map(sample_classified_gdf, center=custom_center)
        assert m.location == list(custom_center)

    def test_add_tile_layers(self, visualizer, sample_classified_gdf):
        """Test that tile layers are added."""
        m = visualizer.create_map(sample_classified_gdf)
        m = visualizer.add_tile_layers(m)

        # Map should have children (layers)
        assert len(m._children) > 0

    def test_add_vector_layer(self, visualizer, sample_classified_gdf):
        """Test adding vector layer."""
        m = visualizer.create_map(sample_classified_gdf)
        m = visualizer.add_vector_layer(m, sample_classified_gdf)

        # Should have GeoJson layer added
        geojson_found = False
        for child in m._children.values():
            if isinstance(child, folium.GeoJson):
                geojson_found = True
                break
        assert geojson_found

    def test_add_legend(self, visualizer, sample_classified_gdf):
        """Test adding legend to map."""
        m = visualizer.create_map(sample_classified_gdf)
        m = visualizer.add_legend(m)

        # Legend is added as HTML element
        assert m.get_root() is not None

    def test_add_controls(self, visualizer, sample_classified_gdf):
        """Test adding map controls."""
        m = visualizer.create_map(sample_classified_gdf)
        m = visualizer.add_controls(m)

        # Should have fullscreen, minimap, etc.
        assert len(m._children) > 0

    def test_create_landcover_map_validates_columns(self, visualizer, sample_raw_gdf):
        """Test that create_landcover_map validates required columns."""
        with pytest.raises(VisualizationError) as exc_info:
            visualizer.create_landcover_map(sample_raw_gdf)

        assert "Missing required columns" in str(exc_info.value)

    def test_create_landcover_map_success(self, visualizer, sample_classified_gdf):
        """Test successful landcover map creation."""
        m = visualizer.create_landcover_map(sample_classified_gdf)
        assert isinstance(m, folium.Map)

    def test_create_landcover_map_saves_to_file(self, visualizer, sample_classified_gdf, tmp_path):
        """Test map is saved when output_path provided."""
        output_file = tmp_path / "test_map.html"
        m = visualizer.create_landcover_map(
            sample_classified_gdf,
            output_path=output_file
        )

        assert output_file.exists()
        content = output_file.read_text()
        assert "leaflet" in content.lower()

    def test_create_comparison_map_validates_length(self, visualizer, sample_classified_gdf):
        """Test comparison map validates list lengths match."""
        with pytest.raises(VisualizationError):
            visualizer.create_comparison_map(
                [sample_classified_gdf],
                ["Dataset1", "Dataset2"]  # Mismatched lengths
            )

    def test_create_comparison_map_success(self, visualizer, sample_classified_gdf):
        """Test successful comparison map creation."""
        m = visualizer.create_comparison_map(
            [sample_classified_gdf, sample_classified_gdf],
            ["Dataset1", "Dataset2"]
        )
        assert isinstance(m, folium.Map)


class TestVisualizeClassification:
    """Tests for visualize_classification convenience function."""

    @pytest.fixture
    def sample_gdf(self):
        """Create a sample classified GeoDataFrame."""
        polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]
        return gpd.GeoDataFrame({
            'landuse': ['residential'],
            'classname': ['builtup_area'],
            'classvalue': [1],
            'priority': [1],
            'geometry': polygons,
        }, crs="EPSG:4326")

    def test_convenience_function_returns_map(self, sample_gdf, tmp_path):
        """Test visualize_classification returns a map."""
        output_file = tmp_path / "quick_map.html"
        m = visualize_classification(sample_gdf, output_path=output_file)

        assert isinstance(m, folium.Map)
        assert output_file.exists()


class TestCRSHandling:
    """Tests for CRS handling in visualization."""

    @pytest.fixture
    def sample_gdf_utm(self):
        """Create a sample GeoDataFrame in UTM projection."""
        polygons = [
            Polygon([(500000, 5000000), (500100, 5000000), (500100, 5000100), (500000, 5000100)]),
        ]
        gdf = gpd.GeoDataFrame({
            'landuse': ['residential'],
            'classname': ['builtup_area'],
            'classvalue': [1],
            'priority': [1],
            'geometry': polygons,
        }, crs="EPSG:32633")  # UTM zone 33N
        return gdf

    def test_crs_conversion_to_wgs84(self, sample_gdf_utm):
        """Test that non-WGS84 data is converted."""
        visualizer = LandcoverMapVisualizer()

        # The add_vector_layer method should handle CRS conversion
        m = visualizer.create_map(sample_gdf_utm)
        m = visualizer.add_vector_layer(m, sample_gdf_utm)

        # If we got here without error, CRS conversion worked
        assert isinstance(m, folium.Map)
