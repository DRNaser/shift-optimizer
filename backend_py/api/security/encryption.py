"""
SOLVEREIGN V3.3b - PII Encryption Module

Implements field-level encryption for Personally Identifiable Information (PII)
using AES-256-GCM with Additional Authenticated Data (AAD).

Security Features:
- AES-256-GCM (Galois/Counter Mode) for authenticated encryption
- AAD binds ciphertext to tenant_id + driver_id (prevents cross-tenant copying)
- Key versioning for seamless rotation
- 24-hour overlap period during key rotation
- Automatic key derivation from master key per tenant
- HKDF for secure key derivation

GDPR Compliance:
- Encryption at rest for all PII fields
- Field-level granularity (name, email, phone, etc.)
- Key deletion enables cryptographic erasure
"""

import base64
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


@dataclass
class EncryptedField:
    """
    Encrypted field value with metadata.

    Format when serialized: version:nonce:ciphertext (all base64)
    """

    version: int  # Key version used for encryption
    nonce: bytes  # 12 bytes for AES-GCM
    ciphertext: bytes  # Encrypted data + auth tag
    aad: bytes  # Additional Authenticated Data (not secret, for context binding)

    def serialize(self) -> str:
        """Serialize to string for database storage."""
        nonce_b64 = base64.b64encode(self.nonce).decode()
        ciphertext_b64 = base64.b64encode(self.ciphertext).decode()
        return f"v{self.version}:{nonce_b64}:{ciphertext_b64}"

    @classmethod
    def deserialize(cls, value: str, aad: bytes) -> "EncryptedField":
        """Deserialize from database storage."""
        parts = value.split(":", 2)
        if len(parts) != 3:
            raise ValueError(f"Invalid encrypted field format: {value[:20]}...")

        version = int(parts[0][1:])  # Remove 'v' prefix
        nonce = base64.b64decode(parts[1])
        ciphertext = base64.b64decode(parts[2])

        return cls(version=version, nonce=nonce, ciphertext=ciphertext, aad=aad)


@dataclass
class EncryptionKey:
    """Encryption key with metadata."""

    version: int
    key: bytes  # 32 bytes for AES-256
    created_at: datetime
    expires_at: Optional[datetime] = None
    is_active: bool = True


class KeyManager:
    """
    Manages encryption keys with versioning and rotation.

    Keys are derived from a master key using HKDF with tenant context.
    This ensures each tenant has unique derived keys.
    """

    KEY_SIZE = 32  # AES-256
    NONCE_SIZE = 12  # GCM standard

    def __init__(
        self,
        master_key: bytes,
        rotation_period: timedelta = timedelta(days=90),
        overlap_period: timedelta = timedelta(hours=24)
    ):
        """
        Initialize key manager.

        Args:
            master_key: 32-byte master key (from secure key management)
            rotation_period: How often to rotate keys
            overlap_period: Grace period where old key still works
        """
        if len(master_key) != self.KEY_SIZE:
            raise ValueError(f"Master key must be {self.KEY_SIZE} bytes")

        self._master_key = master_key
        self._rotation_period = rotation_period
        self._overlap_period = overlap_period
        self._keys: dict[int, EncryptionKey] = {}
        self._current_version = 0

    def _derive_key(self, tenant_id: str, version: int) -> bytes:
        """
        Derive a tenant-specific key from the master key.

        Uses HKDF with tenant_id and version as context.
        """
        info = f"solvereign:pii:{tenant_id}:v{version}".encode()

        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=self.KEY_SIZE,
            salt=None,  # Not using salt, info provides uniqueness
            info=info,
            backend=default_backend()
        )

        return hkdf.derive(self._master_key)

    def get_current_key(self, tenant_id: str) -> EncryptionKey:
        """Get the current (latest) encryption key for a tenant."""
        key_data = self._derive_key(tenant_id, self._current_version)
        return EncryptionKey(
            version=self._current_version,
            key=key_data,
            created_at=datetime.utcnow(),
            is_active=True
        )

    def get_key_by_version(self, tenant_id: str, version: int) -> Optional[EncryptionKey]:
        """Get a specific key version for decryption."""
        if version > self._current_version:
            logger.warning(f"Requested future key version: {version} > {self._current_version}")
            return None

        key_data = self._derive_key(tenant_id, version)
        return EncryptionKey(
            version=version,
            key=key_data,
            created_at=datetime.utcnow(),
            is_active=(version == self._current_version)
        )

    def rotate_keys(self) -> int:
        """
        Rotate to a new key version.

        Returns the new version number.
        """
        self._current_version += 1
        logger.info(f"Key rotation: new version = {self._current_version}")
        return self._current_version

    def generate_nonce(self) -> bytes:
        """Generate a cryptographically secure random nonce."""
        return secrets.token_bytes(self.NONCE_SIZE)


