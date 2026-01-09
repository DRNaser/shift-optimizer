# =============================================================================
# SOLVEREIGN Routing Pack - Gate 5: Artifact Store Tests
# =============================================================================
# Gate 5 Requirements:
# - Evidence Pack not "nur lokal exportieren"
# - Artifact-Store: S3, Azure Blob, MinIO (abstract interface)
# - Evidence has hash (hash_of_evidence_pack)
# - Audit can verify: "Hash matches, no manipulation"
# =============================================================================

import sys
import os
import tempfile
import unittest
import json
from pathlib import Path

sys.path.insert(0, ".")

from packs.routing.services.evidence.artifact_store import (
    ArtifactStore,
    LocalArtifactStore,
    S3ArtifactStore,
    AzureBlobArtifactStore,
    ArtifactMetadata,
    UploadResult,
    DownloadResult,
    IntegrityCheckResult,
    create_artifact_store,
)


class TestLocalArtifactStore(unittest.TestCase):
    """Test LocalArtifactStore implementation."""

    def setUp(self):
        """Set up temp directory for tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.store = LocalArtifactStore(base_path=self.temp_dir)

    def tearDown(self):
        """Clean up temp directory."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # UPLOAD TESTS
    # =========================================================================

    def test_upload_success(self):
        """Test successful artifact upload."""
        print("\n" + "=" * 60)
        print("GATE 5: Artifact Upload Success")
        print("=" * 60)

        content = b"Test evidence pack content for routing plan"
        artifact_id = "evidence_plan_001"

        result = self.store.upload(
            artifact_id=artifact_id,
            content=content,
            plan_id="plan_001",
            tenant_id=1,
            content_type="application/zip",
            created_by="test@lts.de",
        )

        print(f"    Artifact ID: {result.artifact_id}")
        print(f"    Storage path: {result.storage_path}")
        print(f"    Content hash: {result.content_hash[:16]}...")
        print(f"    Size: {result.content_size_bytes} bytes")

        self.assertTrue(result.success)
        self.assertEqual(result.artifact_id, artifact_id)
        self.assertGreater(len(result.content_hash), 0)
        self.assertEqual(result.content_size_bytes, len(content))
        print(f"    [PASS] Artifact uploaded successfully")

    def test_upload_with_file_object(self):
        """Test upload with file-like object."""
        print("\n" + "=" * 60)
        print("GATE 5: Upload with File Object")
        print("=" * 60)

        import io
        content = b"File object content"
        file_obj = io.BytesIO(content)

        result = self.store.upload(
            artifact_id="evidence_file_obj",
            content=file_obj,
            plan_id="plan_002",
            tenant_id=1,
        )

        self.assertTrue(result.success)
        print(f"    [PASS] File object upload works")

    # =========================================================================
    # DOWNLOAD TESTS
    # =========================================================================

    def test_download_success(self):
        """Test successful artifact download."""
        print("\n" + "=" * 60)
        print("GATE 5: Artifact Download Success")
        print("=" * 60)

        # Upload first
        content = b"Download test content"
        artifact_id = "evidence_download_test"
        self.store.upload(
            artifact_id=artifact_id,
            content=content,
            plan_id="plan_003",
            tenant_id=1,
        )

        # Download
        result = self.store.download(artifact_id)

        print(f"    Downloaded: {len(result.content)} bytes")
        print(f"    Integrity verified: {result.integrity_verified}")

        self.assertTrue(result.success)
        self.assertEqual(result.content, content)
        self.assertTrue(result.integrity_verified)
        print(f"    [PASS] Artifact downloaded with integrity verification")

    def test_download_not_found(self):
        """Test download of non-existent artifact."""
        print("\n" + "=" * 60)
        print("GATE 5: Download Not Found")
        print("=" * 60)

        result = self.store.download("nonexistent_artifact")

        self.assertFalse(result.success)
        self.assertIn("not found", result.error_message.lower())
        print(f"    [PASS] Not found error handled correctly")

    # =========================================================================
    # INTEGRITY TESTS
    # =========================================================================

    def test_integrity_verification_pass(self):
        """Test that integrity verification passes for unmodified content."""
        print("\n" + "=" * 60)
        print("GATE 5: Integrity Verification (Pass)")
        print("=" * 60)

        content = b"Integrity test content"
        artifact_id = "evidence_integrity"
        self.store.upload(
            artifact_id=artifact_id,
            content=content,
            plan_id="plan_004",
            tenant_id=1,
        )

        result = self.store.verify_integrity(artifact_id)

        print(f"    Expected hash: {result.expected_hash[:16]}...")
        print(f"    Actual hash: {result.actual_hash[:16]}...")
        print(f"    Matches: {result.matches}")

        self.assertTrue(result.matches)
        self.assertEqual(result.expected_hash, result.actual_hash)
        print(f"    [PASS] Integrity verification passed")

    def test_integrity_verification_fail(self):
        """Test that integrity verification fails for modified content."""
        print("\n" + "=" * 60)
        print("GATE 5: Integrity Verification (Fail - Tampered)")
        print("=" * 60)

        content = b"Original content"
        artifact_id = "evidence_tampered"
        self.store.upload(
            artifact_id=artifact_id,
            content=content,
            plan_id="plan_005",
            tenant_id=1,
        )

        # Tamper with the content file
        content_path = self.store._get_content_path(artifact_id)
        content_path.write_bytes(b"Tampered content!")

        result = self.store.verify_integrity(artifact_id)

        print(f"    Expected hash: {result.expected_hash[:16]}...")
        print(f"    Actual hash: {result.actual_hash[:16]}...")
        print(f"    Matches: {result.matches}")

        self.assertFalse(result.matches)
        self.assertNotEqual(result.expected_hash, result.actual_hash)
        print(f"    [PASS] Integrity violation detected")

    # =========================================================================
    # METADATA TESTS
    # =========================================================================

    def test_metadata_stored_correctly(self):
        """Test that metadata is stored and retrieved correctly."""
        print("\n" + "=" * 60)
        print("GATE 5: Metadata Storage")
        print("=" * 60)

        content = b"Metadata test"
        artifact_id = "evidence_metadata"
        plan_id = "plan_006"
        tenant_id = 42
        created_by = "admin@lts.de"

        self.store.upload(
            artifact_id=artifact_id,
            content=content,
            plan_id=plan_id,
            tenant_id=tenant_id,
            content_type="application/json",
            created_by=created_by,
        )

        metadata = self.store.get_metadata(artifact_id)

        print(f"    Artifact ID: {metadata.artifact_id}")
        print(f"    Plan ID: {metadata.plan_id}")
        print(f"    Tenant ID: {metadata.tenant_id}")
        print(f"    Content hash: {metadata.content_hash[:16]}...")
        print(f"    Created by: {metadata.created_by}")

        self.assertEqual(metadata.artifact_id, artifact_id)
        self.assertEqual(metadata.plan_id, plan_id)
        self.assertEqual(metadata.tenant_id, tenant_id)
        self.assertEqual(metadata.content_type, "application/json")
        self.assertEqual(metadata.created_by, created_by)
        print(f"    [PASS] Metadata stored correctly")

    # =========================================================================
    # EXISTS / DELETE TESTS
    # =========================================================================

    def test_exists_check(self):
        """Test artifact existence check."""
        print("\n" + "=" * 60)
        print("GATE 5: Exists Check")
        print("=" * 60)

        artifact_id = "evidence_exists"

        # Before upload
        self.assertFalse(self.store.exists(artifact_id))
        print(f"    Before upload: exists = False")

        # After upload
        self.store.upload(artifact_id=artifact_id, content=b"test", plan_id="p", tenant_id=1)
        self.assertTrue(self.store.exists(artifact_id))
        print(f"    After upload: exists = True")
        print(f"    [PASS] Exists check works")

    def test_delete_artifact(self):
        """Test artifact deletion."""
        print("\n" + "=" * 60)
        print("GATE 5: Delete Artifact")
        print("=" * 60)

        artifact_id = "evidence_delete"
        self.store.upload(artifact_id=artifact_id, content=b"test", plan_id="p", tenant_id=1)

        # Verify exists
        self.assertTrue(self.store.exists(artifact_id))

        # Delete
        deleted = self.store.delete(artifact_id)
        self.assertTrue(deleted)
        self.assertFalse(self.store.exists(artifact_id))
        print(f"    [PASS] Artifact deleted successfully")


