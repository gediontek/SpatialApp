"""Tests for the config module."""

import pytest
from OSM_auto_label import config


class TestConfigValues:
    """Tests for configuration values."""

    def test_word_embedding_model_defined(self):
        """Test word embedding model is defined."""
        assert config.WORD_EMBEDDING_MODEL is not None
        assert isinstance(config.WORD_EMBEDDING_MODEL, str)
        assert len(config.WORD_EMBEDDING_MODEL) > 0

    def test_seed_categories_structure(self):
        """Test seed categories have correct structure."""
        assert isinstance(config.SEED_CATEGORIES, dict)
        assert len(config.SEED_CATEGORIES) > 0

        for category, tags in config.SEED_CATEGORIES.items():
            assert isinstance(category, str)
            assert isinstance(tags, list)
            assert len(tags) > 0
            for tag in tags:
                assert isinstance(tag, str)

    def test_category_colors_match_categories(self):
        """Test that colors exist for all seed categories."""
        for category in config.SEED_CATEGORIES.keys():
            assert category in config.CATEGORY_COLORS, \
                f"Missing color for category: {category}"

    def test_category_colors_are_valid_hex(self):
        """Test that colors are valid hex codes."""
        import re
        hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')

        for category, color in config.CATEGORY_COLORS.items():
            assert hex_pattern.match(color), \
                f"Invalid hex color for {category}: {color}"

    def test_category_priority_values(self):
        """Test category priority values are positive integers."""
        for category, priority in config.CATEGORY_PRIORITY.items():
            assert isinstance(priority, int)
            assert priority > 0

    def test_tag_replacements_structure(self):
        """Test tag replacements have correct structure."""
        assert isinstance(config.TAG_REPLACEMENTS, dict)

        for original, replacement in config.TAG_REPLACEMENTS.items():
            assert isinstance(original, str)
            assert isinstance(replacement, str)

    def test_clustering_config_keys(self):
        """Test clustering config has required keys."""
        required_keys = ['n_clusters', 'n_components', 'popularity_threshold', 'random_state']

        for key in required_keys:
            assert key in config.CLUSTERING_CONFIG, \
                f"Missing clustering config key: {key}"

    def test_map_config_keys(self):
        """Test map config has required keys."""
        required_keys = ['zoom_start', 'tiles', 'fill_opacity', 'line_weight', 'line_color']

        for key in required_keys:
            assert key in config.MAP_CONFIG, \
                f"Missing map config key: {key}"

    def test_map_config_values(self):
        """Test map config values are valid."""
        assert 0 <= config.MAP_CONFIG['fill_opacity'] <= 1
        assert config.MAP_CONFIG['line_weight'] > 0
        assert config.MAP_CONFIG['zoom_start'] > 0

    def test_default_color_is_valid_hex(self):
        """Test default color is valid hex."""
        import re
        hex_pattern = re.compile(r'^#[0-9A-Fa-f]{6}$')
        assert hex_pattern.match(config.DEFAULT_COLOR)

    def test_excluded_words_list(self):
        """Test excluded words is a list of strings."""
        assert isinstance(config.EXCLUDED_WORDS, list)
        for word in config.EXCLUDED_WORDS:
            assert isinstance(word, str)

    def test_shapefile_columns_list(self):
        """Test shapefile columns is a list of strings."""
        assert isinstance(config.SHAPEFILE_COLUMNS, list)
        assert 'geometry' in config.SHAPEFILE_COLUMNS
        for col in config.SHAPEFILE_COLUMNS:
            assert isinstance(col, str)


class TestLoggingConfig:
    """Tests for logging configuration."""

    def test_logging_config_structure(self):
        """Test logging config has required structure."""
        assert 'version' in config.LOGGING_CONFIG
        assert 'handlers' in config.LOGGING_CONFIG
        assert 'loggers' in config.LOGGING_CONFIG

    def test_logging_config_version(self):
        """Test logging config version is 1."""
        assert config.LOGGING_CONFIG['version'] == 1

    def test_console_handler_exists(self):
        """Test console handler is defined."""
        assert 'console' in config.LOGGING_CONFIG['handlers']

    def test_package_logger_exists(self):
        """Test package logger is defined."""
        assert 'OSM_auto_label' in config.LOGGING_CONFIG['loggers']
