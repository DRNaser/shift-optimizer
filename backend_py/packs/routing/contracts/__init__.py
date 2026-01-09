# =============================================================================
# SOLVEREIGN Routing Pack - Import Contracts
# =============================================================================
# JSON schemas and validators for external data imports (FLS, etc.)
# =============================================================================

from pathlib import Path

CONTRACTS_DIR = Path(__file__).parent

FLS_IMPORT_CONTRACT_SCHEMA = CONTRACTS_DIR / "fls_import_contract.schema.json"

__all__ = [
    "CONTRACTS_DIR",
    "FLS_IMPORT_CONTRACT_SCHEMA",
]