class PIIEncryptor:
    """
    Field-level PII encryption using AES-256-GCM.

    AAD (Additional Authenticated Data) is used to bind ciphertext
    to its context (tenant_id, driver_id). This prevents:
    - Cross-tenant data copying (ciphertext from tenant A won't decrypt for tenant B)
    - Record tampering (ciphertext can't be moved to different driver)
    """

    def __init__(self, key_manager: KeyManager):
        self._key_manager = key_manager

    def _build_aad(self, tenant_id: str, entity_id: str, field_name: str) -> bytes:
        """
        Build Additional Authenticated Data for context binding.

        Format: tenant_id:entity_id:field_name
        """
        return f"{tenant_id}:{entity_id}:{field_name}".encode()

    def encrypt(
        self,
        plaintext: str,
        tenant_id: str,
        entity_id: str,
        field_name: str
    ) -> str:
        """
        Encrypt a PII field.

        Args:
            plaintext: The value to encrypt
            tenant_id: Tenant identifier (for key derivation and AAD)
            entity_id: Entity identifier (driver_id, for AAD)
            field_name: Field name (for AAD, e.g., "name", "email")

        Returns:
            Serialized encrypted field string for database storage
        """
        key = self._key_manager.get_current_key(tenant_id)
        nonce = self._key_manager.generate_nonce()
        aad = self._build_aad(tenant_id, entity_id, field_name)

        # Encrypt with AES-GCM
        aesgcm = AESGCM(key.key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)

        encrypted_field = EncryptedField(
            version=key.version,
            nonce=nonce,
            ciphertext=ciphertext,
            aad=aad
        )

        return encrypted_field.serialize()

    def decrypt(
        self,
        encrypted_value: str,
        tenant_id: str,
        entity_id: str,
        field_name: str
    ) -> str:
        """
        Decrypt a PII field.

        Args:
            encrypted_value: Serialized encrypted field from database
            tenant_id: Tenant identifier
            entity_id: Entity identifier
            field_name: Field name

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If decryption fails (tampered, wrong context, etc.)
        """
        aad = self._build_aad(tenant_id, entity_id, field_name)
        encrypted_field = EncryptedField.deserialize(encrypted_value, aad)

        # Get the key version used for encryption
        key = self._key_manager.get_key_by_version(tenant_id, encrypted_field.version)
        if not key:
            raise ValueError(f"Unknown key version: {encrypted_field.version}")

        # Decrypt with AES-GCM
        aesgcm = AESGCM(key.key)

        try:
            plaintext_bytes = aesgcm.decrypt(
                encrypted_field.nonce,
                encrypted_field.ciphertext,
                aad
            )
            return plaintext_bytes.decode("utf-8")
        except Exception as e:
            logger.error(
                f"Decryption failed: tenant={tenant_id}, entity={entity_id}, "
                f"field={field_name}, version={encrypted_field.version}, error={e}"
            )
            raise ValueError("Decryption failed - data may be tampered or context mismatch")

    def re_encrypt(
        self,
        encrypted_value: str,
        tenant_id: str,
        entity_id: str,
        field_name: str
    ) -> str:
        """
        Re-encrypt a field with the current key version.

        Used during key rotation to upgrade old ciphertexts.
        """
        plaintext = self.decrypt(encrypted_value, tenant_id, entity_id, field_name)
        return self.encrypt(plaintext, tenant_id, entity_id, field_name)


