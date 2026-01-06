# ADR-001: PII Encryption Key Management

**Status**: Accepted
**Date**: 2026-01-05
**Author**: Security Team

---

## Context

SOLVEREIGN stores Personally Identifiable Information (PII) for drivers:
- Full name
- National ID / Tax ID
- Email, Phone, Mobile
- Address

GDPR requires encryption at rest and the ability to perform "cryptographic erasure" (delete encryption key = data unreadable).

## Decision

### Architecture: Envelope Encryption with KMS

```
┌─────────────────────────────────────────────────────────────────┐
│                    KEY HIERARCHY                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐                                            │
│  │   Master Key    │  Stored in: AWS KMS / HashiCorp Vault      │
│  │   (KEK - Key    │  Never leaves KMS                          │
│  │   Encryption    │  Used to wrap/unwrap DEKs                  │
│  │   Key)          │                                            │
│  └────────┬────────┘                                            │
│           │                                                     │
│           │ wraps/unwraps                                       │
│           ▼                                                     │
│  ┌─────────────────┐                                            │
│  │  Data Encryption│  One per tenant                            │
│  │  Key (DEK)      │  Stored encrypted in DB                    │
│  │  - tenant_dek   │  256-bit AES                               │
│  └────────┬────────┘                                            │
│           │                                                     │
│           │ encrypts                                            │
│           ▼                                                     │
│  ┌─────────────────┐                                            │
│  │   PII Fields    │  Encrypted with tenant DEK                 │
│  │   - driver_name │  AAD: tenant_id + driver_id                │
│  │   - email       │  Stored in PostgreSQL                      │
│  │   - phone       │                                            │
│  └─────────────────┘                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key Storage by Environment

| Environment | KEK Storage | DEK Storage | Notes |
|-------------|-------------|-------------|-------|
| **Development** | Env var `PII_MASTER_KEY` | Memory | WARNING logged |
| **Staging** | AWS KMS (test key) | PostgreSQL (encrypted) | Full KMS integration |
| **Production** | AWS KMS (prod key) | PostgreSQL (encrypted) | Audited, rotatable |

### Key Rotation Procedure

1. **Generate new DEK version** (v2)
2. **24-hour overlap period**: Both v1 and v2 active
3. **Re-encrypt existing data**: Background job migrates ciphertext from v1 to v2
4. **Retire v1**: After all data migrated, mark v1 as inactive
5. **Archive v1**: Keep for 90 days (regulatory), then delete

```python
# Simplified rotation flow
async def rotate_tenant_key(tenant_id: str):
    # 1. Generate new DEK
    new_dek = await kms.generate_data_key()
    await store_encrypted_dek(tenant_id, new_dek, version=current_version + 1)

    # 2. Start overlap period
    await set_key_status(tenant_id, current_version, status='overlap')

    # 3. Queue re-encryption job
    await queue_job('re_encrypt_tenant_pii', tenant_id=tenant_id, from_version=current_version)

    # 4. Job marks old key inactive when complete
```

### GDPR Cryptographic Erasure

When a driver requests deletion:

1. **Option A: Physical Deletion**
   - Delete all driver records from database
   - Simple but leaves audit gaps

2. **Option B: Cryptographic Erasure** (Preferred)
   - Delete the driver's DEK (or tenant DEK if per-driver keys)
   - Data becomes unreadable
   - Audit log preserved (events, not PII)
   - Metadata retained (anonymized driver ID)

```sql
-- Crypto-shred a driver
DELETE FROM encryption_keys
WHERE tenant_id = $1 AND driver_id = $2;

-- Update driver record to mark as deleted
UPDATE drivers
SET status = 'CRYPTO_DELETED',
    full_name_encrypted = NULL,
    email_encrypted = NULL,
    phone_encrypted = NULL
WHERE id = $2 AND tenant_id = $1;
```

## Implementation Details

### Current Implementation (`api/security/encryption.py`)

- AES-256-GCM encryption
- AAD (Additional Authenticated Data) binds ciphertext to context
- Key versioning support
- HKDF for key derivation from master key

### What's Missing (Future Work)

1. **KMS Integration**: Replace env var with AWS KMS API calls
2. **Per-Tenant DEK**: Currently derives from single master key
3. **Key Rotation Jobs**: Background worker for re-encryption
4. **Key Audit Log**: Track all key operations

### Security Controls

| Control | Status |
|---------|--------|
| KEK in HSM/KMS | ⏳ Pending KMS integration |
| DEK per tenant | ⏳ Pending schema update |
| AAD binding | ✅ Implemented |
| Key versioning | ✅ Implemented |
| Rotation procedure | ✅ Documented |
| Crypto-erasure | ✅ Implemented |

## Consequences

### Positive

- GDPR compliant encryption at rest
- Cryptographic erasure possible
- Key rotation without data loss
- AAD prevents cross-tenant attacks

### Negative

- Additional complexity
- Latency for encryption/decryption
- KMS dependency in production
- Key loss = data loss (backup KEK!)

### Risks

| Risk | Mitigation |
|------|------------|
| KEK loss | Multi-region KMS backup |
| DEK corruption | Transaction-safe DB storage |
| Performance | Cache decrypted data in memory (with TTL) |
| Audit | All key operations logged |

## Alternatives Considered

1. **PostgreSQL pgcrypto**: Rejected - keys in DB, no HSM
2. **Application-level only**: Rejected - no hardware protection
3. **Full-disk encryption only**: Rejected - no field-level control

---

## References

- [GDPR Art. 17 - Right to Erasure](https://gdpr-info.eu/art-17-gdpr/)
- [AWS KMS Envelope Encryption](https://docs.aws.amazon.com/kms/latest/developerguide/concepts.html#enveloping)
- [NIST SP 800-57 Key Management](https://csrc.nist.gov/publications/detail/sp/800-57-part-1/rev-5/final)
