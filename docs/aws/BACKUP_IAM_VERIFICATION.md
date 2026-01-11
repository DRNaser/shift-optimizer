# Backup IAM Verification Checklist

**System**: SOLVEREIGN V3.7+
**Owner**: Platform Engineering
**Last Updated**: 2026-01-11

---

## Purpose

This checklist verifies that backup IAM policies follow least-privilege principles and that backup/restore operations work correctly in production.

---

## Pre-Deployment Verification

### 1. IAM Policy Review

- [ ] Policy uses `backup-iam-policy.json` template
- [ ] `${ENV}` placeholder replaced with actual environment (staging/prod)
- [ ] No `s3:*` wildcard actions
- [ ] No `s3:PutObjectAcl` (ACLs disabled on bucket)
- [ ] Delete scoped to `postgresql/*` prefix only

### 2. Bucket Configuration

- [ ] Bucket versioning enabled
- [ ] Server-side encryption enabled (SSE-S3 or SSE-KMS)
- [ ] Block Public Access enabled (all 4 settings)
- [ ] Lifecycle policy configured (e.g., 90-day retention)

```bash
# Verify bucket settings
aws s3api get-bucket-versioning --bucket solvereign-backups-${ENV}
aws s3api get-bucket-encryption --bucket solvereign-backups-${ENV}
aws s3api get-public-access-block --bucket solvereign-backups-${ENV}
```

---

## Backup CronJob Verification

### 3. CronJob Configuration

- [ ] Runs in Kubernetes namespace: `solvereign`
- [ ] Uses service account with IAM role (IRSA) or secrets
- [ ] Schedule: `0 2 * * *` (2 AM daily) or as specified
- [ ] Resource limits set (cpu/memory)

```bash
# View CronJob
kubectl get cronjob -n solvereign backup-postgres

# Check last job status
kubectl get jobs -n solvereign -l app=backup-postgres --sort-by=.metadata.creationTimestamp
```

### 4. Manual Backup Test

```bash
# Trigger backup manually
kubectl create job --from=cronjob/backup-postgres backup-manual-$(date +%Y%m%d) -n solvereign

# Wait and check logs
kubectl logs job/backup-manual-$(date +%Y%m%d) -n solvereign

# Verify file exists in S3
aws s3 ls s3://solvereign-backups-${ENV}/postgresql/ --recursive | tail -5
```

---

## Restore Verification (Go/No-Go Item #8)

### 5. Restore Test (Weekly or Pre-Release)

**IMPORTANT**: This is Go/No-Go checklist item #8. Restore must be tested before any GA release.

```bash
# Set environment for safety
export SOLVEREIGN_ENV=staging

# Run restore verification script
python scripts/verify_backup_restore.py --bucket solvereign-backups-staging

# Expected output:
# [INFO] RESULT: PASS - Restore verification successful
```

### 6. Restore Test Results

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Database created | Yes | | |
| Restore completes | Yes | | |
| Tenant count >0 | Yes | | |
| User count >0 | Yes | | |
| Hardening PASS | 17/17 | | |
| Test DB dropped | Yes | | |

---

## Production Safety

### 7. Safety Guard Verification

The restore script includes production safety guards:

```bash
# This MUST fail in production
SOLVEREIGN_ENV=production python scripts/verify_backup_restore.py --bucket solvereign-backups-prod
# Expected: Exit code 3, "PRODUCTION SAFETY CHECK FAILED"

# This MUST succeed in staging
SOLVEREIGN_ENV=staging python scripts/verify_backup_restore.py --bucket solvereign-backups-staging
# Expected: "Safety check passed: SOLVEREIGN_ENV=staging"
```

### 8. Override Flag (Emergency Only)

The `--i-know-what-im-doing` flag allows production execution with a 5-second warning:

```bash
# DANGEROUS - Only for emergency restore scenarios
python scripts/verify_backup_restore.py \
  --bucket solvereign-backups-prod \
  --i-know-what-im-doing
```

---

## IAM Actions Reference

| Action | Purpose | Scoped To |
|--------|---------|-----------|
| `s3:PutObject` | Upload backup | Bucket + prefix |
| `s3:GetObject` | Download for restore | Bucket + prefix |
| `s3:ListBucket` | Find latest backup | Bucket |
| `s3:DeleteObject` | Rotate old backups | `postgresql/*` only |

### Actions NOT Needed

| Action | Reason |
|--------|--------|
| `s3:PutObjectAcl` | Bucket ACLs disabled |
| `s3:GetBucketAcl` | Not needed for backup ops |
| `s3:DeleteBucket` | Never delete bucket |
| `s3:*` | Overly permissive |

---

## Troubleshooting

### Backup Fails with AccessDenied

1. Check IAM role attached to service account
2. Verify bucket name matches policy
3. Check bucket policy doesn't override IAM

```bash
# Debug IAM
kubectl exec -it deploy/api -n solvereign -- aws sts get-caller-identity
kubectl exec -it deploy/api -n solvereign -- aws s3 ls s3://solvereign-backups-${ENV}/
```

### Restore Fails with "File not found"

1. Check S3 prefix is correct (`postgresql/`)
2. Verify backup completed successfully
3. Check file permissions in S3

```bash
# List backups
aws s3 ls s3://solvereign-backups-${ENV}/postgresql/ --recursive
```

### Safety Check Blocks Execution

1. Set `SOLVEREIGN_ENV=staging` or `development`
2. Verify DATABASE_URL points to non-production host
3. If emergency, use `--i-know-what-im-doing` with caution

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Platform Lead | | | |
| Security Lead | | | |
| Ops Engineer | | | |

---

**Document Version**: 1.0
**Next Review**: After first production backup cycle
