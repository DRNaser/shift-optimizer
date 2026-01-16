"""
SOLVEREIGN V3 Configuration
============================

Environment-based configuration with sensible defaults.
Supports .env files via python-dotenv.
"""

import os
from pathlib import Path
from typing import Literal

# Base directory (shift-optimizer/backend_py)
BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    """V3 Configuration with environment variable support."""

    # ========================================================================
    # Database Configuration
    # ========================================================================
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://solvereign:dev_password_change_in_production@localhost:5432/solvereign"
    )
    DATABASE_HOST: str = os.getenv("DATABASE_HOST", "localhost")
    DATABASE_PORT: int = int(os.getenv("DATABASE_PORT", "5432"))
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "solvereign")
    DATABASE_USER: str = os.getenv("DATABASE_USER", "solvereign")
    DATABASE_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "dev_password_change_in_production")

    # ========================================================================
    # Solver Configuration
    # ========================================================================
    SOLVER_SEED: int = int(os.getenv("SOLVER_SEED", "94"))  # Best seed for normal forecast
    SOLVER_SEED_KW51: int = int(os.getenv("SOLVER_SEED_KW51", "18"))  # Best seed for KW51
    SOLVER_NUM_WORKERS: int = int(os.getenv("SOLVER_NUM_WORKERS", "1"))  # Must be 1 for determinism
    SOLVER_TIMEOUT_SECONDS: int = int(os.getenv("SOLVER_TIMEOUT_SECONDS", "300"))  # 5 minutes

    # Memory limit for solver (P2 FIX: OOM Prevention)
    # Default: 6GB (leaves 2GB for OS/other processes in 8GB container)
    # Set to 0 to disable (relies on Docker memory limit only)
    SOLVER_MAX_MEM_MB: int = int(os.getenv("SOLVER_MAX_MEM_MB", "6144"))

    # ========================================================================
    # Operational Rules
    # ========================================================================
    FREEZE_WINDOW_MINUTES: int = int(os.getenv("FREEZE_WINDOW_MINUTES", "720"))  # 12 hours
    FREEZE_WINDOW_BEHAVIOR: Literal["FROZEN", "OVERRIDE_REQUIRED"] = os.getenv(
        "FREEZE_WINDOW_BEHAVIOR", "FROZEN"
    )

    # ========================================================================
    # Parser Configuration
    # ========================================================================
    PARSER_CONFIG_VERSION: str = os.getenv("PARSER_CONFIG_VERSION", "v3.0.0-mvp")
    PARSER_STRICT_MODE: bool = os.getenv("PARSER_STRICT_MODE", "true").lower() == "true"

    # ========================================================================
    # Audit Configuration
    # ========================================================================
    AUDIT_CHECKS_ENABLED: bool = os.getenv("AUDIT_CHECKS_ENABLED", "true").lower() == "true"
    AUDIT_CHECK_COVERAGE: bool = os.getenv("AUDIT_CHECK_COVERAGE", "true").lower() == "true"
    AUDIT_CHECK_REST: bool = os.getenv("AUDIT_CHECK_REST", "true").lower() == "true"
    AUDIT_CHECK_OVERLAP: bool = os.getenv("AUDIT_CHECK_OVERLAP", "true").lower() == "true"
    AUDIT_CHECK_SPAN: bool = os.getenv("AUDIT_CHECK_SPAN", "true").lower() == "true"
    AUDIT_CHECK_REPRODUCIBILITY: bool = os.getenv("AUDIT_CHECK_REPRODUCIBILITY", "true").lower() == "true"

    # ========================================================================
    # Export Configuration
    # ========================================================================
    EXPORT_MATRIX_CSV: bool = os.getenv("EXPORT_MATRIX_CSV", "true").lower() == "true"
    EXPORT_ROSTERS_CSV: bool = os.getenv("EXPORT_ROSTERS_CSV", "true").lower() == "true"
    EXPORT_KPIS_JSON: bool = os.getenv("EXPORT_KPIS_JSON", "true").lower() == "true"
    EXPORT_AUDIT_JSON: bool = os.getenv("EXPORT_AUDIT_JSON", "true").lower() == "true"

    # ========================================================================
    # Logging
    # ========================================================================
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: Literal["json", "text"] = os.getenv("LOG_FORMAT", "json")
    LOG_FILE: Path = BASE_DIR / os.getenv("LOG_FILE", "logs/solvereign.log")

    # ========================================================================
    # Security (Production)
    # ========================================================================
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change_me_in_production_to_random_string")
    ALLOWED_HOSTS: list[str] = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    CORS_ORIGINS: list[str] = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8501"
    ).split(",")

    # ========================================================================
    # Feature Flags
    # ========================================================================
    FEATURE_SLACK_INTEGRATION: bool = os.getenv("FEATURE_SLACK_INTEGRATION", "false").lower() == "true"
    FEATURE_FREEZE_WINDOWS: bool = os.getenv("FEATURE_FREEZE_WINDOWS", "true").lower() == "true"
    FEATURE_DIFF_ENGINE: bool = os.getenv("FEATURE_DIFF_ENGINE", "true").lower() == "true"
    FEATURE_STREAMLIT_UI: bool = os.getenv("FEATURE_STREAMLIT_UI", "true").lower() == "true"

    # ========================================================================
    # Solver Engine Selection (V3 = canonical, V4 = experimental)
    # ========================================================================
    # CRITICAL: V3 is the ONLY production-ready solver. It produces 145 FTE / 0 PT.
    # V4 is experimental R&D only - may timeout or produce PT overflow.
    SOLVER_ENGINE: Literal["v3", "v4"] = os.getenv("SOLVER_ENGINE", "v3")

    # Allow V4 solver output to be published (default: False for safety)
    # Set to "true" ONLY for R&D testing - never in production!
    ALLOW_V4_PUBLISH: bool = os.getenv("ALLOW_V4_PUBLISH", "false").lower() == "true"

    # If True, V4 runs will be BLOCKED from publishing even with ALLOW_V4_PUBLISH=true
    # This is an emergency kill switch for pilot deployment
    V4_PUBLISH_KILL_SWITCH: bool = os.getenv("V4_PUBLISH_KILL_SWITCH", "false").lower() == "true"

    # ========================================================================
    # Development
    # ========================================================================
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    TESTING: bool = os.getenv("TESTING", "false").lower() == "true"

    @classmethod
    def get_connection_string(cls) -> str:
        """Build PostgreSQL connection string from config."""
        return cls.DATABASE_URL

    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production mode."""
        return not cls.DEBUG and not cls.TESTING

    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return list of warnings/errors."""
        warnings = []

        # Check production security
        if cls.is_production():
            if cls.SECRET_KEY == "change_me_in_production_to_random_string":
                warnings.append("SECRET_KEY must be changed in production")
            if "dev_password" in cls.DATABASE_PASSWORD:
                warnings.append("DATABASE_PASSWORD must be changed in production")

        # Check determinism requirements
        if cls.SOLVER_NUM_WORKERS != 1:
            warnings.append(f"SOLVER_NUM_WORKERS={cls.SOLVER_NUM_WORKERS} breaks determinism (must be 1)")

        # Check freeze window logic
        if cls.FREEZE_WINDOW_MINUTES < 0:
            warnings.append(f"FREEZE_WINDOW_MINUTES cannot be negative: {cls.FREEZE_WINDOW_MINUTES}")

        return warnings


# Singleton instance
config = Config()


# Load .env file if exists (optional dependency)
try:
    from dotenv import load_dotenv
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"✅ Loaded environment from {env_file}")
except ImportError:
    pass  # python-dotenv not installed, use OS environment only


# Validate configuration on import
if config_warnings := config.validate():
    print("WARNING: Configuration Warnings:")
    for warning in config_warnings:
        print(f"   - {warning}")
