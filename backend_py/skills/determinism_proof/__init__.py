"""
Determinism Proof Skill (Skill 103)
===================================

Validates solver determinism by running multiple iterations with the same
seed and verifying all produce identical output hashes.

CLI:
    python -m backend_py.skills.determinism_proof --mode quick
    python -m backend_py.skills.determinism_proof --mode full --runs 10
"""

from .prover import DeterminismProver

__all__ = ["DeterminismProver"]
