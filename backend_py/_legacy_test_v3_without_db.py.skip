#!/usr/bin/env python3
"""
SOLVEREIGN V3 - Tests Without Database
=======================================

Test V3 modules that don't require database connection.
Safe to run without Docker/PostgreSQL.

Usage:
    python backend_py/test_v3_without_db.py
"""

import sys
from datetime import time


def test_config_module():
    """Test 1: Configuration module."""
    print("\n" + "="*70)
    print("TEST 1: Configuration Module")
    print("="*70)

    try:
        from packs.roster.engine.config import config

        print(f"[OK] Config module imported successfully")
        print(f"\nConfiguration Settings:")
        print(f"   Database: {config.DATABASE_NAME}")
        print(f"   Solver Seed: {config.SOLVER_SEED}")
        print(f"   Freeze Window: {config.FREEZE_WINDOW_MINUTES} minutes")

        # Validate configuration
        warnings = config.validate()
        if warnings:
            print(f"\nConfiguration Warnings:")
            for warning in warnings:
                print(f"   - {warning}")
        else:
            print(f"\n[OK] No configuration warnings")

        return True

    except Exception as e:
        print(f"[FAIL] Test 1 failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_models_module():
    """Test 2: Data models."""
    print("\n" + "="*70)
    print("TEST 2: Data Models")
    print("="*70)

    try:
        from v3 import models

        print(f"[OK] Models module imported successfully")

        # Test tour fingerprint
        print(f"\nTesting Tour Fingerprint:")
        fingerprint = models.compute_tour_fingerprint(
            day=1,
            start=time(6, 0),
            end=time(14, 0),
            depot="Depot Nord"
        )
        print(f"   Fingerprint: {fingerprint}")

        print(f"\n[OK] All model tests passed!")
        return True

    except Exception as e:
        print(f"[FAIL] Test 2 failed: {e}")
        return False


def main():
    """Run all tests."""
    print("="*70)
    print("SOLVEREIGN V3 - Tests Without Database")
    print("="*70)

    results = []
    results.append(("Configuration", test_config_module()))
    results.append(("Data Models", test_models_module()))

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"\n{'='*70}")
    if passed == total:
        print(f"SUCCESS: ALL {total} TESTS PASSED!")
    else:
        print(f"FAILED: {total - passed} of {total} TESTS FAILED")
    print("="*70)


if __name__ == "__main__":
    main()
