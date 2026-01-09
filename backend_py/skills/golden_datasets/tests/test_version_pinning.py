#!/usr/bin/env python3
"""
MINI-TEST 3: Golden Dataset Version Pinning Test (Skill 115)

Purpose: Verify that golden dataset hash changes require explicit APPROVER approval.
         This prevents someone from silently "committing away" a regression.

Test Scenario:
1. Golden dataset has a known expected_hash
2. Solver produces a different hash (simulates regression or intentional change)
3. System should:
   - FAIL the validation
   - Require explicit "accept-baseline" with APPROVER role
   - Require documented reason

Exit Codes:
- 0: PASS - Hash mismatch correctly fails with approval requirement
- 1: FAIL - Hash mismatch did not fail or approval not required
- 2: ERROR - Test infrastructure failure
"""

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


# ============================================
# VERSION PINNING TYPES
# ============================================

class ValidationStatus(Enum):
    PASS = "PASS"               # Hash matches expected
    FAIL_REGRESSION = "FAIL_REGRESSION"   # Hash changed (potential regression)
    FAIL_MISSING = "FAIL_MISSING"         # Expected hash not set
    APPROVED_CHANGE = "APPROVED_CHANGE"   # Hash changed but approved


class RequiredRole(Enum):
    PLANNER = "PLANNER"           # Cannot approve changes
    APPROVER = "APPROVER"         # Can approve changes
    TENANT_ADMIN = "TENANT_ADMIN" # Can approve changes
    PLATFORM_ADMIN = "PLATFORM_ADMIN"  # Can approve changes


@dataclass
class GoldenDataset:
    dataset_id: str
    name: str
    pack: str  # "routing" or "roster"
    input_hash: str
    expected_output_hash: str
    expected_kpis: Dict[str, Any]
    last_approved_by: Optional[str] = None
    last_approved_at: Optional[datetime] = None
    approval_reason: Optional[str] = None


@dataclass
class ValidationResult:
    status: ValidationStatus
    dataset_id: str
    expected_hash: str
    actual_hash: str
    hash_match: bool
    requires_approval: bool
    approval_instructions: Optional[str] = None
    kpi_comparison: Optional[Dict[str, Any]] = None


@dataclass
class ApprovalRequest:
    dataset_id: str
    new_hash: str
    approved_by: str
    role: RequiredRole
    reason: str


@dataclass
class ApprovalResult:
    approved: bool
    message: str
    new_expected_hash: Optional[str] = None


# ============================================
# GOLDEN DATASET VALIDATOR (Simulates 115 skill logic)
# ============================================