class TestArtifactStoreFactory(unittest.TestCase):
    """Test artifact store factory function."""

    def test_create_local_store(self):
        """Test factory creates LocalArtifactStore."""
        print("\n" + "=" * 60)
        print("GATE 5: Factory - Local Store")
        print("=" * 60)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = create_artifact_store(
                store_type="local",
                base_path=temp_dir,
            )

            self.assertIsInstance(store, LocalArtifactStore)
            print(f"    [PASS] Factory creates LocalArtifactStore")

    def test_create_s3_store(self):
        """Test factory creates S3ArtifactStore."""
        print("\n" + "=" * 60)
        print("GATE 5: Factory - S3 Store")
        print("=" * 60)

        store = create_artifact_store(
            store_type="s3",
            bucket_name="test-bucket",
            endpoint_url="http://localhost:9000",  # MinIO
        )

        self.assertIsInstance(store, S3ArtifactStore)
        print(f"    [PASS] Factory creates S3ArtifactStore")

    def test_create_minio_store(self):
        """Test factory creates S3ArtifactStore for MinIO."""
        print("\n" + "=" * 60)
        print("GATE 5: Factory - MinIO Store")
        print("=" * 60)

        store = create_artifact_store(
            store_type="minio",
            bucket_name="test-bucket",
            endpoint_url="http://minio:9000",
        )

        self.assertIsInstance(store, S3ArtifactStore)
        print(f"    [PASS] Factory creates S3ArtifactStore for MinIO")

    def test_create_azure_store(self):
        """Test factory creates AzureBlobArtifactStore."""
        print("\n" + "=" * 60)
        print("GATE 5: Factory - Azure Store")
        print("=" * 60)

        store = create_artifact_store(
            store_type="azure",
            container_name="test-container",
        )

        self.assertIsInstance(store, AzureBlobArtifactStore)
        print(f"    [PASS] Factory creates AzureBlobArtifactStore")

    def test_unknown_store_type_raises(self):
        """Test factory raises for unknown store type."""
        print("\n" + "=" * 60)
        print("GATE 5: Factory - Unknown Type")
        print("=" * 60)

        with self.assertRaises(ValueError):
            create_artifact_store(store_type="unknown")

        print(f"    [PASS] Unknown store type raises ValueError")


