"""
Main entry point for OSM Landcover Classification.

Run from command line:
    python -m OSM_auto_label.main --input data.shp --output classified.shp
"""

from __future__ import annotations

import argparse
import logging
import logging.config
import sys
from pathlib import Path

from .classifier import (
    OSMLandcoverClassifier,
    WordEmbeddingError,
    DataLoadError,
    ClassificationError,
)
from .visualizer import LandcoverMapVisualizer, VisualizationError
from . import config

# Configure module logger
logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """
    Configure logging for the application.

    Args:
        verbose: If True, set log level to DEBUG
    """
    log_config = config.LOGGING_CONFIG.copy()
    if verbose:
        log_config["handlers"]["console"]["level"] = "DEBUG"
        log_config["loggers"]["OSM_auto_label"]["level"] = "DEBUG"
    logging.config.dictConfig(log_config)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Classify OSM landuse data into landcover categories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic usage
    python -m OSM_auto_label.main -i input.shp -o classified.shp

    # With visualization
    python -m OSM_auto_label.main -i input.shp -o classified.shp -m map.html

    # Run clustering analysis
    python -m OSM_auto_label.main -i input.shp -o classified.shp --cluster
        """,
    )

    parser.add_argument(
        "-i", "--input",
        type=str,
        required=True,
        help="Path to input OSM shapefile",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        required=True,
        help="Path for output classified shapefile",
    )
    parser.add_argument(
        "-m", "--map",
        type=str,
        default=None,
        help="Path for output HTML map (optional)",
    )
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Run clustering analysis (for exploration)",
    )
    parser.add_argument(
        "--category-layers",
        action="store_true",
        help="Create separate map layers for each category",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (debug) output",
    )

    return parser.parse_args()


def main() -> int:
    """
    Main execution function.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    args = parse_args()

    # Setup logging
    if not args.quiet:
        setup_logging(verbose=args.verbose)
    else:
        logging.disable(logging.CRITICAL)

    # Validate input file
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1

    try:
        # Initialize classifier
        logger.info("=" * 60)
        logger.info("OSM Landcover Classification")
        logger.info("=" * 60)

        classifier = OSMLandcoverClassifier()

        # Run classification pipeline
        gdf_classified = classifier.process(
            input_shapefile=args.input,
            output_shapefile=args.output,
            run_clustering=args.cluster,
        )

        # Create visualization if requested
        if args.map:
            visualizer = LandcoverMapVisualizer()
            visualizer.create_landcover_map(
                gdf_classified,
                output_path=args.map,
                show_category_layers=args.category_layers,
            )

        # Print summary
        logger.info("-" * 40)
        logger.info("Summary:")
        logger.info(f"  Input:  {args.input}")
        logger.info(f"  Output: {args.output}")
        if args.map:
            logger.info(f"  Map:    {args.map}")
        logger.info(f"  Features classified: {len(gdf_classified)}")
        logger.info("-" * 40)

        return 0

    except WordEmbeddingError as e:
        logger.error(f"Word embedding error: {e}")
        return 1
    except DataLoadError as e:
        logger.error(f"Data loading error: {e}")
        return 1
    except ClassificationError as e:
        logger.error(f"Classification error: {e}")
        return 1
    except VisualizationError as e:
        logger.error(f"Visualization error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.warning("Operation cancelled by user")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