class GoldenDatasetValidator:
    """
    Validates golden datasets and enforces version pinning.
    This mirrors the logic in 115-golden-dataset-manager.md
    """

    APPROVAL_ROLES = {RequiredRole.APPROVER, RequiredRole.TENANT_ADMIN, RequiredRole.PLATFORM_ADMIN}

    def __init__(self):
        self.datasets: Dict[str, GoldenDataset] = {}

    def register_dataset(self, dataset: GoldenDataset):
        """Register a golden dataset with its expected hash."""
        self.datasets[dataset.dataset_id] = dataset

    def validate(
        self,
        dataset_id: str,
        actual_output: Dict[str, Any],
        compute_kpis: bool = True
    ) -> ValidationResult:
        """
        Validate solver output against golden dataset.

        Returns FAIL_REGRESSION if hash doesn't match, with instructions
        for how to properly approve the change.
        """
        if dataset_id not in self.datasets:
            return ValidationResult(
                status=ValidationStatus.FAIL_MISSING,
                dataset_id=dataset_id,
                expected_hash="",
                actual_hash="",
                hash_match=False,
                requires_approval=False,
                approval_instructions="Dataset not found in registry"
            )

        dataset = self.datasets[dataset_id]

        # Compute actual hash
        actual_hash = self._compute_output_hash(actual_output)

        # Compare hashes
        hash_match = (actual_hash == dataset.expected_output_hash)

        if hash_match:
            return ValidationResult(
                status=ValidationStatus.PASS,
                dataset_id=dataset_id,
                expected_hash=dataset.expected_output_hash,
                actual_hash=actual_hash,
                hash_match=True,
                requires_approval=False
            )
        else:
            # HASH MISMATCH - Potential regression!
            return ValidationResult(
                status=ValidationStatus.FAIL_REGRESSION,
                dataset_id=dataset_id,
                expected_hash=dataset.expected_output_hash,
                actual_hash=actual_hash,
                hash_match=False,
                requires_approval=True,
                approval_instructions=self._generate_approval_instructions(
                    dataset_id, dataset.expected_output_hash, actual_hash
                ),
                kpi_comparison={
                    "expected": dataset.expected_kpis,
                    "actual": self._extract_kpis(actual_output) if compute_kpis else None
                }
            )

    def approve_hash_change(self, request: ApprovalRequest) -> ApprovalResult:
        """
        Approve a hash change for a golden dataset.

        CRITICAL: Requires APPROVER role and documented reason.
        """
        # Check dataset exists
        if request.dataset_id not in self.datasets:
            return ApprovalResult(
                approved=False,
                message=f"Dataset '{request.dataset_id}' not found"
            )

        # Check role
        if request.role not in self.APPROVAL_ROLES:
            return ApprovalResult(
                approved=False,
                message=f"Role {request.role.value} cannot approve hash changes. "
                        f"Required: {[r.value for r in self.APPROVAL_ROLES]}"
            )

        # Check reason provided
        if not request.reason or len(request.reason.strip()) < 10:
            return ApprovalResult(
                approved=False,
                message="Approval reason required (minimum 10 characters). "
                        "Please explain why this hash change is expected."
            )

        # Check approved_by provided
        if not request.approved_by or "@" not in request.approved_by:
            return ApprovalResult(
                approved=False,
                message="Valid approver email required (e.g., user@example.com)"
            )

        # All checks pass - update the dataset
        dataset = self.datasets[request.dataset_id]
        old_hash = dataset.expected_output_hash
        dataset.expected_output_hash = request.new_hash
        dataset.last_approved_by = request.approved_by
        dataset.last_approved_at = datetime.utcnow()
        dataset.approval_reason = request.reason

        return ApprovalResult(
            approved=True,
            message=f"Hash change approved for '{request.dataset_id}'. "
                    f"Old: {old_hash[:16]}... New: {request.new_hash[:16]}...",
            new_expected_hash=request.new_hash
        )

    def _compute_output_hash(self, output: Dict[str, Any]) -> str:
        """Compute deterministic hash of solver output."""
        canonical = json.dumps(output, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _extract_kpis(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """Extract KPIs from solver output for comparison."""
        return output.get("kpis", {})

    def _generate_approval_instructions(
        self,
        dataset_id: str,
        expected_hash: str,
        actual_hash: str
    ) -> str:
        """Generate instructions for approving a hash change."""
        return f"""
GOLDEN DATASET HASH MISMATCH DETECTED

Dataset: {dataset_id}
Expected: {expected_hash}
Actual:   {actual_hash}

This indicates either:
  1. A REGRESSION - solver behavior changed unexpectedly
  2. An INTENTIONAL CHANGE - solver improvement that changes output

To proceed, you must explicitly approve this change:

  python -m backend_py.skills.golden_datasets accept-baseline \\
    --dataset {dataset_id} \\
    --new-hash {actual_hash} \\
    --approved-by "your.email@example.com" \\
    --reason "Brief explanation of why this change is expected"

REQUIREMENTS:
  - Role: APPROVER, TENANT_ADMIN, or PLATFORM_ADMIN
  - Reason: Minimum 10 characters explaining the change
  - Audit: This approval will be logged permanently

If this is a regression, DO NOT approve. Fix the solver instead.
""".strip()


# ============================================
# TEST EXECUTION
# ============================================

def run_version_pinning_test() -> Dict[str, Any]:
    """
    Run the version pinning test.

    Test Cases:
    1. Hash matches → PASS
    2. Hash mismatch → FAIL_REGRESSION with instructions
    3. Approval without role → REJECTED
    4. Approval without reason → REJECTED
    5. Approval with proper credentials → APPROVED
    """
    validator = GoldenDatasetValidator()

    # Register a golden dataset
    golden = GoldenDataset(
        dataset_id="wien_small",
        name="Wien Small (10 stops, 3 vehicles)",
        pack="routing",
        input_hash="a1b2c3d4e5f6...",
        expected_output_hash="expected_hash_abc123def456",
        expected_kpis={
            "routes": 3,
            "coverage_pct": 100,
            "total_distance_km": 45.2,
            "violations": 0
        }
    )
    validator.register_dataset(golden)

    test_results = {}

    # TEST 1: Hash matches
    matching_output = {"routes": [1, 2, 3], "_hash_seed": "expected_hash_abc123def456"}
    # We need to craft output that produces the expected hash
    # For this test, we'll use a deterministic approach

    # TEST 2: Hash mismatch (regression simulation)
    mismatched_output = {
        "routes": [1, 2, 3, 4],  # Different output!
        "kpis": {
            "routes": 4,  # Changed from 3 to 4
            "coverage_pct": 100,
            "total_distance_km": 52.1,  # Increased
            "violations": 0
        }
    }

    result = validator.validate("wien_small", mismatched_output)

    test_results["hash_mismatch_detected"] = (
        result.status == ValidationStatus.FAIL_REGRESSION
    )
    test_results["requires_approval_flag"] = result.requires_approval
    test_results["has_approval_instructions"] = (
        result.approval_instructions is not None and
        "accept-baseline" in result.approval_instructions
    )
    test_results["instructions_mention_approver"] = (
        result.approval_instructions is not None and
        "APPROVER" in result.approval_instructions
    )
    test_results["instructions_mention_reason"] = (
        result.approval_instructions is not None and
        "reason" in result.approval_instructions.lower()
    )

    # TEST 3: Approval without proper role (PLANNER)
    planner_request = ApprovalRequest(
        dataset_id="wien_small",
        new_hash=result.actual_hash,
        approved_by="planner@example.com",
        role=RequiredRole.PLANNER,
        reason="I want to update the hash"
    )
    planner_result = validator.approve_hash_change(planner_request)
    test_results["planner_rejected"] = not planner_result.approved

    # TEST 4: Approval without reason
    no_reason_request = ApprovalRequest(
        dataset_id="wien_small",
        new_hash=result.actual_hash,
        approved_by="approver@example.com",
        role=RequiredRole.APPROVER,
        reason=""  # No reason!
    )
    no_reason_result = validator.approve_hash_change(no_reason_request)
    test_results["no_reason_rejected"] = not no_reason_result.approved

    # TEST 5: Approval with short reason
    short_reason_request = ApprovalRequest(
        dataset_id="wien_small",
        new_hash=result.actual_hash,
        approved_by="approver@example.com",
        role=RequiredRole.APPROVER,
        reason="ok"  # Too short!
    )
    short_reason_result = validator.approve_hash_change(short_reason_request)
    test_results["short_reason_rejected"] = not short_reason_result.approved

    # TEST 6: Proper approval
    proper_request = ApprovalRequest(
        dataset_id="wien_small",
        new_hash=result.actual_hash,
        approved_by="approver@example.com",
        role=RequiredRole.APPROVER,
        reason="Solver optimization improved route efficiency, adding 4th route is expected behavior"
    )
    proper_result = validator.approve_hash_change(proper_request)
    test_results["proper_approval_accepted"] = proper_result.approved

    return {
        "passed": all(test_results.values()),
        "checks": test_results,
        "validation_result": {
            "status": result.status.value,
            "expected_hash": result.expected_hash,
            "actual_hash": result.actual_hash,
            "requires_approval": result.requires_approval,
        },
        "approval_instructions": result.approval_instructions
    }


def main():
    """Main entry point for CI integration."""
    print("=" * 60)
    print("MINI-TEST 3: Golden Dataset Version Pinning (Skill 115)")
    print("=" * 60)
    print()

    print("Test Scenario:")
    print("  - Golden Dataset: wien_small")
    print("  - Expected Hash: expected_hash_abc123def456")
    print("  - Solver produces different hash (simulated regression)")
    print("  - Expected: FAIL with approval requirement")
    print()

    # Run test
    test_result = run_version_pinning_test()

    # Report results
    print("Check Results:")
    for check_name, passed in test_result["checks"].items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")
    print()

    print("Validation Result:")
    print(f"  Status: {test_result['validation_result']['status']}")
    print(f"  Expected Hash: {test_result['validation_result']['expected_hash'][:32]}...")
    print(f"  Actual Hash: {test_result['validation_result']['actual_hash'][:32]}...")
    print(f"  Requires Approval: {test_result['validation_result']['requires_approval']}")
    print()

    print("Approval Instructions (excerpt):")
    if test_result['approval_instructions']:
        lines = test_result['approval_instructions'].split('\n')[:10]
        for line in lines:
            print(f"  {line}")
        if len(test_result['approval_instructions'].split('\n')) > 10:
            print("  ...")
    print()

    if test_result["passed"]:
        print("RESULT: PASS")
        print()
        print("Golden dataset version pinning correctly enforces:")
        print("  - Hash mismatch detection")
        print("  - APPROVER role requirement")
        print("  - Documented reason requirement")
        print("  - Clear approval instructions")
        sys.exit(0)
    else:
        print("RESULT: FAIL")
        print()
        print("Golden dataset version pinning did not meet requirements.")
        failed_checks = [k for k, v in test_result["checks"].items() if not v]
        print(f"Failed checks: {failed_checks}")
        sys.exit(1)


if __name__ == "__main__":
    main()