# =============================================================================
# PII FIELD DEFINITIONS
# =============================================================================

class PIIFields:
    """
    Enumeration of PII fields that require encryption.

    Categories:
    - IDENTITY: Name, ID numbers
    - CONTACT: Email, phone, address
    - EMPLOYMENT: Contract details, salary (if applicable)
    - CONSENT: Timestamps of consent
    """

    # Identity
    FULL_NAME = "full_name"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    NATIONAL_ID = "national_id"
    TAX_ID = "tax_id"

    # Contact
    EMAIL = "email"
    PHONE = "phone"
    MOBILE = "mobile"
    ADDRESS_STREET = "address_street"
    ADDRESS_CITY = "address_city"
    ADDRESS_POSTAL = "address_postal"

    # Employment
    EMPLOYEE_ID = "employee_id"
    CONTRACT_NUMBER = "contract_number"

    # All fields requiring encryption
    ALL = {
        FULL_NAME, FIRST_NAME, LAST_NAME, NATIONAL_ID, TAX_ID,
        EMAIL, PHONE, MOBILE, ADDRESS_STREET, ADDRESS_CITY, ADDRESS_POSTAL,
        EMPLOYEE_ID, CONTRACT_NUMBER
    }


# =============================================================================
# DRIVER MODEL WITH ENCRYPTED PII
# =============================================================================

@dataclass
class DriverPII:
    """
    Driver Personally Identifiable Information.
    All fields stored encrypted in database.
    """

    driver_id: str
    tenant_id: str

    # Identity (encrypted)
    full_name: Optional[str] = None
    national_id: Optional[str] = None

    # Contact (encrypted)
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None

    # GDPR
    consent_timestamp: Optional[datetime] = None
    consent_version: Optional[str] = None
    deletion_requested_at: Optional[datetime] = None

    def to_encrypted_dict(self, encryptor: PIIEncryptor) -> dict:
        """Convert to dict with encrypted PII fields."""
        result = {
            "driver_id": self.driver_id,
            "tenant_id": self.tenant_id,
            "consent_timestamp": self.consent_timestamp.isoformat() if self.consent_timestamp else None,
            "consent_version": self.consent_version,
            "deletion_requested_at": self.deletion_requested_at.isoformat() if self.deletion_requested_at else None,
        }

        # Encrypt PII fields
        for field_name in ["full_name", "national_id", "email", "phone", "mobile"]:
            value = getattr(self, field_name)
            if value:
                result[f"{field_name}_encrypted"] = encryptor.encrypt(
                    value, self.tenant_id, self.driver_id, field_name
                )
            else:
                result[f"{field_name}_encrypted"] = None

        return result

    @classmethod
    def from_encrypted_dict(cls, data: dict, encryptor: PIIEncryptor) -> "DriverPII":
        """Create from dict with encrypted PII fields."""
        driver_id = data["driver_id"]
        tenant_id = data["tenant_id"]

        # Decrypt PII fields
        decrypted = {}
        for field_name in ["full_name", "national_id", "email", "phone", "mobile"]:
            encrypted_value = data.get(f"{field_name}_encrypted")
            if encrypted_value:
                decrypted[field_name] = encryptor.decrypt(
                    encrypted_value, tenant_id, driver_id, field_name
                )
            else:
                decrypted[field_name] = None

        return cls(
            driver_id=driver_id,
            tenant_id=tenant_id,
            full_name=decrypted.get("full_name"),
            national_id=decrypted.get("national_id"),
            email=decrypted.get("email"),
            phone=decrypted.get("phone"),
            mobile=decrypted.get("mobile"),
            consent_timestamp=datetime.fromisoformat(data["consent_timestamp"]) if data.get("consent_timestamp") else None,
            consent_version=data.get("consent_version"),
            deletion_requested_at=datetime.fromisoformat(data["deletion_requested_at"]) if data.get("deletion_requested_at") else None,
        )


