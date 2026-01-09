# =============================================================================
# SOLVEREIGN Configuration - Artifact Store
# =============================================================================
# Configuration for artifact storage across environments.
#
# Supports:
# - Local filesystem (development)
# - AWS S3 / MinIO (staging/production)
# - Azure Blob Storage (production)
# =============================================================================

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================

class ArtifactStoreType(str, Enum):
    """Artifact store backend types."""
    LOCAL = "local"
    S3 = "s3"
    AZURE_BLOB = "azure_blob"
    MINIO = "minio"


class Environment(str, Enum):
    """Deployment environments."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class ArtifactStoreConfig:
    """Configuration for artifact store."""

    # Store type
    store_type: ArtifactStoreType = ArtifactStoreType.LOCAL

    # Local storage
    local_base_path: str = "./data/artifacts"

    # S3/MinIO configuration
    s3_bucket: str = ""
    s3_prefix: str = "artifacts/"
    s3_region: str = "eu-central-1"
    s3_endpoint_url: Optional[str] = None  # For MinIO
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[str] = None

    # Azure Blob configuration
    azure_connection_string: Optional[str] = None
    azure_container: str = "solvereign-artifacts"
    azure_prefix: str = "artifacts/"

    # Common settings
    hash_algorithm: str = "sha256"
    enable_integrity_check: bool = True
    retention_days: int = 365

    # Artifact types to store
    store_artifacts: Dict[str, bool] = field(default_factory=lambda: {
        "raw_blob": True,
        "canonical_orders": True,
        "validation_report": True,
        "drift_report": True,
        "fallback_report": True,
        "routing_evidence": True,
        "plan_evidence": True,
        "import_run": True,
    })

    @classmethod
    def from_environment(cls, env: Optional[Environment] = None) -> "ArtifactStoreConfig":
        """
        Create config from environment variables.

        Environment variables:
        - SOLVEREIGN_ARTIFACT_STORE_TYPE: local, s3, azure_blob, minio
        - SOLVEREIGN_ARTIFACT_LOCAL_PATH: Path for local storage
        - SOLVEREIGN_S3_BUCKET: S3 bucket name
        - SOLVEREIGN_S3_PREFIX: S3 key prefix
        - SOLVEREIGN_S3_REGION: AWS region
        - SOLVEREIGN_S3_ENDPOINT_URL: Custom endpoint (MinIO)
        - AWS_ACCESS_KEY_ID: S3 access key
        - AWS_SECRET_ACCESS_KEY: S3 secret key
        - SOLVEREIGN_AZURE_CONNECTION_STRING: Azure connection string
        - SOLVEREIGN_AZURE_CONTAINER: Azure container name
        """
        if env is None:
            env_str = os.environ.get("SOLVEREIGN_ENVIRONMENT", "development")
            env = Environment(env_str.lower())

        store_type_str = os.environ.get("SOLVEREIGN_ARTIFACT_STORE_TYPE", "local")

        return cls(
            store_type=ArtifactStoreType(store_type_str.lower()),
            local_base_path=os.environ.get(
                "SOLVEREIGN_ARTIFACT_LOCAL_PATH",
                "./data/artifacts"
            ),
            s3_bucket=os.environ.get("SOLVEREIGN_S3_BUCKET", ""),
            s3_prefix=os.environ.get("SOLVEREIGN_S3_PREFIX", "artifacts/"),
            s3_region=os.environ.get("SOLVEREIGN_S3_REGION", "eu-central-1"),
            s3_endpoint_url=os.environ.get("SOLVEREIGN_S3_ENDPOINT_URL"),
            s3_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            s3_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            azure_connection_string=os.environ.get("SOLVEREIGN_AZURE_CONNECTION_STRING"),
            azure_container=os.environ.get(
                "SOLVEREIGN_AZURE_CONTAINER",
                "solvereign-artifacts"
            ),
            azure_prefix=os.environ.get("SOLVEREIGN_AZURE_PREFIX", "artifacts/"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (without secrets)."""
        return {
            "store_type": self.store_type.value,
            "local_base_path": self.local_base_path,
            "s3_bucket": self.s3_bucket,
            "s3_prefix": self.s3_prefix,
            "s3_region": self.s3_region,
            "s3_endpoint_url": self.s3_endpoint_url,
            "s3_has_credentials": bool(self.s3_access_key_id),
            "azure_container": self.azure_container,
            "azure_prefix": self.azure_prefix,
            "azure_has_connection_string": bool(self.azure_connection_string),
            "hash_algorithm": self.hash_algorithm,
            "enable_integrity_check": self.enable_integrity_check,
            "retention_days": self.retention_days,
            "store_artifacts": self.store_artifacts,
        }


