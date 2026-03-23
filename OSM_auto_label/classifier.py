"""
OSM Landcover Classifier module.

Handles loading, preprocessing, and classification of OSM data
into landcover categories using word embeddings.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import SpectralClustering

from . import config
from .downloader import _get_classified_dir

# Configure module logger
logger = logging.getLogger(__name__)


def _name_to_filename(name: str) -> str:
    """
    Convert a name to a valid filename.

    Args:
        name: Input name string

    Returns:
        Sanitized filename string
    """
    name = name.lower().strip()
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s]+', '_', name)
    return name


class WordEmbeddingError(Exception):
    """Raised when word embedding operations fail."""
    pass


class DataLoadError(Exception):
    """Raised when data loading fails."""
    pass


class ClassificationError(Exception):
    """Raised when classification fails."""
    pass


# Module-level cache for word vectors (singleton pattern)
_word_vectors_cache: Dict[str, Any] = {}


def _get_word_vectors(model_name: str) -> Any:
    """
    Get word vectors with lazy loading and caching.

    Args:
        model_name: Name of the gensim model to load

    Returns:
        Loaded word vectors

    Raises:
        WordEmbeddingError: If model loading fails
    """
    if model_name not in _word_vectors_cache:
        try:
            import gensim.downloader
            logger.info(f"Loading word embedding model: {model_name}")
            _word_vectors_cache[model_name] = gensim.downloader.load(model_name)
        except Exception as e:
            raise WordEmbeddingError(
                f"Failed to load word embedding model '{model_name}': {e}"
            ) from e
    return _word_vectors_cache[model_name]


class OSMLandcoverClassifier:
    """
    Classifies OSM polygon data into landcover categories using word embeddings.

    The classifier uses pre-trained word vectors (GloVe) to semantically map
    OSM tags to predefined landcover categories based on vector similarity.

    Attributes:
        word_vectors: Loaded word embedding model (lazy loaded)
        allowed_keys: Valid words from the embedding vocabulary
    """

    def __init__(
        self,
        word_model: str = config.WORD_EMBEDDING_MODEL,
        seed_categories: Optional[Dict[str, List[str]]] = None,
        replacements: Optional[Dict[str, str]] = None,
        category_priority: Optional[Dict[str, int]] = None,
        tag_priority: Optional[Dict[str, int]] = None,
    ) -> None:
        """
        Initialize the classifier with word embedding model.

        Args:
            word_model: Name of the gensim word embedding model to load
            seed_categories: Override default seed categories from config
            replacements: Override default tag replacements from config
            category_priority: Override default category priorities from config
            tag_priority: Override default tag priorities from config

        Note:
            Word vectors are lazy-loaded on first access for better performance.
        """
        self._word_model = word_model
        self._word_vectors: Optional[Any] = None
        self._allowed_keys: Optional[List[str]] = None

        # Use provided config or fall back to defaults
        self.seed_categories = seed_categories or config.SEED_CATEGORIES
        self.replacements = replacements or config.TAG_REPLACEMENTS
        self.category_priority = category_priority or config.CATEGORY_PRIORITY
        self.tag_priority = tag_priority or config.TAG_PRIORITY

        # Will be populated during classification
        self._cluster_assignments: Dict[str, List[str]] = {}
        self._cluster_assignments_rev: Dict[str, str] = {}
        self._landuse_key_map: Dict[str, str] = {}

    @property
    def word_vectors(self) -> Any:
        """Lazy-load word vectors on first access."""
        if self._word_vectors is None:
            self._word_vectors = _get_word_vectors(self._word_model)
        return self._word_vectors

    @property
    def allowed_keys(self) -> List[str]:
        """Get allowed vocabulary keys (excludes configured exclusions)."""
        if self._allowed_keys is None:
            self._allowed_keys = list(
                set(self.word_vectors.key_to_index) - set(config.EXCLUDED_WORDS)
            )
        return self._allowed_keys

    def load_shapefile(self, filepath: str | Path) -> gpd.GeoDataFrame:
        """
        Load and preprocess OSM shapefile.

        Args:
            filepath: Path to the input shapefile

        Returns:
            GeoDataFrame containing polygon features

        Raises:
            DataLoadError: If file loading fails
        """
        filepath = Path(filepath)

        if not filepath.exists():
            raise DataLoadError(f"Shapefile not found: {filepath}")

        try:
            logger.info(f"Loading shapefile: {filepath}")
            gdf = gpd.read_file(filepath, encoding="latin1")
        except Exception as e:
            raise DataLoadError(f"Failed to read shapefile: {e}") from e

        # Filter to only polygons
        gdf = gdf[gdf.geometry.geom_type == "Polygon"]

        # Keep only relevant columns
        available_cols = [
            col for col in config.SHAPEFILE_COLUMNS if col in gdf.columns
        ]
        gdf = gdf[available_cols]

        logger.info(f"Loaded {len(gdf)} polygon features")
        return gdf

    def preprocess(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Clean and prepare data for classification.

        Args:
            gdf: Input GeoDataFrame with landuse/natural columns

        Returns:
            Preprocessed GeoDataFrame

        Raises:
            DataLoadError: If no valid features found after preprocessing
        """
        logger.info("Preprocessing data...")

        # Drop rows with no landuse or natural tags
        gdf = gdf.dropna(subset=["landuse", "natural"], how="all").copy()

        if len(gdf) == 0:
            raise DataLoadError("No features with landuse or natural tags found")

        # Merge natural into landuse column
        mask = ~gdf["natural"].isnull()
        gdf.loc[mask, "landuse"] = gdf.loc[mask, "natural"]

        # Filter to ASCII tags only
        gdf = gdf[
            gdf["landuse"].apply(lambda x: x is not None and str(x).isascii())
        ].copy()

        logger.info(f"After preprocessing: {len(gdf)} features")
        return gdf

    def get_tag_statistics(
        self, gdf: gpd.GeoDataFrame
    ) -> Tuple[List[Tuple[str, int]], Set[str]]:
        """
        Get statistics about landuse tags.

        Args:
            gdf: GeoDataFrame with landuse column

        Returns:
            Tuple of (tag counts as list of tuples, set of unique tags)
        """
        tag_counter = Counter(gdf["landuse"]).most_common()
        tag_set = set(gdf["landuse"])

        logger.info(f"Found {len(tag_set)} unique tags")
        logger.debug(f"Top 10 tags: {tag_counter[:10]}")

        return tag_counter, tag_set

    def create_landuse_mapping(self, tag_set: Set[str]) -> Dict[str, str]:
        """
        Create mapping from OSM tags to word vectors.

        Args:
            tag_set: Set of unique landuse tags

        Returns:
            Dictionary mapping original tags to embedding keys
        """
        logger.info("Creating landuse to word vector mapping...")

        # Find tags not in vocabulary or replacements
        unvec_words = sorted(
            tag_set
            - set(self.word_vectors.key_to_index)
            - set(self.replacements.keys())
        )
        logger.debug(f"Unvectorized words ({len(unvec_words)}): {unvec_words}")

        cleaned_tags = list(tag_set - set(unvec_words))
        orig_tags = list(cleaned_tags)

        # Apply replacements (create new list to avoid mutation issues)
        cleaned_tags = [
            self.replacements.get(tag, tag) for tag in cleaned_tags
        ]

        # Create mapping
        landuse_key_map: Dict[str, str] = {}
        for cleaned, orig in zip(cleaned_tags, orig_tags):
            if cleaned in self.allowed_keys:
                landuse_key_map[orig] = cleaned
            elif cleaned.split("_")[-1] in self.allowed_keys:
                landuse_key_map[orig] = cleaned.split("_")[-1]

        logger.info(f"Successfully mapped {len(landuse_key_map)} tags to word vectors")
        self._landuse_key_map = landuse_key_map
        return landuse_key_map

    def cluster_tags(
        self,
        tag_counts: Dict[str, int],
        landuse_key_map: Dict[str, str],
        n_clusters: int = config.CLUSTERING_CONFIG["n_clusters"],
        popular_thresh: float = config.CLUSTERING_CONFIG["popularity_threshold"],
    ) -> Dict[str, int]:
        """
        Perform spectral clustering on popular tags (for analysis).

        Args:
            tag_counts: Dictionary of tag -> count
            landuse_key_map: Mapping from tags to embedding keys
            n_clusters: Number of clusters
            popular_thresh: Minimum frequency threshold for inclusion

        Returns:
            Dictionary mapping tags to cluster IDs
        """
        logger.info(f"Clustering tags with threshold {popular_thresh}...")

        # Calculate tag frequencies
        total_count = sum(tag_counts.values())
        tag_freq = {tag: count / total_count for tag, count in tag_counts.items()}

        # Filter to popular tags with vectors
        popular_tags = {
            tag: freq
            for tag, freq in tag_freq.items()
            if freq > popular_thresh and tag in landuse_key_map
        }

        if not popular_tags:
            logger.warning("No popular tags found for clustering")
            return {}

        logger.info(f"Clustering {len(popular_tags)} popular tags")

        # Get word vectors and add noise (vectorized)
        tag_list = list(popular_tags.keys())
        X_vec = self.word_vectors[[landuse_key_map[tag] for tag in tag_list]]
        noise = 1e-2 * np.random.randn(*X_vec.shape)
        X = X_vec + noise

        # Perform clustering
        clustering = SpectralClustering(
            n_clusters=min(n_clusters, len(X)),
            n_components=config.CLUSTERING_CONFIG["n_components"],
            assign_labels="cluster_qr",
            affinity="nearest_neighbors",
            random_state=config.CLUSTERING_CONFIG["random_state"],
        ).fit(X)

        # Create cluster assignments
        cluster_dict = dict(zip(tag_list, clustering.labels_))

        # Group by cluster for display
        clusters: Dict[int, List[str]] = defaultdict(list)
        for tag, cluster_id in sorted(cluster_dict.items()):
            clusters[cluster_id].append(tag)

        logger.info("Automatic clustering results:")
        for cluster_id, tags in clusters.items():
            logger.info(f"Cluster {cluster_id}: {tags}")

        return cluster_dict

    def assign_categories(
        self,
        tag_counts: Dict[str, int],
        landuse_key_map: Dict[str, str],
    ) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
        """
        Assign all tags to predefined categories using embedding similarity.

        Args:
            tag_counts: Dictionary of tag -> count
            landuse_key_map: Mapping from tags to embedding keys

        Returns:
            Tuple of (category -> tags mapping, tag -> category mapping)

        Raises:
            ClassificationError: If no valid category centroids can be computed
        """
        logger.info("Assigning tags to categories...")

        # Calculate category centroids from seed words
        cat_centroids: Dict[str, np.ndarray] = {}
        for cat_name, tags in self.seed_categories.items():
            valid_tags = [
                landuse_key_map[tag] for tag in tags if tag in landuse_key_map
            ]
            if valid_tags:
                cat_centroids[cat_name] = np.median(
                    self.word_vectors[valid_tags], axis=0
                )

        if not cat_centroids:
            raise ClassificationError(
                "Could not compute any category centroids from seed words"
            )

        # Pre-compute centroid list for vectorized distance calculation
        cat_names = list(cat_centroids.keys())
        centroid_array = np.array([cat_centroids[cat] for cat in cat_names])

        # Assign each tag to nearest category
        cluster_assignments: Dict[str, List[str]] = defaultdict(list)
        for tag in tag_counts:
            if tag in landuse_key_map:
                tag_vector = self.word_vectors[landuse_key_map[tag]]
                distances = np.linalg.norm(centroid_array - tag_vector, axis=1)
                nearest_cat = cat_names[np.argmin(distances)]
                cluster_assignments[nearest_cat].append(tag)

        # Create reverse mapping
        cluster_assignments_rev = {
            tag: cat
            for cat, tags in cluster_assignments.items()
            for tag in tags
        }

        logger.info("Category assignments:")
        for cat, tags in cluster_assignments.items():
            suffix = "..." if len(tags) > 10 else ""
            logger.info(f"{cat} ({len(tags)} tags): {tags[:10]}{suffix}")

        self._cluster_assignments = dict(cluster_assignments)
        self._cluster_assignments_rev = cluster_assignments_rev

        return dict(cluster_assignments), cluster_assignments_rev

    def classify(
        self,
        gdf: gpd.GeoDataFrame,
        cluster_assignments_rev: Dict[str, str],
    ) -> gpd.GeoDataFrame:
        """
        Add classification columns to GeoDataFrame.

        Args:
            gdf: Input GeoDataFrame with landuse column
            cluster_assignments_rev: Mapping from tag to category

        Returns:
            GeoDataFrame with added classification columns

        Raises:
            ClassificationError: If no features could be classified
        """
        logger.info("Classifying features...")

        # Filter to classified tags only
        gdf_classified = gdf[gdf["landuse"].isin(cluster_assignments_rev)].copy()

        if len(gdf_classified) == 0:
            raise ClassificationError("No features could be classified")

        cat_names = list(self.seed_categories.keys())

        # Add classification columns
        gdf_classified["classname"] = gdf_classified["landuse"].map(
            cluster_assignments_rev
        )
        gdf_classified["classvalue"] = gdf_classified["classname"].apply(
            lambda x: cat_names.index(x) + 1
        )

        # Add priority
        def get_priority(row: pd.Series) -> int:
            tag = row["landuse"]
            cat = cluster_assignments_rev[tag]
            return self.tag_priority.get(tag, self.category_priority.get(cat, 1))

        gdf_classified["priority"] = gdf_classified.apply(get_priority, axis=1)

        logger.info(f"Classified {len(gdf_classified)} features into {len(cat_names)} categories")
        logger.info(f"Category distribution:\n{gdf_classified['classname'].value_counts()}")

        return gdf_classified

    def save(
        self,
        gdf: gpd.GeoDataFrame,
        name: str,
        output_path: Optional[str | Path] = None,
    ) -> Path:
        """
        Save classified GeoDataFrame as GeoJSON.

        Args:
            gdf: Classified GeoDataFrame
            name: Name for the file (e.g., "paris")
            output_path: Optional custom path (overrides auto-save to data/classified)

        Returns:
            Path where file was saved

        Raises:
            DataLoadError: If saving fails
        """
        # Determine save path
        if output_path:
            save_path = Path(output_path)
        else:
            filename = _name_to_filename(name) + ".geojson"
            save_path = _get_classified_dir() / filename

        save_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving classified data to: {save_path}")

        # Ensure integer types before saving
        gdf = gdf.copy()
        gdf["classvalue"] = gdf["classvalue"].astype("int32")
        gdf["priority"] = gdf["priority"].astype("int32")

        try:
            gdf.to_file(save_path, driver="GeoJSON")
            logger.info("Saved successfully")
            return save_path
        except Exception as e:
            raise DataLoadError(f"Failed to save: {e}") from e

    def _run_classification_pipeline(
        self,
        gdf: gpd.GeoDataFrame,
        run_clustering: bool = False,
    ) -> gpd.GeoDataFrame:
        """
        Internal method to run the classification pipeline on a GeoDataFrame.

        Args:
            gdf: Preprocessed GeoDataFrame
            run_clustering: Whether to run exploratory clustering analysis

        Returns:
            Classified GeoDataFrame
        """
        # Get statistics
        tag_counts_list, tag_set = self.get_tag_statistics(gdf)
        tag_counts = dict(tag_counts_list)

        # Create embedding mapping
        landuse_key_map = self.create_landuse_mapping(tag_set)

        # Filter counts to mapped tags
        tag_counts_filtered = {
            k: v for k, v in tag_counts.items() if k in landuse_key_map
        }

        # Optional clustering analysis
        if run_clustering:
            self.cluster_tags(tag_counts_filtered, landuse_key_map)

        # Assign to categories
        _, cluster_assignments_rev = self.assign_categories(
            tag_counts_filtered, landuse_key_map
        )

        # Classify GeoDataFrame
        return self.classify(gdf, cluster_assignments_rev)

    def process(
        self,
        input_shapefile: str | Path,
        output_shapefile: Optional[str | Path] = None,
        run_clustering: bool = False,
    ) -> gpd.GeoDataFrame:
        """
        Run the complete classification pipeline.

        Args:
            input_shapefile: Path to input OSM shapefile
            output_shapefile: Optional path to save classified shapefile
            run_clustering: Whether to run exploratory clustering analysis

        Returns:
            Classified GeoDataFrame
        """
        logger.info("=" * 60)
        logger.info("OSM Landcover Classification Pipeline")
        logger.info("=" * 60)

        # Load and preprocess
        gdf = self.load_shapefile(input_shapefile)
        gdf = self.preprocess(gdf)

        # Run classification pipeline
        gdf_classified = self._run_classification_pipeline(gdf, run_clustering)

        # Save if output path provided
        if output_shapefile:
            self.save(gdf_classified, name="output", output_path=output_shapefile)

        logger.info("=" * 60)
        logger.info("Processing complete!")
        logger.info("=" * 60)

        return gdf_classified

    def process_geodataframe(
        self,
        gdf: gpd.GeoDataFrame,
        name: Optional[str] = None,
        output_path: Optional[str | Path] = None,
        run_clustering: bool = False,
    ) -> gpd.GeoDataFrame:
        """
        Run classification pipeline on an existing GeoDataFrame.

        Use this method when you have already loaded data (e.g., from osmnx)
        instead of reading from a shapefile.

        Args:
            gdf: GeoDataFrame with 'landuse' and/or 'natural' columns
            name: Name for saving (e.g., "paris"). Auto-saves to data/classified/{name}.geojson
            output_path: Optional custom path (overrides auto-save)
            run_clustering: Whether to run exploratory clustering analysis

        Returns:
            Classified GeoDataFrame

        Example:
            >>> gdf_classified = classifier.process_geodataframe(gdf, name="paris")
            >>> # Saved to data/classified/paris.geojson
        """
        logger.info("=" * 60)
        logger.info("OSM Landcover Classification Pipeline")
        logger.info("=" * 60)
        logger.info(f"Input: {len(gdf)} features")

        # Preprocess
        gdf = self.preprocess(gdf)

        # Run classification pipeline
        gdf_classified = self._run_classification_pipeline(gdf, run_clustering)

        # Save if name or output path provided
        if name or output_path:
            self.save(gdf_classified, name=name or "output", output_path=output_path)

        logger.info("=" * 60)
        logger.info("Processing complete!")
        logger.info("=" * 60)

        return gdf_classified

    @property
    def category_names(self) -> List[str]:
        """Get list of category names."""
        return list(self.seed_categories.keys())

    @property
    def cluster_assignments(self) -> Dict[str, List[str]]:
        """Get category to tags mapping (populated after assign_categories)."""
        return self._cluster_assignments

    @property
    def tag_to_category(self) -> Dict[str, str]:
        """Get tag to category mapping (populated after assign_categories)."""
        return self._cluster_assignments_rev