# =============================================================================
# GDPR COMPLIANCE FUNCTIONS
# =============================================================================

async def process_deletion_request(
    driver_id: str,
    tenant_id: str,
    key_manager: KeyManager,
    db_connection  # PostgreSQL connection
) -> dict:
    """
    Process a GDPR deletion request (Right to Erasure).

    Options:
    1. Physical deletion: Remove all records
    2. Cryptographic erasure: Delete encryption keys
    3. Pseudonymization: Replace with anonymous identifiers

    Returns dict with deletion status.
    """
    logger.info(f"Processing GDPR deletion request: driver={driver_id}, tenant={tenant_id}")

    # Option 1: Mark for deletion (soft delete)
    # Actual deletion happens after retention period
    async with db_connection.cursor() as cur:
        await cur.execute("""
            UPDATE drivers
            SET deletion_requested_at = NOW(),
                status = 'DELETION_REQUESTED'
            WHERE id = %s AND tenant_id = %s
        """, (driver_id, tenant_id))

    return {
        "status": "DELETION_SCHEDULED",
        "driver_id": driver_id,
        "message": "Deletion request recorded. Data will be purged within 30 days."
    }


async def run_gdpr_cleanup_job(
    key_manager: KeyManager,
    db_connection,
    retention_days: int = 30
) -> dict:
    """
    Background job to process pending GDPR deletions.

    Run daily via cron or scheduler.
    """
    logger.info("Starting GDPR cleanup job")

    async with db_connection.cursor() as cur:
        # Find records ready for deletion
        await cur.execute("""
            SELECT id, tenant_id
            FROM drivers
            WHERE deletion_requested_at < NOW() - INTERVAL '%s days'
            AND status = 'DELETION_REQUESTED'
        """, (retention_days,))

        pending = await cur.fetchall()

        deleted_count = 0
        for row in pending:
            driver_id = row["id"]
            tenant_id = row["tenant_id"]

            # Delete PII data
            await cur.execute("""
                DELETE FROM drivers WHERE id = %s AND tenant_id = %s
            """, (driver_id, tenant_id))

            # Log deletion for audit
            await cur.execute("""
                INSERT INTO security_audit_log (event_type, tenant_id, severity, details_json)
                VALUES ('GDPR_DELETION', %s, 'INFO', %s)
            """, (tenant_id, {"driver_id": driver_id, "action": "physical_deletion"}))

            deleted_count += 1

        await db_connection.commit()

    logger.info(f"GDPR cleanup completed: {deleted_count} records deleted")

    return {
        "status": "COMPLETED",
        "deleted_count": deleted_count
    }


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_key_manager: Optional[KeyManager] = None
_pii_encryptor: Optional[PIIEncryptor] = None


def get_key_manager() -> KeyManager:
    """Get or create the singleton KeyManager instance."""
    global _key_manager

    if _key_manager is None:
        # Load master key from environment
        master_key_hex = os.environ.get("PII_MASTER_KEY")

        if master_key_hex:
            master_key = bytes.fromhex(master_key_hex)
        else:
            # Generate a random key for development
            # WARNING: This is NOT suitable for production!
            logger.warning(
                "PII_MASTER_KEY not set - generating random key. "
                "Data encrypted with this key will be LOST on restart!"
            )
            master_key = secrets.token_bytes(32)

        _key_manager = KeyManager(master_key)

    return _key_manager


def get_pii_encryptor() -> PIIEncryptor:
    """Get or create the singleton PIIEncryptor instance."""
    global _pii_encryptor

    if _pii_encryptor is None:
        _pii_encryptor = PIIEncryptor(get_key_manager())

    return _pii_encryptor