class TestHashComputation(unittest.TestCase):
    """Test hash computation for integrity."""

    def test_hash_is_deterministic(self):
        """Test that same content produces same hash."""
        print("\n" + "=" * 60)
        print("GATE 5: Hash Determinism")
        print("=" * 60)

        content = b"Deterministic hash test content"

        hash1 = ArtifactStore.compute_hash(content)
        hash2 = ArtifactStore.compute_hash(content)

        print(f"    Hash 1: {hash1}")
        print(f"    Hash 2: {hash2}")

        self.assertEqual(hash1, hash2)
        print(f"    [PASS] Same content produces same hash")

    def test_different_content_different_hash(self):
        """Test that different content produces different hash."""
        print("\n" + "=" * 60)
        print("GATE 5: Hash Uniqueness")
        print("=" * 60)

        content1 = b"Content version 1"
        content2 = b"Content version 2"

        hash1 = ArtifactStore.compute_hash(content1)
        hash2 = ArtifactStore.compute_hash(content2)

        print(f"    Hash 1: {hash1[:16]}...")
        print(f"    Hash 2: {hash2[:16]}...")

        self.assertNotEqual(hash1, hash2)
        print(f"    [PASS] Different content produces different hash")

    def test_hash_is_sha256(self):
        """Test that hash is valid SHA256 (64 hex chars)."""
        print("\n" + "=" * 60)
        print("GATE 5: Hash Format (SHA256)")
        print("=" * 60)

        content = b"SHA256 format test"
        hash_val = ArtifactStore.compute_hash(content)

        print(f"    Hash: {hash_val}")
        print(f"    Length: {len(hash_val)} chars")

        self.assertEqual(len(hash_val), 64)  # SHA256 = 64 hex chars
        self.assertTrue(all(c in '0123456789abcdef' for c in hash_val))
        print(f"    [PASS] Hash is valid SHA256")


