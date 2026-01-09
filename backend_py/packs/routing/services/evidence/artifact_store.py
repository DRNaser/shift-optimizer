# =============================================================================
# SOLVEREIGN Routing Pack - Gate 5: Artifact Store
# =============================================================================
# Abstract interface for storing evidence packs with cloud support.
#
# Gate 5 Requirements:
# - Evidence Pack darf nicht "nur lokal exportieren"
# - Artifact-Store Pfad muss: S3, Azure Blob, MinIO (oder abstraktes Interface)
# - Evidence muss Hash haben (hash_of_evidence_pack)
# - Audit kann prüfen: "Hash stimmt überein, keine Manipulation"
# =============================================================================

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, BinaryIO, Union

logger = logging.getLogger(__name__)


# =============================================================================
# ARTIFACT METADATA
# =============================================================================

@dataclass
class ArtifactMetadata:
    """
    Metadata for a stored artifact.

    Includes hash for integrity verification at retrieval time.
    """
    artifact_id: str                # Unique artifact identifier
    plan_id: str                    # Plan this evidence belongs to
    tenant_id: int                  # Tenant ID
    content_hash: str               # SHA256 hash of content for integrity
    content_size_bytes: int         # Size in bytes
    content_type: str               # MIME type (application/zip, application/json)
    storage_path: str               # Full path in storage
    created_at: str                 # ISO timestamp
    created_by: Optional[str]       # User who created

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactMetadata":
        return cls(**data)


@dataclass
class UploadResult:
    """Result of an artifact upload operation."""
    success: bool
    artifact_id: str
    storage_path: str
    content_hash: str
    content_size_bytes: int
    url: Optional[str] = None       # Pre-signed URL (if supported)
    error_message: Optional[str] = None


@dataclass
class DownloadResult:
    """Result of an artifact download operation."""
    success: bool
    artifact_id: str
    content: Optional[bytes] = None
    metadata: Optional[ArtifactMetadata] = None
    error_message: Optional[str] = None
    integrity_verified: bool = False


@dataclass
class IntegrityCheckResult:
    """Result of integrity verification."""
    artifact_id: str
    expected_hash: str
    actual_hash: str
    matches: bool
    checked_at: str


# =============================================================================
# ABSTRACT ARTIFACT STORE
# =============================================================================

