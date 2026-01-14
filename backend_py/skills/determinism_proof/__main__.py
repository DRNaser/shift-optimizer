#!/usr/bin/env python3
"""
Determinism Proof CLI (Skill 103)
=================================

Validates solver determinism by running multiple iterations.

Usage:
    # Quick mode (3 runs)
    python -m backend_py.skills.determinism_proof --mode quick

    # Full mode (10 runs)
    python -m backend_py.skills.determinism_proof --mode full --runs 10

    # Custom runs with output
    python -m backend_py.skills.determinism_proof --runs 5 --output result.json

Exit codes:
    0: PASS - All runs produced identical hashes
    1: FAIL - Hashes differ (non-deterministic)
    2: ERROR - Infrastructure error
"""

import argparse
import json
import sys

from .prover import DeterminismProver


def main():
    parser = argparse.ArgumentParser(
        description="Determinism Proof - Validate solver produces identical results"
    )
    parser.add_argument(
        "--mode",
        choices=["quick", "full"],
        default="quick",
        help="Test mode: quick (3 runs) or full (10 runs)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        help="Override number of runs (default: 3 for quick, 10 for full)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=94,
        help="Solver seed (default: 94 - golden seed)"
    )
    parser.add_argument(
        "--output",
        default="determinism_proof.json",
        help="Output file for results"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    # Determine run count
    if args.runs:
        runs = args.runs
    elif args.mode == "full":
        runs = 10
    else:
        runs = 3

    print("=" * 60)
    print("DETERMINISM PROOF (Skill 103)")
    print("=" * 60)
    print(f"\nMode: {args.mode}")
    print(f"Runs: {runs}")
    print(f"Seed: {args.seed}")
    print("=" * 60)

    # Run proof
    prover = DeterminismProver(seed=args.seed, verbose=args.verbose)
    result = prover.prove(runs=runs)

    # Save result
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    # Print result
    print("\n--- Result ---")
    if result.error:
        print(f"[ERROR] {result.error}")
        print(f"\nResult saved to: {args.output}")
        sys.exit(2)

    if result.passed:
        print(f"[PASS] All {result.runs_completed} runs produced identical hashes")
        print(f"  Unique hashes: {result.unique_hashes}")
        print(f"  Hash: {result.hashes[0][:32]}...")
        print(f"  FTE: {result.fte_counts[0]}")
        print(f"  PT: {result.pt_counts[0]}")
    else:
        print(f"[FAIL] Non-deterministic! Found {result.unique_hashes} unique hashes")
        print(f"  Runs completed: {result.runs_completed}")
        print(f"  Unique hashes:")
        for h in set(result.hashes):
            print(f"    - {h[:32]}...")

    print(f"\nResult saved to: {args.output}")
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
