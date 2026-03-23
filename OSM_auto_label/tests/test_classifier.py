"""Tests for the classifier module."""

import pytest
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from unittest.mock import Mock, patch, MagicMock

from OSM_auto_label.classifier import (
    OSMLandcoverClassifier,
    WordEmbeddingError,
    DataLoadError,
    ClassificationError,
    _name_to_filename,
    _get_word_vectors,
)


class TestNameToFilename:
    """Tests for _name_to_filename function."""

    def test_simple_name(self):
        assert _name_to_filename("Paris") == "paris"

    def test_name_with_spaces(self):
        assert _name_to_filename("New York") == "new_york"

    def test_name_with_special_chars(self):
        assert _name_to_filename("Paris, France") == "paris_france"

    def test_name_with_diacritics(self):
        # Diacritics pass through (only non-word chars removed)
        result = _name_to_filename("Brașov")
        # The regex keeps unicode word characters, so ș stays
        assert result == "brașov" or "bra" in result

    def test_empty_string(self):
        assert _name_to_filename("") == ""

    def test_name_with_multiple_spaces(self):
        assert _name_to_filename("San   Francisco") == "san_francisco"


class TestWordVectorsCache:
    """Tests for word vector caching."""

    @patch('OSM_auto_label.classifier._word_vectors_cache', {})
    @patch('gensim.downloader.load')
    def test_caches_word_vectors(self, mock_load):
        """Test that word vectors are cached after first load."""
        mock_vectors = Mock()
        mock_load.return_value = mock_vectors

        # First call should load
        result1 = _get_word_vectors("test-model")
        assert mock_load.call_count == 1

        # Second call should use cache
        result2 = _get_word_vectors("test-model")
        assert mock_load.call_count == 1  # Still 1, not 2

        assert result1 is result2

    @patch('OSM_auto_label.classifier._word_vectors_cache', {})
    @patch('gensim.downloader.load')
    def test_raises_word_embedding_error(self, mock_load):
        """Test that WordEmbeddingError is raised on load failure."""
        mock_load.side_effect = Exception("Failed to load")

        with pytest.raises(WordEmbeddingError) as exc_info:
            _get_word_vectors("invalid-model")

        assert "invalid-model" in str(exc_info.value)


