#!/usr/bin/env python3
# =============================================================================
# SOLVEREIGN Routing Pack - Matrix Generation CLI
# =============================================================================
# Generate static travel time matrices from OSRM.
#
# Usage:
#   python -m backend_py.packs.routing.cli.generate_matrix --help
#   python -m backend_py.packs.routing.cli.generate_matrix \
#       --locations locations.csv \
#       --version wien_2026w02_v1 \
#       --output data/matrices/
#
#   python -m backend_py.packs.routing.cli.generate_matrix \
#       --validate data/matrices/wien_2026w02_v1.csv
# =============================================================================

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import List, Tuple

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend_py.packs.routing.services.travel_time.matrix_generator import (
    MatrixGenerator,
    MatrixGeneratorConfig,
    MatrixGeneratorError,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_locations_from_csv(csv_path: str) -> List[Tuple[float, float]]:
    """
    Load locations from CSV file.

    Expected format:
        lat,lng
        48.2082,16.3738
        48.2206,16.4097
        ...

    Or with headers:
        latitude,longitude
        48.2082,16.3738
        ...
    """
    locations = []
    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        # Check if first row is header or data
        if header:
            try:
                lat, lng = float(header[0]), float(header[1])
                locations.append((lat, lng))
            except ValueError:
                pass  # It's a header, skip

        for row in reader:
            if len(row) >= 2:
                try:
                    lat = float(row[0])
                    lng = float(row[1])
                    locations.append((lat, lng))
                except ValueError:
                    logger.warning(f"Skipping invalid row: {row}")

    return locations


def generate_command(args):
    """Generate matrix from locations."""
    logger.info("=" * 60)
    logger.info("SOLVEREIGN Matrix Generator")
    logger.info("=" * 60)

    # Load locations
    if args.locations:
        logger.info(f"Loading locations from: {args.locations}")
        locations = load_locations_from_csv(args.locations)
    elif args.sample:
        # Sample Vienna locations for testing
        logger.info("Using sample Vienna locations")
        locations = [
            (48.2082, 16.3738),  # Stephansplatz
            (48.2206, 16.4097),  # Prater
            (48.1986, 16.3417),  # Schonbrunn
            (48.2553, 16.2844),  # Klosterneuburg
            (48.1663, 16.4078),  # Schwechat
            (48.2486, 16.3561),  # Floridsdorf
            (48.1851, 16.3122),  # Liesing
            (48.2340, 16.4130),  # Donaustadt
            (48.1920, 16.3850),  # Simmering
            (48.2300, 16.3200),  # Hernals
        ]
    else:
        logger.error("Must specify --locations or --sample")
        return 1

    logger.info(f"Loaded {len(locations)} locations")

    # Configure generator
    config = MatrixGeneratorConfig(
        osrm_url=args.osrm_url,
        output_dir=args.output,
        batch_size=args.batch_size,
        timeout_seconds=args.timeout,
    )

    # Generate matrix
    try:
        with MatrixGenerator(config) as generator:
            result = generator.generate_from_locations(
                locations=locations,
                version_id=args.version,
            )

            logger.info("")
            logger.info("=" * 60)
            logger.info("Generation Complete!")
            logger.info("=" * 60)
            logger.info(f"Version:        {result.version_id}")
            logger.info(f"Locations:      {result.location_count}")
            logger.info(f"Total legs:     {result.total_legs}")
            logger.info(f"Rows written:   {result.row_count}")
            logger.info(f"Content hash:   {result.content_hash[:16]}...")
            logger.info(f"OSRM map hash:  {result.osrm_map_hash}")
            logger.info(f"Generation time: {result.generation_time_seconds:.2f}s")
            logger.info(f"Output file:    {result.csv_path}")
            logger.info("")

            if args.json:
                print(result.to_json())

            return 0

    except MatrixGeneratorError as e:
        logger.error(f"Matrix generation failed: {e}")
        return 1


def validate_command(args):
    """Validate existing matrix."""
    logger.info("=" * 60)
    logger.info("SOLVEREIGN Matrix Validator")
    logger.info("=" * 60)
    logger.info(f"Validating: {args.validate}")

    config = MatrixGeneratorConfig()
    generator = MatrixGenerator(config)

    result = generator.validate_matrix(args.validate)

    logger.info("")
    if result.valid:
        logger.info("VALIDATION: PASS")
    else:
        logger.error("VALIDATION: FAIL")

    logger.info(f"Rows:       {result.row_count}")
    logger.info(f"Locations:  {result.location_count}")
    logger.info(f"Hash:       {result.content_hash[:16]}...")

    if result.errors:
        logger.error(f"Errors ({len(result.errors)}):")
        for err in result.errors[:10]:  # Show first 10
            logger.error(f"  - {err}")

    if result.warnings:
        logger.warning(f"Warnings ({len(result.warnings)}):")
        for warn in result.warnings[:10]:
            logger.warning(f"  - {warn}")

    if args.json:
        print(json.dumps({
            "valid": result.valid,
            "csv_path": result.csv_path,
            "row_count": result.row_count,
            "location_count": result.location_count,
            "content_hash": result.content_hash,
            "errors": result.errors,
            "warnings": result.warnings,
        }, indent=2))

    return 0 if result.valid else 1


def main():
    parser = argparse.ArgumentParser(
        description="SOLVEREIGN Matrix Generator - Generate travel time matrices from OSRM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate from locations CSV
  python -m backend_py.packs.routing.cli.generate_matrix \\
      --locations data/locations.csv \\
      --version wien_2026w02_v1

  # Generate with sample Vienna locations (for testing)
  python -m backend_py.packs.routing.cli.generate_matrix \\
      --sample \\
      --version test_v1

  # Validate existing matrix
  python -m backend_py.packs.routing.cli.generate_matrix \\
      --validate data/matrices/wien_2026w02_v1.csv
        """,
    )

    # Generation options
    parser.add_argument(
        "--locations",
        help="Path to CSV file with locations (lat,lng per row)",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Use sample Vienna locations for testing",
    )
    parser.add_argument(
        "--version",
        default="generated_v1",
        help="Version ID for the generated matrix (default: generated_v1)",
    )
    parser.add_argument(
        "--output",
        default="data/matrices",
        help="Output directory (default: data/matrices)",
    )

    # Validation option
    parser.add_argument(
        "--validate",
        help="Validate existing matrix CSV instead of generating",
    )

    # OSRM options
    parser.add_argument(
        "--osrm-url",
        default="http://localhost:5000",
        help="OSRM server URL (default: http://localhost:5000)",
    )

    # Performance options
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Max locations per OSRM request (default: 100)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="OSRM request timeout in seconds (default: 30)",
    )

    # Output options
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Route to command
    if args.validate:
        return validate_command(args)
    elif args.locations or args.sample:
        return generate_command(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
