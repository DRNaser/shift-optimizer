# =============================================================================
# SOLVEREIGN Routing Pack - Policy Profiles
# =============================================================================
# Pre-configured policy profiles for different tenants/sites.
# =============================================================================

from pathlib import Path
import json
from typing import Dict, Any, Optional

PROFILES_DIR = Path(__file__).parent


def load_profile(profile_name: str) -> Dict[str, Any]:
    """
    Load a policy profile by name.

    Args:
        profile_name: Name of the profile (without .json extension)

    Returns:
        Policy profile as dict

    Raises:
        FileNotFoundError: If profile doesn't exist
    """
    profile_path = PROFILES_DIR / f"{profile_name}.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"Profile not found: {profile_name}")

    with open(profile_path, "r") as f:
        return json.load(f)


def get_available_profiles() -> list:
    """Get list of available profile names."""
    return [
        p.stem for p in PROFILES_DIR.glob("*.json")
        if not p.name.startswith("_")
    ]


__all__ = [
    "PROFILES_DIR",
    "load_profile",
    "get_available_profiles",
]