class ArtifactStore(ABC):
    """
    Abstract base class for artifact storage.

    Implementations:
    - LocalArtifactStore: File system storage (dev/test)
    - S3ArtifactStore: AWS S3 / MinIO storage
    - AzureBlobArtifactStore: Azure Blob Storage

    Gate 5 Requirements:
    - Every upload includes content hash
    - Every download verifies integrity
    - Metadata stored alongside content
    """

    @abstractmethod
    def upload(
        self,
        artifact_id: str,
        content: Union[bytes, BinaryIO],
        plan_id: str,
        tenant_id: int,
        content_type: str = "application/zip",
        created_by: Optional[str] = None,
    ) -> UploadResult:
        """
        Upload an artifact to storage.

        Args:
            artifact_id: Unique identifier for the artifact
            content: Artifact content (bytes or file-like object)
            plan_id: Associated plan ID
            tenant_id: Tenant ID
            content_type: MIME type
            created_by: User who created the artifact

        Returns:
            UploadResult with success status and hash
        """
        pass

    @abstractmethod
    def download(
        self,
        artifact_id: str,
        verify_integrity: bool = True,
    ) -> DownloadResult:
        """
        Download an artifact from storage.

        Args:
            artifact_id: Artifact identifier
            verify_integrity: If True, verify content hash matches

        Returns:
            DownloadResult with content and verification status
        """
        pass

    @abstractmethod
    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """
        Get artifact metadata without downloading content.

        Args:
            artifact_id: Artifact identifier

        Returns:
            ArtifactMetadata or None if not found
        """
        pass

    @abstractmethod
    def verify_integrity(self, artifact_id: str) -> IntegrityCheckResult:
        """
        Verify artifact integrity without downloading.

        Computes hash of stored content and compares with stored hash.

        Args:
            artifact_id: Artifact identifier

        Returns:
            IntegrityCheckResult
        """
        pass

    @abstractmethod
    def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists."""
        pass

    @abstractmethod
    def delete(self, artifact_id: str) -> bool:
        """Delete artifact and metadata."""
        pass

    @abstractmethod
    def get_url(
        self,
        artifact_id: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """
        Get pre-signed URL for artifact (if supported).

        Args:
            artifact_id: Artifact identifier
            expires_in_seconds: URL expiration time

        Returns:
            Pre-signed URL or None if not supported
        """
        pass

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    @staticmethod
    def compute_hash(content: Union[bytes, BinaryIO]) -> str:
        """Compute SHA256 hash of content."""
        if isinstance(content, bytes):
            return hashlib.sha256(content).hexdigest()
        else:
            # File-like object
            hasher = hashlib.sha256()
            content.seek(0)
            for chunk in iter(lambda: content.read(8192), b""):
                hasher.update(chunk)
            content.seek(0)
            return hasher.hexdigest()

    @staticmethod
    def generate_artifact_path(
        tenant_id: int,
        plan_id: str,
        artifact_id: str,
    ) -> str:
        """
        Generate standard storage path.

        Format: tenant_{tenant_id}/plans/{plan_id}/{artifact_id}
        """
        return f"tenant_{tenant_id}/plans/{plan_id}/{artifact_id}"


# =============================================================================
# LOCAL ARTIFACT STORE (Dev/Test)
# =============================================================================

class LocalArtifactStore(ArtifactStore):
    """
    Local file system artifact store.

    For development and testing. Not for production.
    """

    def __init__(self, base_path: Union[str, Path]):
        """
        Initialize local artifact store.

        Args:
            base_path: Base directory for artifact storage
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_artifact_dir(self, artifact_id: str) -> Path:
        """Get directory for an artifact."""
        return self.base_path / artifact_id

    def _get_content_path(self, artifact_id: str) -> Path:
        """Get path to artifact content file."""
        return self._get_artifact_dir(artifact_id) / "content"

    def _get_metadata_path(self, artifact_id: str) -> Path:
        """Get path to artifact metadata file."""
        return self._get_artifact_dir(artifact_id) / "metadata.json"

    def upload(
        self,
        artifact_id: str,
        content: Union[bytes, BinaryIO],
        plan_id: str,
        tenant_id: int,
        content_type: str = "application/zip",
        created_by: Optional[str] = None,
    ) -> UploadResult:
        """Upload artifact to local file system."""
        try:
            # Convert to bytes if needed
            if hasattr(content, 'read'):
                content_bytes = content.read()
            else:
                content_bytes = content

            # Compute hash
            content_hash = self.compute_hash(content_bytes)
            content_size = len(content_bytes)

            # Create directory
            artifact_dir = self._get_artifact_dir(artifact_id)
            artifact_dir.mkdir(parents=True, exist_ok=True)

            # Write content
            content_path = self._get_content_path(artifact_id)
            content_path.write_bytes(content_bytes)

            # Create metadata
            storage_path = self.generate_artifact_path(tenant_id, plan_id, artifact_id)
            metadata = ArtifactMetadata(
                artifact_id=artifact_id,
                plan_id=plan_id,
                tenant_id=tenant_id,
                content_hash=content_hash,
                content_size_bytes=content_size,
                content_type=content_type,
                storage_path=storage_path,
                created_at=datetime.now().isoformat(),
                created_by=created_by,
            )

            # Write metadata
            metadata_path = self._get_metadata_path(artifact_id)
            metadata_path.write_text(metadata.to_json())

            logger.info(f"Uploaded artifact {artifact_id} to local storage")

            return UploadResult(
                success=True,
                artifact_id=artifact_id,
                storage_path=storage_path,
                content_hash=content_hash,
                content_size_bytes=content_size,
                url=str(content_path),
            )

        except Exception as e:
            logger.error(f"Failed to upload artifact {artifact_id}: {e}")
            return UploadResult(
                success=False,
                artifact_id=artifact_id,
                storage_path="",
                content_hash="",
                content_size_bytes=0,
                error_message=str(e),
            )

    def download(
        self,
        artifact_id: str,
        verify_integrity: bool = True,
    ) -> DownloadResult:
        """Download artifact from local file system."""
        try:
            # Read content
            content_path = self._get_content_path(artifact_id)
            if not content_path.exists():
                return DownloadResult(
                    success=False,
                    artifact_id=artifact_id,
                    error_message="Artifact not found",
                )

            content = content_path.read_bytes()

            # Get metadata
            metadata = self.get_metadata(artifact_id)

            # Verify integrity if requested
            integrity_verified = False
            if verify_integrity and metadata:
                actual_hash = self.compute_hash(content)
                integrity_verified = (actual_hash == metadata.content_hash)
                if not integrity_verified:
                    logger.warning(
                        f"Integrity check failed for artifact {artifact_id}: "
                        f"expected {metadata.content_hash}, got {actual_hash}"
                    )

            return DownloadResult(
                success=True,
                artifact_id=artifact_id,
                content=content,
                metadata=metadata,
                integrity_verified=integrity_verified,
            )

        except Exception as e:
            logger.error(f"Failed to download artifact {artifact_id}: {e}")
            return DownloadResult(
                success=False,
                artifact_id=artifact_id,
                error_message=str(e),
            )

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """Get artifact metadata."""
        try:
            metadata_path = self._get_metadata_path(artifact_id)
            if not metadata_path.exists():
                return None

            data = json.loads(metadata_path.read_text())
            return ArtifactMetadata.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to get metadata for {artifact_id}: {e}")
            return None

    def verify_integrity(self, artifact_id: str) -> IntegrityCheckResult:
        """Verify artifact integrity."""
        metadata = self.get_metadata(artifact_id)
        if not metadata:
            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash="",
                actual_hash="",
                matches=False,
                checked_at=datetime.now().isoformat(),
            )

        content_path = self._get_content_path(artifact_id)
        if not content_path.exists():
            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash=metadata.content_hash,
                actual_hash="",
                matches=False,
                checked_at=datetime.now().isoformat(),
            )

        actual_hash = self.compute_hash(content_path.read_bytes())

        return IntegrityCheckResult(
            artifact_id=artifact_id,
            expected_hash=metadata.content_hash,
            actual_hash=actual_hash,
            matches=(actual_hash == metadata.content_hash),
            checked_at=datetime.now().isoformat(),
        )

    def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists."""
        return self._get_content_path(artifact_id).exists()

    def delete(self, artifact_id: str) -> bool:
        """Delete artifact and metadata."""
        try:
            artifact_dir = self._get_artifact_dir(artifact_id)
            if artifact_dir.exists():
                import shutil
                shutil.rmtree(artifact_dir)
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete artifact {artifact_id}: {e}")
            return False

    def get_url(
        self,
        artifact_id: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """Get file path as URL (local storage doesn't support pre-signed URLs)."""
        content_path = self._get_content_path(artifact_id)
        if content_path.exists():
            return f"file://{content_path.absolute()}"
        return None


# =============================================================================
# S3 ARTIFACT STORE (Production - S3 / MinIO)
# =============================================================================

class S3ArtifactStore(ArtifactStore):
    """
    S3-compatible artifact store.

    Works with AWS S3, MinIO, and other S3-compatible services.

    Requires boto3 for AWS SDK functionality.
    """

    def __init__(
        self,
        bucket_name: str,
        endpoint_url: Optional[str] = None,  # For MinIO/custom S3
        region_name: str = "eu-central-1",
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
    ):
        """
        Initialize S3 artifact store.

        Args:
            bucket_name: S3 bucket name
            endpoint_url: Custom endpoint (for MinIO)
            region_name: AWS region
            access_key_id: AWS access key (or from env)
            secret_access_key: AWS secret key (or from env)
        """
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url
        self.region_name = region_name

        # Lazy import boto3
        try:
            import boto3
            from botocore.config import Config

            config = Config(signature_version='s3v4')

            self.s3 = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                region_name=region_name,
                aws_access_key_id=access_key_id or os.environ.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=secret_access_key or os.environ.get('AWS_SECRET_ACCESS_KEY'),
                config=config,
            )
            self._boto3_available = True
        except ImportError:
            logger.warning("boto3 not available - S3ArtifactStore will not work")
            self.s3 = None
            self._boto3_available = False

    def _get_content_key(self, artifact_id: str) -> str:
        """Get S3 key for content."""
        return f"artifacts/{artifact_id}/content"

    def _get_metadata_key(self, artifact_id: str) -> str:
        """Get S3 key for metadata."""
        return f"artifacts/{artifact_id}/metadata.json"

    def upload(
        self,
        artifact_id: str,
        content: Union[bytes, BinaryIO],
        plan_id: str,
        tenant_id: int,
        content_type: str = "application/zip",
        created_by: Optional[str] = None,
    ) -> UploadResult:
        """Upload artifact to S3."""
        if not self._boto3_available:
            return UploadResult(
                success=False,
                artifact_id=artifact_id,
                storage_path="",
                content_hash="",
                content_size_bytes=0,
                error_message="boto3 not available",
            )

        try:
            # Convert to bytes if needed
            if hasattr(content, 'read'):
                content_bytes = content.read()
            else:
                content_bytes = content

            # Compute hash
            content_hash = self.compute_hash(content_bytes)
            content_size = len(content_bytes)

            # Upload content
            content_key = self._get_content_key(artifact_id)
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=content_key,
                Body=content_bytes,
                ContentType=content_type,
                Metadata={
                    'plan_id': plan_id,
                    'tenant_id': str(tenant_id),
                    'content_hash': content_hash,
                },
            )

            # Create and upload metadata
            storage_path = f"s3://{self.bucket_name}/{content_key}"
            metadata = ArtifactMetadata(
                artifact_id=artifact_id,
                plan_id=plan_id,
                tenant_id=tenant_id,
                content_hash=content_hash,
                content_size_bytes=content_size,
                content_type=content_type,
                storage_path=storage_path,
                created_at=datetime.now().isoformat(),
                created_by=created_by,
            )

            metadata_key = self._get_metadata_key(artifact_id)
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=metadata_key,
                Body=metadata.to_json(),
                ContentType="application/json",
            )

            logger.info(f"Uploaded artifact {artifact_id} to S3 bucket {self.bucket_name}")

            return UploadResult(
                success=True,
                artifact_id=artifact_id,
                storage_path=storage_path,
                content_hash=content_hash,
                content_size_bytes=content_size,
            )

        except Exception as e:
            logger.error(f"Failed to upload artifact {artifact_id} to S3: {e}")
            return UploadResult(
                success=False,
                artifact_id=artifact_id,
                storage_path="",
                content_hash="",
                content_size_bytes=0,
                error_message=str(e),
            )

    def download(
        self,
        artifact_id: str,
        verify_integrity: bool = True,
    ) -> DownloadResult:
        """Download artifact from S3."""
        if not self._boto3_available:
            return DownloadResult(
                success=False,
                artifact_id=artifact_id,
                error_message="boto3 not available",
            )

        try:
            content_key = self._get_content_key(artifact_id)
            response = self.s3.get_object(Bucket=self.bucket_name, Key=content_key)
            content = response['Body'].read()

            metadata = self.get_metadata(artifact_id)

            integrity_verified = False
            if verify_integrity and metadata:
                actual_hash = self.compute_hash(content)
                integrity_verified = (actual_hash == metadata.content_hash)

            return DownloadResult(
                success=True,
                artifact_id=artifact_id,
                content=content,
                metadata=metadata,
                integrity_verified=integrity_verified,
            )

        except Exception as e:
            logger.error(f"Failed to download artifact {artifact_id} from S3: {e}")
            return DownloadResult(
                success=False,
                artifact_id=artifact_id,
                error_message=str(e),
            )

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """Get artifact metadata from S3."""
        if not self._boto3_available:
            return None

        try:
            metadata_key = self._get_metadata_key(artifact_id)
            response = self.s3.get_object(Bucket=self.bucket_name, Key=metadata_key)
            data = json.loads(response['Body'].read().decode('utf-8'))
            return ArtifactMetadata.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to get metadata for {artifact_id}: {e}")
            return None

    def verify_integrity(self, artifact_id: str) -> IntegrityCheckResult:
        """Verify artifact integrity in S3."""
        metadata = self.get_metadata(artifact_id)
        if not metadata:
            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash="",
                actual_hash="",
                matches=False,
                checked_at=datetime.now().isoformat(),
            )

        try:
            content_key = self._get_content_key(artifact_id)
            response = self.s3.get_object(Bucket=self.bucket_name, Key=content_key)
            content = response['Body'].read()
            actual_hash = self.compute_hash(content)

            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash=metadata.content_hash,
                actual_hash=actual_hash,
                matches=(actual_hash == metadata.content_hash),
                checked_at=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.error(f"Failed to verify integrity for {artifact_id}: {e}")
            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash=metadata.content_hash,
                actual_hash="",
                matches=False,
                checked_at=datetime.now().isoformat(),
            )

    def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists in S3."""
        if not self._boto3_available:
            return False

        try:
            content_key = self._get_content_key(artifact_id)
            self.s3.head_object(Bucket=self.bucket_name, Key=content_key)
            return True
        except:
            return False

    def delete(self, artifact_id: str) -> bool:
        """Delete artifact from S3."""
        if not self._boto3_available:
            return False

        try:
            content_key = self._get_content_key(artifact_id)
            metadata_key = self._get_metadata_key(artifact_id)

            self.s3.delete_object(Bucket=self.bucket_name, Key=content_key)
            self.s3.delete_object(Bucket=self.bucket_name, Key=metadata_key)
            return True
        except Exception as e:
            logger.error(f"Failed to delete artifact {artifact_id}: {e}")
            return False

    def get_url(
        self,
        artifact_id: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """Get pre-signed URL for artifact."""
        if not self._boto3_available:
            return None

        try:
            content_key = self._get_content_key(artifact_id)
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': content_key},
                ExpiresIn=expires_in_seconds,
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {artifact_id}: {e}")
            return None


# =============================================================================
# AZURE BLOB ARTIFACT STORE (Production)
# =============================================================================

class AzureBlobArtifactStore(ArtifactStore):
    """
    Azure Blob Storage artifact store.

    Requires azure-storage-blob for Azure SDK functionality.
    """

    def __init__(
        self,
        container_name: str,
        connection_string: Optional[str] = None,
        account_name: Optional[str] = None,
        account_key: Optional[str] = None,
    ):
        """
        Initialize Azure Blob artifact store.

        Args:
            container_name: Azure container name
            connection_string: Azure connection string (or from env)
            account_name: Storage account name
            account_key: Storage account key
        """
        self.container_name = container_name

        try:
            from azure.storage.blob import BlobServiceClient

            if connection_string:
                self.blob_service = BlobServiceClient.from_connection_string(connection_string)
            else:
                conn_str = os.environ.get('AZURE_STORAGE_CONNECTION_STRING')
                if conn_str:
                    self.blob_service = BlobServiceClient.from_connection_string(conn_str)
                else:
                    self.blob_service = BlobServiceClient(
                        account_url=f"https://{account_name}.blob.core.windows.net",
                        credential=account_key,
                    )
            self.container_client = self.blob_service.get_container_client(container_name)
            self._azure_available = True
        except ImportError:
            logger.warning("azure-storage-blob not available - AzureBlobArtifactStore will not work")
            self.blob_service = None
            self.container_client = None
            self._azure_available = False

    def _get_content_blob_name(self, artifact_id: str) -> str:
        return f"artifacts/{artifact_id}/content"

    def _get_metadata_blob_name(self, artifact_id: str) -> str:
        return f"artifacts/{artifact_id}/metadata.json"

    def upload(
        self,
        artifact_id: str,
        content: Union[bytes, BinaryIO],
        plan_id: str,
        tenant_id: int,
        content_type: str = "application/zip",
        created_by: Optional[str] = None,
    ) -> UploadResult:
        """Upload artifact to Azure Blob Storage."""
        if not self._azure_available:
            return UploadResult(
                success=False,
                artifact_id=artifact_id,
                storage_path="",
                content_hash="",
                content_size_bytes=0,
                error_message="azure-storage-blob not available",
            )

        try:
            if hasattr(content, 'read'):
                content_bytes = content.read()
            else:
                content_bytes = content

            content_hash = self.compute_hash(content_bytes)
            content_size = len(content_bytes)

            # Upload content
            content_blob = self._get_content_blob_name(artifact_id)
            blob_client = self.container_client.get_blob_client(content_blob)
            blob_client.upload_blob(content_bytes, overwrite=True, content_type=content_type)

            # Create and upload metadata
            storage_path = f"azure://{self.container_name}/{content_blob}"
            metadata = ArtifactMetadata(
                artifact_id=artifact_id,
                plan_id=plan_id,
                tenant_id=tenant_id,
                content_hash=content_hash,
                content_size_bytes=content_size,
                content_type=content_type,
                storage_path=storage_path,
                created_at=datetime.now().isoformat(),
                created_by=created_by,
            )

            metadata_blob = self._get_metadata_blob_name(artifact_id)
            metadata_client = self.container_client.get_blob_client(metadata_blob)
            metadata_client.upload_blob(metadata.to_json(), overwrite=True, content_type="application/json")

            logger.info(f"Uploaded artifact {artifact_id} to Azure container {self.container_name}")

            return UploadResult(
                success=True,
                artifact_id=artifact_id,
                storage_path=storage_path,
                content_hash=content_hash,
                content_size_bytes=content_size,
            )

        except Exception as e:
            logger.error(f"Failed to upload artifact {artifact_id} to Azure: {e}")
            return UploadResult(
                success=False,
                artifact_id=artifact_id,
                storage_path="",
                content_hash="",
                content_size_bytes=0,
                error_message=str(e),
            )

    def download(
        self,
        artifact_id: str,
        verify_integrity: bool = True,
    ) -> DownloadResult:
        """Download artifact from Azure Blob Storage."""
        if not self._azure_available:
            return DownloadResult(
                success=False,
                artifact_id=artifact_id,
                error_message="azure-storage-blob not available",
            )

        try:
            content_blob = self._get_content_blob_name(artifact_id)
            blob_client = self.container_client.get_blob_client(content_blob)
            content = blob_client.download_blob().readall()

            metadata = self.get_metadata(artifact_id)

            integrity_verified = False
            if verify_integrity and metadata:
                actual_hash = self.compute_hash(content)
                integrity_verified = (actual_hash == metadata.content_hash)

            return DownloadResult(
                success=True,
                artifact_id=artifact_id,
                content=content,
                metadata=metadata,
                integrity_verified=integrity_verified,
            )

        except Exception as e:
            logger.error(f"Failed to download artifact {artifact_id} from Azure: {e}")
            return DownloadResult(
                success=False,
                artifact_id=artifact_id,
                error_message=str(e),
            )

    def get_metadata(self, artifact_id: str) -> Optional[ArtifactMetadata]:
        """Get artifact metadata from Azure."""
        if not self._azure_available:
            return None

        try:
            metadata_blob = self._get_metadata_blob_name(artifact_id)
            blob_client = self.container_client.get_blob_client(metadata_blob)
            data = json.loads(blob_client.download_blob().readall().decode('utf-8'))
            return ArtifactMetadata.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to get metadata for {artifact_id}: {e}")
            return None

    def verify_integrity(self, artifact_id: str) -> IntegrityCheckResult:
        """Verify artifact integrity in Azure."""
        metadata = self.get_metadata(artifact_id)
        if not metadata:
            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash="",
                actual_hash="",
                matches=False,
                checked_at=datetime.now().isoformat(),
            )

        try:
            content_blob = self._get_content_blob_name(artifact_id)
            blob_client = self.container_client.get_blob_client(content_blob)
            content = blob_client.download_blob().readall()
            actual_hash = self.compute_hash(content)

            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash=metadata.content_hash,
                actual_hash=actual_hash,
                matches=(actual_hash == metadata.content_hash),
                checked_at=datetime.now().isoformat(),
            )
        except Exception as e:
            logger.error(f"Failed to verify integrity for {artifact_id}: {e}")
            return IntegrityCheckResult(
                artifact_id=artifact_id,
                expected_hash=metadata.content_hash,
                actual_hash="",
                matches=False,
                checked_at=datetime.now().isoformat(),
            )

    def exists(self, artifact_id: str) -> bool:
        """Check if artifact exists in Azure."""
        if not self._azure_available:
            return False

        try:
            content_blob = self._get_content_blob_name(artifact_id)
            blob_client = self.container_client.get_blob_client(content_blob)
            return blob_client.exists()
        except:
            return False

    def delete(self, artifact_id: str) -> bool:
        """Delete artifact from Azure."""
        if not self._azure_available:
            return False

        try:
            content_blob = self._get_content_blob_name(artifact_id)
            metadata_blob = self._get_metadata_blob_name(artifact_id)

            self.container_client.get_blob_client(content_blob).delete_blob()
            self.container_client.get_blob_client(metadata_blob).delete_blob()
            return True
        except Exception as e:
            logger.error(f"Failed to delete artifact {artifact_id}: {e}")
            return False

    def get_url(
        self,
        artifact_id: str,
        expires_in_seconds: int = 3600,
    ) -> Optional[str]:
        """Get SAS URL for artifact."""
        if not self._azure_available:
            return None

        try:
            from azure.storage.blob import generate_blob_sas, BlobSasPermissions
            from datetime import timedelta

            content_blob = self._get_content_blob_name(artifact_id)

            sas_token = generate_blob_sas(
                account_name=self.blob_service.account_name,
                container_name=self.container_name,
                blob_name=content_blob,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(seconds=expires_in_seconds),
            )

            return f"https://{self.blob_service.account_name}.blob.core.windows.net/{self.container_name}/{content_blob}?{sas_token}"
        except Exception as e:
            logger.error(f"Failed to generate SAS URL for {artifact_id}: {e}")
            return None


# =============================================================================
# FACTORY
# =============================================================================

def create_artifact_store(
    store_type: str = "local",
    **kwargs,
) -> ArtifactStore:
    """
    Factory function to create artifact store.

    Args:
        store_type: "local", "s3", "minio", or "azure"
        **kwargs: Store-specific configuration

    Returns:
        Configured ArtifactStore instance
    """
    if store_type == "local":
        return LocalArtifactStore(
            base_path=kwargs.get("base_path", "./artifacts"),
        )
    elif store_type in ("s3", "minio"):
        return S3ArtifactStore(
            bucket_name=kwargs["bucket_name"],
            endpoint_url=kwargs.get("endpoint_url"),
            region_name=kwargs.get("region_name", "eu-central-1"),
            access_key_id=kwargs.get("access_key_id"),
            secret_access_key=kwargs.get("secret_access_key"),
        )
    elif store_type == "azure":
        return AzureBlobArtifactStore(
            container_name=kwargs["container_name"],
            connection_string=kwargs.get("connection_string"),
            account_name=kwargs.get("account_name"),
            account_key=kwargs.get("account_key"),
        )
    else:
        raise ValueError(f"Unknown store type: {store_type}")
