# Wien Pilot Golden Dataset (46 Vehicles)

## Purpose

This golden dataset provides reproducible test fixtures for the Wien Pilot routing pipeline. It is used to:

1. **Verify Determinism**: Same input MUST produce identical hashes across runs
2. **Regression Testing**: Detect unintended behavior changes
3. **Documentation**: Serve as executable specification

## Files

| File | Description |
|------|-------------|
| `wien_pilot_small.json` | 10-order FLS export for quick testing |
| `expected_canonical.json` | Expected canonicalization results |
| `expected_manifest.json` | Expected manifest structure |

## Dataset Characteristics

- **Orders**: 10 (mix of DELIVERY, PICKUP, SERVICE)
- **Orders with direct coords**: 8
- **Orders with zone fallback**: 1 (ORD-006, PLZ 1220)
- **Orders with H3 fallback**: 1 (ORD-007)
- **Two-person orders**: 2 (ORD-008, ORD-010)
- **Orders with skills**: 2 (INSTALLATION, HEAVY_LIFT)
- **Depots**: 2 (DEPOT-MAIN, DEPOT-SOUTH)

## Expected Verdicts

| Gate | Verdict | Reason |
|------|---------|--------|
| Import Validation | OK | All hard gates pass |
| Coords Quality | WARN | 20% fallback rate (zone/h3), but all resolvable |
| OSRM Finalize | ENABLED | Coords quality is OK or WARN (not BLOCK) |

## Running Tests

```bash
# Run all golden dataset regression tests
pytest backend_py/packs/routing/tests/test_golden_dataset_regression.py -v

# Run specific test class
pytest backend_py/packs/routing/tests/test_golden_dataset_regression.py::TestHashStability -v

# Run with coverage
pytest backend_py/packs/routing/tests/test_golden_dataset_regression.py --cov=backend_py.packs.routing -v
```

## Key Invariants

1. **Hash Stability**: `canonical_hash` MUST be identical for same input
2. **Verdict Stability**: Same input + same policy = same verdict
3. **Order Preservation**: Order sequence is maintained
4. **Metadata Preservation**: Tenant/site IDs preserved

## Updating the Dataset

When adding new test cases:

1. Add orders to `wien_pilot_small.json`
2. Update `expected_canonical.json` with expected stats
3. Run regression tests to verify
4. Document changes in this README

## Related Files

- Policy Profile: `backend_py/packs/routing/policies/profiles/wien_pilot_routing.json`
- Import Contract: `backend_py/packs/routing/contracts/fls_import_contract.schema.json`
- Regression Tests: `backend_py/packs/routing/tests/test_golden_dataset_regression.py`