class TestGate5Integration(unittest.TestCase):
    """Gate 5: Full integration test."""

    def test_evidence_pack_workflow(self):
        """
        Integration test: Full evidence pack upload/download/verify workflow.

        This proves the complete Gate 5 requirement:
        1. Upload evidence pack with hash
        2. Download and verify integrity
        3. Detect tampering
        """
        print("\n" + "=" * 70)
        print("GATE 5 INTEGRATION: Evidence Pack Workflow")
        print("=" * 70)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = create_artifact_store(store_type="local", base_path=temp_dir)

            # 1. Create evidence pack content
            evidence_data = {
                "plan_id": "plan_123",
                "tenant_id": 1,
                "routes_count": 10,
                "stops_count": 100,
                "audit_passed": True,
            }
            content = json.dumps(evidence_data, indent=2).encode()

            # 2. Upload
            print("\n[1] Uploading evidence pack...")
            upload_result = store.upload(
                artifact_id="evidence_plan_123_v1",
                content=content,
                plan_id="plan_123",
                tenant_id=1,
                content_type="application/json",
                created_by="dispatcher@lts.de",
            )

            self.assertTrue(upload_result.success)
            print(f"    Uploaded: {upload_result.artifact_id}")
            print(f"    Hash: {upload_result.content_hash}")

            # 3. Download and verify
            print("\n[2] Downloading and verifying...")
            download_result = store.download(
                artifact_id="evidence_plan_123_v1",
                verify_integrity=True,
            )

            self.assertTrue(download_result.success)
            self.assertTrue(download_result.integrity_verified)
            self.assertEqual(download_result.content, content)
            print(f"    Downloaded: {len(download_result.content)} bytes")
            print(f"    Integrity: VERIFIED")

            # 4. Verify metadata
            print("\n[3] Checking metadata...")
            metadata = store.get_metadata("evidence_plan_123_v1")

            self.assertEqual(metadata.plan_id, "plan_123")
            self.assertEqual(metadata.tenant_id, 1)
            self.assertEqual(metadata.created_by, "dispatcher@lts.de")
            print(f"    Plan ID: {metadata.plan_id}")
            print(f"    Created by: {metadata.created_by}")
            print(f"    Stored hash: {metadata.content_hash}")

            # 5. Verify integrity check function
            print("\n[4] Running integrity check...")
            integrity_result = store.verify_integrity("evidence_plan_123_v1")

            self.assertTrue(integrity_result.matches)
            print(f"    Expected: {integrity_result.expected_hash[:16]}...")
            print(f"    Actual: {integrity_result.actual_hash[:16]}...")
            print(f"    Match: {integrity_result.matches}")

            print("\n" + "=" * 70)
            print("GATE 5 PASSED: Evidence Pack workflow complete with integrity")
            print("=" * 70)

    def test_multiple_storage_backends_interface(self):
        """
        Prove that all storage backends implement the same interface.
        """
        print("\n" + "=" * 70)
        print("GATE 5 INTEGRATION: Multiple Storage Backends")
        print("=" * 70)

        backends = [
            ("local", {"base_path": tempfile.mkdtemp()}),
            ("s3", {"bucket_name": "test", "endpoint_url": "http://localhost:9000"}),
            ("azure", {"container_name": "test"}),
        ]

        for backend_name, config in backends:
            store = create_artifact_store(store_type=backend_name, **config)

            # Verify it's an ArtifactStore
            self.assertIsInstance(store, ArtifactStore)

            # Verify it has required methods
            self.assertTrue(hasattr(store, 'upload'))
            self.assertTrue(hasattr(store, 'download'))
            self.assertTrue(hasattr(store, 'verify_integrity'))
            self.assertTrue(hasattr(store, 'get_metadata'))
            self.assertTrue(hasattr(store, 'exists'))
            self.assertTrue(hasattr(store, 'delete'))
            self.assertTrue(hasattr(store, 'get_url'))

            print(f"    [PASS] {backend_name}: Implements ArtifactStore interface")

        print("\n" + "=" * 70)
        print("GATE 5 PASSED: All backends implement abstract interface")
        print("=" * 70)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Gate 5: Artifact Store Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
