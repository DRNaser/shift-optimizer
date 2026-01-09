"""
SOLVEREIGN SaaS - Azure Blob Artifact Store
============================================

Production artifact storage with lifecycle management.

Storage Tiers (per user decision):
- Hot: Recent evidence (0-30 days) - LRS
- Cool: Older evidence (30-90 days) - auto-transition
- Archive: Historical evidence (90+ days) - auto-archive

Features:
- Tenant-isolated blob paths
- Signed URL generation for secure downloads
- Automatic lifecycle management via Azure policies
- Evidence linking to solver runs
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, BinaryIO, Union
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ArtifactMetadata:
    """Metadata for a stored artifact."""
    artifact_id: str
    tenant_id: int
    site_id: int
    artifact_type: str  # "evidence_pack", "solver_result", "audit_report"
    run_id: Optional[str]
    plan_version_id: Optional[int]
    blob_path: str
    content_hash: str
    size_bytes: int
    created_at: datetime
    tier: str  # "Hot", "Cool", "Archive"
    download_url: Optional[str] = None


class ArtifactStore:
    """
    Abstract artifact store interface.

    Implementations:
    - AzureBlobArtifactStore: Production (Azure Blob Storage)
    - LocalFileArtifactStore: Development (local filesystem)
    """

    async def store(
        self,
        tenant_id: int,
        site_id: int,
        artifact_type: str,
        content: Union[bytes, BinaryIO, Dict],
        run_id: Optional[str] = None,
        plan_version_id: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> ArtifactMetadata:
        """Store an artifact and return metadata."""
        raise NotImplementedError

    async def get(self, artifact_id: str, tenant_id: int) -> Optional[bytes]:
        """Retrieve artifact content."""
        raise NotImplementedError

    async def get_metadata(self, artifact_id: str, tenant_id: int) -> Optional[ArtifactMetadata]:
        """Get artifact metadata without content."""
        raise NotImplementedError

    async def get_download_url(self, artifact_id: str, tenant_id: int, expires_in: int = 3600) -> Optional[str]:
        """Generate a signed download URL."""
        raise NotImplementedError

    async def delete(self, artifact_id: str, tenant_id: int) -> bool:
        """Delete an artifact (for testing/cleanup)."""
        raise NotImplementedError


class AzureBlobArtifactStore(ArtifactStore):
    """
    Azure Blob Storage artifact store.

    Container structure:
    - solvereign-artifacts/
      - tenant-{tenant_id}/
        - site-{site_id}/
          - evidence_pack/
          - solver_result/
          - audit_report/

    Lifecycle Policy (configured in Azure):
    - Hot → Cool after 30 days
    - Cool → Archive after 90 days
    - Delete archived blobs after 365 days (optional)
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        container_name: str = "solvereign-artifacts",
        account_url: Optional[str] = None,
    ):
        self.container_name = container_name
        self._connection_string = connection_string or os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        self._account_url = account_url or os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
        self._client = None
        self._container_client = None

    async def _get_container_client(self):
        """Lazy initialization of Azure Blob client."""
        if self._container_client is None:
            try:
                from azure.storage.blob.aio import BlobServiceClient
                from azure.identity.aio import DefaultAzureCredential

                if self._connection_string:
                    # Connection string auth (development)
                    service_client = BlobServiceClient.from_connection_string(self._connection_string)
                elif self._account_url:
                    # Managed Identity auth (production)
                    credential = DefaultAzureCredential()
                    service_client = BlobServiceClient(self._account_url, credential=credential)
                else:
                    raise ValueError("No Azure Storage credentials configured")

                self._client = service_client
                self._container_client = service_client.get_container_client(self.container_name)

                # Ensure container exists
                try:
                    await self._container_client.create_container()
                    logger.info(f"Created container: {self.container_name}")
                except Exception:
                    pass  # Container already exists

            except ImportError:
                raise ImportError(
                    "Azure Blob Storage SDK not installed. "
                    "Run: pip install azure-storage-blob azure-identity"
                )

        return self._container_client

    def _build_blob_path(
        self,
        tenant_id: int,
        site_id: int,
        artifact_type: str,
        artifact_id: str,
        filename: Optional[str] = None,
    ) -> str:
        """Build hierarchical blob path for tenant isolation."""
        base_path = f"tenant-{tenant_id}/site-{site_id}/{artifact_type}"
        if filename:
            return f"{base_path}/{artifact_id}/{filename}"
        return f"{base_path}/{artifact_id}.json"

    async def store(
        self,
        tenant_id: int,
        site_id: int,
        artifact_type: str,
        content: Union[bytes, BinaryIO, Dict],
        run_id: Optional[str] = None,
        plan_version_id: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> ArtifactMetadata:
        """Store an artifact in Azure Blob Storage."""
        container = await self._get_container_client()

        # Generate artifact ID
        artifact_id = self._generate_artifact_id(tenant_id, site_id, artifact_type)

        # Serialize content if dict
        if isinstance(content, dict):
            content = json.dumps(content, default=str, indent=2).encode("utf-8")
        elif hasattr(content, "read"):
            content = content.read()

        # Compute hash
        content_hash = hashlib.sha256(content).hexdigest()[:16]

        # Build blob path
        blob_path = self._build_blob_path(tenant_id, site_id, artifact_type, artifact_id, filename)

        # Upload with metadata
        blob_client = container.get_blob_client(blob_path)

        metadata = {
            "tenant_id": str(tenant_id),
            "site_id": str(site_id),
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "content_hash": content_hash,
            "run_id": run_id or "",
            "plan_version_id": str(plan_version_id) if plan_version_id else "",
            "created_at": datetime.utcnow().isoformat(),
        }

        await blob_client.upload_blob(
            content,
            overwrite=True,
            metadata=metadata,
            standard_blob_tier="Hot",  # Start in Hot tier
        )

        logger.info(
            "artifact_stored",
            extra={
                "artifact_id": artifact_id,
                "tenant_id": tenant_id,
                "blob_path": blob_path,
                "size_bytes": len(content),
            }
        )

        return ArtifactMetadata(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            site_id=site_id,
            artifact_type=artifact_type,
            run_id=run_id,
            plan_version_id=plan_version_id,
            blob_path=blob_path,
            content_hash=content_hash,
            size_bytes=len(content),
            created_at=datetime.utcnow(),
            tier="Hot",
        )

    async def get(self, artifact_id: str, tenant_id: int) -> Optional[bytes]:
        """Retrieve artifact content."""
        metadata = await self.get_metadata(artifact_id, tenant_id)
        if not metadata:
            return None

        container = await self._get_container_client()
        blob_client = container.get_blob_client(metadata.blob_path)

        try:
            download = await blob_client.download_blob()
            return await download.readall()
        except Exception as e:
            logger.error(f"Failed to download artifact {artifact_id}: {e}")
            return None

    async def get_metadata(self, artifact_id: str, tenant_id: int) -> Optional[ArtifactMetadata]:
        """Get artifact metadata without content."""
        container = await self._get_container_client()

        # Search for blob with matching artifact_id in tenant's namespace
        prefix = f"tenant-{tenant_id}/"

        async for blob in container.list_blobs(name_starts_with=prefix, include=["metadata"]):
            if blob.metadata and blob.metadata.get("artifact_id") == artifact_id:
                # Verify tenant match
                if blob.metadata.get("tenant_id") != str(tenant_id):
                    logger.warning(f"Tenant mismatch for artifact {artifact_id}")
                    return None

                return ArtifactMetadata(
                    artifact_id=artifact_id,
                    tenant_id=tenant_id,
                    site_id=int(blob.metadata.get("site_id", 0)),
                    artifact_type=blob.metadata.get("artifact_type", "unknown"),
                    run_id=blob.metadata.get("run_id") or None,
                    plan_version_id=int(blob.metadata["plan_version_id"]) if blob.metadata.get("plan_version_id") else None,
                    blob_path=blob.name,
                    content_hash=blob.metadata.get("content_hash", ""),
                    size_bytes=blob.size,
                    created_at=blob.creation_time or datetime.utcnow(),
                    tier=blob.blob_tier or "Hot",
                )

        return None

    async def get_download_url(self, artifact_id: str, tenant_id: int, expires_in: int = 3600) -> Optional[str]:
        """
        Generate a SAS URL for secure download.

        Uses User Delegation SAS when using Managed Identity (production).
        Falls back to Account Key SAS when using connection string (pilot/dev).
        """
        metadata = await self.get_metadata(artifact_id, tenant_id)
        if not metadata:
            return None

        try:
            from azure.storage.blob import generate_blob_sas, BlobSasPermissions

            container = await self._get_container_client()
            blob_client = container.get_blob_client(metadata.blob_path)

            # Determine SAS method
            account_key = self._get_account_key()

            if account_key:
                # Pilot mode: Account Key SAS (simpler but key management needed)
                sas_token = generate_blob_sas(
                    account_name=blob_client.account_name,
                    container_name=self.container_name,
                    blob_name=metadata.blob_path,
                    account_key=account_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.utcnow() + timedelta(seconds=expires_in),
                )
                logger.debug(f"Generated Account Key SAS for {artifact_id}")
            else:
                # Production mode: User Delegation SAS (no stored secrets)
                sas_token = await self._generate_user_delegation_sas(
                    blob_client, metadata.blob_path, expires_in
                )
                logger.debug(f"Generated User Delegation SAS for {artifact_id}")

            return f"{blob_client.url}?{sas_token}"

        except Exception as e:
            logger.error(f"Failed to generate SAS URL for {artifact_id}: {e}")
            return None

    async def _generate_user_delegation_sas(
        self,
        blob_client,
        blob_name: str,
        expires_in: int
    ) -> str:
        """
        Generate User Delegation SAS (production mode).

        Requires: Storage Blob Delegator role on the storage account.
        This method uses Managed Identity - no secrets stored.
        """
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions

        # Get user delegation key (valid for up to 7 days)
        delegation_key_start = datetime.utcnow()
        delegation_key_expiry = datetime.utcnow() + timedelta(days=1)

        # Request user delegation key from Azure
        user_delegation_key = await self._client.get_user_delegation_key(
            key_start_time=delegation_key_start,
            key_expiry_time=delegation_key_expiry,
        )

        # Generate SAS using delegation key
        sas_token = generate_blob_sas(
            account_name=blob_client.account_name,
            container_name=self.container_name,
            blob_name=blob_name,
            user_delegation_key=user_delegation_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(seconds=expires_in),
        )

        return sas_token

    def _get_account_key(self) -> Optional[str]:
        """Extract account key from connection string (for SAS generation)."""
        if not self._connection_string:
            return None
        parts = dict(p.split("=", 1) for p in self._connection_string.split(";") if "=" in p)
        return parts.get("AccountKey")

    def get_auth_mode(self) -> str:
        """Return current authentication mode for documentation."""
        if self._connection_string:
            return "connection_string"
        elif self._account_url:
            return "managed_identity"
        else:
            return "not_configured"

    async def delete(self, artifact_id: str, tenant_id: int) -> bool:
        """Delete an artifact."""
        metadata = await self.get_metadata(artifact_id, tenant_id)
        if not metadata:
            return False

        container = await self._get_container_client()
        blob_client = container.get_blob_client(metadata.blob_path)

        try:
            await blob_client.delete_blob()
            logger.info(f"Deleted artifact {artifact_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete artifact {artifact_id}: {e}")
            return False

    def _generate_artifact_id(self, tenant_id: int, site_id: int, artifact_type: str) -> str:
        """Generate unique artifact ID."""
        import uuid
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        unique = str(uuid.uuid4())[:8]
        return f"{artifact_type}-{tenant_id}-{site_id}-{timestamp}-{unique}"

    async def close(self):
        """Close Azure client connections."""
        if self._client:
            await self._client.close()


class LocalFileArtifactStore(ArtifactStore):
    """
    Local filesystem artifact store for development.

    Structure mirrors Azure:
    - artifacts/
      - tenant-{tenant_id}/
        - site-{site_id}/
          - evidence_pack/
          - solver_result/
    """

    def __init__(self, base_path: str = "artifacts"):
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    def _build_path(
        self,
        tenant_id: int,
        site_id: int,
        artifact_type: str,
        artifact_id: str,
    ) -> str:
        """Build local file path."""
        dir_path = os.path.join(
            self.base_path,
            f"tenant-{tenant_id}",
            f"site-{site_id}",
            artifact_type,
        )
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, f"{artifact_id}.json")

    async def store(
        self,
        tenant_id: int,
        site_id: int,
        artifact_type: str,
        content: Union[bytes, BinaryIO, Dict],
        run_id: Optional[str] = None,
        plan_version_id: Optional[int] = None,
        filename: Optional[str] = None,
    ) -> ArtifactMetadata:
        """Store artifact locally."""
        import uuid

        artifact_id = f"{artifact_type}-{tenant_id}-{site_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}"

        # Serialize content if dict
        if isinstance(content, dict):
            content = json.dumps(content, default=str, indent=2).encode("utf-8")
        elif hasattr(content, "read"):
            content = content.read()

        content_hash = hashlib.sha256(content).hexdigest()[:16]
        file_path = self._build_path(tenant_id, site_id, artifact_type, artifact_id)

        # Write content
        with open(file_path, "wb") as f:
            f.write(content)

        # Write metadata
        metadata_path = file_path.replace(".json", ".meta.json")
        meta = {
            "artifact_id": artifact_id,
            "tenant_id": tenant_id,
            "site_id": site_id,
            "artifact_type": artifact_type,
            "run_id": run_id,
            "plan_version_id": plan_version_id,
            "content_hash": content_hash,
            "size_bytes": len(content),
            "created_at": datetime.utcnow().isoformat(),
        }
        with open(metadata_path, "w") as f:
            json.dump(meta, f, indent=2)

        return ArtifactMetadata(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            site_id=site_id,
            artifact_type=artifact_type,
            run_id=run_id,
            plan_version_id=plan_version_id,
            blob_path=file_path,
            content_hash=content_hash,
            size_bytes=len(content),
            created_at=datetime.utcnow(),
            tier="Local",
        )

    async def get(self, artifact_id: str, tenant_id: int) -> Optional[bytes]:
        """Retrieve artifact content."""
        metadata = await self.get_metadata(artifact_id, tenant_id)
        if not metadata:
            return None

        try:
            with open(metadata.blob_path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    async def get_metadata(self, artifact_id: str, tenant_id: int) -> Optional[ArtifactMetadata]:
        """Get artifact metadata."""
        # Search tenant directory
        tenant_dir = os.path.join(self.base_path, f"tenant-{tenant_id}")
        if not os.path.exists(tenant_dir):
            return None

        for root, dirs, files in os.walk(tenant_dir):
            for file in files:
                if file.endswith(".meta.json") and artifact_id in file:
                    meta_path = os.path.join(root, file)
                    with open(meta_path) as f:
                        meta = json.load(f)

                    if meta.get("tenant_id") != tenant_id:
                        return None

                    return ArtifactMetadata(
                        artifact_id=meta["artifact_id"],
                        tenant_id=meta["tenant_id"],
                        site_id=meta["site_id"],
                        artifact_type=meta["artifact_type"],
                        run_id=meta.get("run_id"),
                        plan_version_id=meta.get("plan_version_id"),
                        blob_path=meta_path.replace(".meta.json", ".json"),
                        content_hash=meta["content_hash"],
                        size_bytes=meta["size_bytes"],
                        created_at=datetime.fromisoformat(meta["created_at"]),
                        tier="Local",
                    )

        return None

    async def get_download_url(self, artifact_id: str, tenant_id: int, expires_in: int = 3600) -> Optional[str]:
        """Local files don't have download URLs - return file path."""
        metadata = await self.get_metadata(artifact_id, tenant_id)
        if metadata:
            return f"file://{metadata.blob_path}"
        return None

    async def delete(self, artifact_id: str, tenant_id: int) -> bool:
        """Delete artifact and metadata."""
        metadata = await self.get_metadata(artifact_id, tenant_id)
        if not metadata:
            return False

        try:
            os.remove(metadata.blob_path)
            os.remove(metadata.blob_path.replace(".json", ".meta.json"))
            return True
        except FileNotFoundError:
            return False


# =============================================================================
# FACTORY
# =============================================================================

def get_artifact_store() -> ArtifactStore:
    """
    Get appropriate artifact store based on environment.

    Production: AzureBlobArtifactStore (requires AZURE_STORAGE_* env vars)
    Development: LocalFileArtifactStore
    """
    if os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or os.environ.get("AZURE_STORAGE_ACCOUNT_URL"):
        return AzureBlobArtifactStore()
    else:
        logger.warning("Using LocalFileArtifactStore (development mode)")
        return LocalFileArtifactStore()


# =============================================================================
# AZURE LIFECYCLE POLICY (for reference - apply via Azure Portal/CLI)
# =============================================================================

LIFECYCLE_POLICY_JSON = """
{
  "rules": [
    {
      "enabled": true,
      "name": "solvereign-lifecycle",
      "type": "Lifecycle",
      "definition": {
        "actions": {
          "baseBlob": {
            "tierToCool": {
              "daysAfterModificationGreaterThan": 30
            },
            "tierToArchive": {
              "daysAfterModificationGreaterThan": 90
            },
            "delete": {
              "daysAfterModificationGreaterThan": 365
            }
          }
        },
        "filters": {
          "blobTypes": ["blockBlob"],
          "prefixMatch": ["tenant-"]
        }
      }
    }
  ]
}
"""