# =============================================================================
# ENVIRONMENT PRESETS
# =============================================================================

def get_development_config() -> ArtifactStoreConfig:
    """Get development (local) configuration."""
    return ArtifactStoreConfig(
        store_type=ArtifactStoreType.LOCAL,
        local_base_path="./data/artifacts",
    )


def get_staging_config() -> ArtifactStoreConfig:
    """
    Get staging configuration.

    Staging uses S3 with environment-specific bucket.
    """
    return ArtifactStoreConfig(
        store_type=ArtifactStoreType.S3,
        s3_bucket=os.environ.get("SOLVEREIGN_S3_BUCKET", "solvereign-staging-artifacts"),
        s3_prefix="artifacts/staging/",
        s3_region=os.environ.get("SOLVEREIGN_S3_REGION", "eu-central-1"),
        s3_endpoint_url=os.environ.get("SOLVEREIGN_S3_ENDPOINT_URL"),
        s3_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        s3_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        enable_integrity_check=True,
        retention_days=90,
    )


def get_production_config() -> ArtifactStoreConfig:
    """
    Get production configuration.

    Production uses Azure Blob Storage for compliance.
    """
    return ArtifactStoreConfig(
        store_type=ArtifactStoreType.AZURE_BLOB,
        azure_connection_string=os.environ.get("SOLVEREIGN_AZURE_CONNECTION_STRING"),
        azure_container=os.environ.get("SOLVEREIGN_AZURE_CONTAINER", "solvereign-prod-artifacts"),
        azure_prefix="artifacts/prod/",
        enable_integrity_check=True,
        retention_days=365,
    )


def get_artifact_store_config(env: Optional[Environment] = None) -> ArtifactStoreConfig:
    """
    Get artifact store config for environment.

    Args:
        env: Target environment (or detect from SOLVEREIGN_ENVIRONMENT)

    Returns:
        ArtifactStoreConfig for the environment
    """
    if env is None:
        env_str = os.environ.get("SOLVEREIGN_ENVIRONMENT", "development")
        env = Environment(env_str.lower())

    if env == Environment.DEVELOPMENT:
        return get_development_config()
    elif env == Environment.STAGING:
        return get_staging_config()
    elif env == Environment.PRODUCTION:
        return get_production_config()
    else:
        return get_development_config()


# =============================================================================
# ARTIFACT STORE FACTORY
# =============================================================================

def get_artifact_store(config: Optional[ArtifactStoreConfig] = None):
    """
    Get artifact store instance based on config.

    Args:
        config: Optional config (or auto-detect from environment)

    Returns:
        ArtifactStore instance
    """
    if config is None:
        config = get_artifact_store_config()

    # Import here to avoid circular imports
    from backend_py.packs.routing.services.evidence.artifact_store import (
        LocalArtifactStore,
        S3ArtifactStore,
        AzureBlobArtifactStore,
    )

    if config.store_type == ArtifactStoreType.LOCAL:
        return LocalArtifactStore(
            base_path=Path(config.local_base_path),
            hash_algorithm=config.hash_algorithm,
        )

    elif config.store_type in (ArtifactStoreType.S3, ArtifactStoreType.MINIO):
        return S3ArtifactStore(
            bucket_name=config.s3_bucket,
            prefix=config.s3_prefix,
            region=config.s3_region,
            endpoint_url=config.s3_endpoint_url,
            access_key_id=config.s3_access_key_id,
            secret_access_key=config.s3_secret_access_key,
            hash_algorithm=config.hash_algorithm,
        )

    elif config.store_type == ArtifactStoreType.AZURE_BLOB:
        return AzureBlobArtifactStore(
            connection_string=config.azure_connection_string,
            container_name=config.azure_container,
            prefix=config.azure_prefix,
            hash_algorithm=config.hash_algorithm,
        )

    else:
        raise ValueError(f"Unknown store type: {config.store_type}")