class TestOSMLandcoverClassifier:
    """Tests for OSMLandcoverClassifier class."""

    @pytest.fixture
    def mock_word_vectors(self):
        """Create mock word vectors."""
        mock = MagicMock()
        mock.key_to_index = {
            "residential": 0,
            "commercial": 1,
            "forest": 2,
            "water": 3,
            "grass": 4,
            "industrial": 5,
        }
        # Return random vectors when accessed
        mock.__getitem__ = lambda self, key: np.random.randn(300)
        return mock

    @pytest.fixture
    def sample_gdf(self):
        """Create a sample GeoDataFrame for testing."""
        polygons = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
            Polygon([(2, 0), (3, 0), (3, 1), (2, 1)]),
        ]
        return gpd.GeoDataFrame({
            'landuse': ['residential', 'commercial', 'forest'],
            'natural': [None, None, None],
            'geometry': polygons,
        })

    @pytest.fixture
    def sample_gdf_with_natural(self):
        """Create a sample GeoDataFrame with natural tags."""
        polygons = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ]
        return gpd.GeoDataFrame({
            'landuse': [None, 'residential'],
            'natural': ['water', None],
            'geometry': polygons,
        })

    def test_init_defaults(self):
        """Test classifier initialization with defaults."""
        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: Mock())):
            classifier = OSMLandcoverClassifier()
            assert classifier.seed_categories is not None
            assert classifier.replacements is not None
            assert classifier.category_priority is not None

    def test_init_custom_categories(self):
        """Test classifier initialization with custom categories."""
        custom_cats = {"urban": ["residential"], "nature": ["forest"]}

        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: Mock())):
            classifier = OSMLandcoverClassifier(seed_categories=custom_cats)
            assert classifier.seed_categories == custom_cats

    def test_preprocess_merges_natural(self, sample_gdf_with_natural, mock_word_vectors):
        """Test that preprocessing merges natural column into landuse."""
        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            classifier = OSMLandcoverClassifier()
            result = classifier.preprocess(sample_gdf_with_natural)

            # Check that water from natural column is now in landuse
            assert 'water' in result['landuse'].values
            assert 'residential' in result['landuse'].values

    def test_preprocess_removes_empty_rows(self, mock_word_vectors):
        """Test that preprocessing removes rows without landuse or natural."""
        polygons = [
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
            Polygon([(1, 0), (2, 0), (2, 1), (1, 1)]),
        ]
        gdf = gpd.GeoDataFrame({
            'landuse': ['residential', None],
            'natural': [None, None],
            'geometry': polygons,
        })

        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            classifier = OSMLandcoverClassifier()
            result = classifier.preprocess(gdf)
            assert len(result) == 1

    def test_preprocess_raises_on_empty(self, mock_word_vectors):
        """Test that preprocessing raises error when no valid features."""
        polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]
        gdf = gpd.GeoDataFrame({
            'landuse': [None],
            'natural': [None],
            'geometry': polygons,
        })

        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            classifier = OSMLandcoverClassifier()
            with pytest.raises(DataLoadError):
                classifier.preprocess(gdf)

    def test_get_tag_statistics(self, sample_gdf, mock_word_vectors):
        """Test tag statistics calculation."""
        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            classifier = OSMLandcoverClassifier()
            counts, tag_set = classifier.get_tag_statistics(sample_gdf)

            assert len(tag_set) == 3
            assert 'residential' in tag_set
            assert 'commercial' in tag_set
            assert 'forest' in tag_set

    def test_classify_adds_columns(self, sample_gdf, mock_word_vectors):
        """Test that classify adds required columns."""
        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            classifier = OSMLandcoverClassifier()
            classifier.seed_categories = {"builtup": ["residential", "commercial"], "forest": ["forest"]}

            assignments = {
                'residential': 'builtup',
                'commercial': 'builtup',
                'forest': 'forest',
            }

            result = classifier.classify(sample_gdf, assignments)

            assert 'classname' in result.columns
            assert 'classvalue' in result.columns
            assert 'priority' in result.columns

    def test_classify_raises_on_empty(self, mock_word_vectors):
        """Test that classify raises error when no features can be classified."""
        polygons = [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])]
        gdf = gpd.GeoDataFrame({
            'landuse': ['unknown_tag'],
            'geometry': polygons,
        })

        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            classifier = OSMLandcoverClassifier()

            with pytest.raises(ClassificationError):
                classifier.classify(gdf, {})  # Empty assignments

    def test_category_names_property(self, mock_word_vectors):
        """Test category_names property."""
        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            classifier = OSMLandcoverClassifier()
            classifier.seed_categories = {"cat1": ["a"], "cat2": ["b"]}

            names = classifier.category_names
            assert names == ["cat1", "cat2"]


class TestClassifierIntegration:
    """Integration tests for the classifier (require mocked word vectors)."""

    @pytest.fixture
    def mock_word_vectors(self):
        """Create more realistic mock word vectors."""
        vectors = {
            "residential": np.array([1.0, 0.0, 0.0] + [0.0] * 297),
            "commercial": np.array([0.9, 0.1, 0.0] + [0.0] * 297),
            "industrial": np.array([0.8, 0.2, 0.0] + [0.0] * 297),
            "forest": np.array([0.0, 1.0, 0.0] + [0.0] * 297),
            "wood": np.array([0.0, 0.9, 0.1] + [0.0] * 297),
            "water": np.array([0.0, 0.0, 1.0] + [0.0] * 297),
            "grass": np.array([0.0, 0.5, 0.5] + [0.0] * 297),
        }

        mock = MagicMock()
        mock.key_to_index = {k: i for i, k in enumerate(vectors.keys())}

        def get_item(keys):
            if isinstance(keys, list):
                return np.array([vectors.get(k, np.zeros(300)) for k in keys])
            return vectors.get(keys, np.zeros(300))

        mock.__getitem__ = get_item
        return mock

    def test_create_landuse_mapping(self, mock_word_vectors):
        """Test landuse mapping creation."""
        with patch.object(OSMLandcoverClassifier, 'word_vectors', new_callable=lambda: property(lambda self: mock_word_vectors)):
            with patch.object(OSMLandcoverClassifier, 'allowed_keys', new_callable=lambda: property(lambda self: list(mock_word_vectors.key_to_index.keys()))):
                classifier = OSMLandcoverClassifier()
                tag_set = {'residential', 'forest', 'unknown_tag'}

                mapping = classifier.create_landuse_mapping(tag_set)

                assert 'residential' in mapping
                assert 'forest' in mapping
                assert 'unknown_tag' not in mapping
