# WhatsApp DM Configuration Guide

> **Version**: V4.6 | **Last Updated**: 2026-01-14

This document describes the configuration and operational steps for the WhatsApp DM communication system in SOLVEREIGN.

---

## Overview

SOLVEREIGN supports WhatsApp Direct Messages (DMs) to drivers for:
- Plan notifications (offers, acknowledgements)
- Coverage-now suggestions
- Reminders

**Key Principles:**
- **Consent Required**: No message sent without `consent_whatsapp = TRUE`
- **Template Only**: All messages use pre-approved Meta templates (no free text)
- **Full Audit**: Every message and consent change is logged

---

## Environment Variables

### Meta WhatsApp Cloud API (PRIMARY)

| Variable | Description | Required |
|----------|-------------|----------|
| `WHATSAPP_META_ACCESS_TOKEN` | Meta Graph API access token | Yes |
| `WHATSAPP_META_PHONE_NUMBER_ID` | WhatsApp Business phone number ID | Yes |
| `WHATSAPP_META_WEBHOOK_VERIFY_TOKEN` | Token for webhook verification | Yes |
| `WHATSAPP_META_APP_SECRET` | App secret for webhook signature verification | Yes |

**Example `.env`:**
```bash
WHATSAPP_META_ACCESS_TOKEN=EAAxxxxxxxxx...
WHATSAPP_META_PHONE_NUMBER_ID=123456789012345
WHATSAPP_META_WEBHOOK_VERIFY_TOKEN=my-secure-verify-token-2026
WHATSAPP_META_APP_SECRET=abcdef123456...
```

### ClawdBot (OPTIONAL Secondary)

| Variable | Description | Required |
|----------|-------------|----------|
| `CLAWDBOT_API_KEY` | ClawdBot API key | No |
| `CLAWDBOT_API_URL` | ClawdBot API base URL | No (default: `https://api.clawdbot.com/v1`) |

**Note:** ClawdBot is NOT required for core flows. It serves as an optional backup provider.

---

## Database Migrations

Apply migrations in order:

```bash
# 1. Driver contacts table with E.164 validation
psql $DATABASE_URL < backend_py/db/migrations/055_driver_contacts.sql

# 2. WhatsApp provider abstraction
psql $DATABASE_URL < backend_py/db/migrations/056_whatsapp_provider.sql

# 3. Daily plan importer
psql $DATABASE_URL < backend_py/db/migrations/057_daily_plans.sql

# 4. Approval policy system
psql $DATABASE_URL < backend_py/db/migrations/058_approval_policy.sql
```

### Verify Migrations

```sql
-- Driver contacts
SELECT * FROM masterdata.verify_driver_contacts_integrity();

-- Provider configuration
SELECT * FROM notify.verify_provider_integrity();

-- Daily plans
SELECT * FROM masterdata.verify_daily_plans_integrity();

-- Approval policies
SELECT * FROM auth.verify_approval_policy_integrity();
```

All checks should return `PASS`.

---

## Provider Configuration

### Activate Meta Provider

After setting environment variables, activate the provider in the database:

```sql
-- Activate Meta WhatsApp provider
UPDATE notify.providers
SET
    is_active = TRUE,
    config = jsonb_set(config, '{phone_number_id}', '"YOUR_PHONE_NUMBER_ID"')
WHERE provider_key = 'whatsapp_meta' AND tenant_id IS NULL;
```

### Check Provider Status

```sql
SELECT
    provider_key,
    display_name,
    is_active,
    is_primary,
    health_status,
    last_success_at,
    consecutive_failures
FROM notify.providers
WHERE channel = 'WHATSAPP';
```

---

## WhatsApp Template Setup

### Required Templates

Register these templates with Meta for approval:

| Template Key | Template Name | Category | Variables |
|--------------|---------------|----------|-----------|
| `PORTAL_INVITE` | `portal_invite_v1` | UTILITY | `{{1}}` = driver_name, `{{2}}` = portal_url |
| `REMINDER_24H` | `reminder_24h_v1` | UTILITY | `{{1}}` = driver_name, `{{2}}` = portal_url |
| `COVERAGE_OFFER` | `coverage_offer_v1` | UTILITY | `{{1}}` = driver_name, `{{2}}` = shift_date, `{{3}}` = response_url |

### Template Content Examples

**Portal Invite (German):**
```
Hallo {{1}}, Ihr neuer Schichtplan ist verfügbar.
Bitte bestätigen Sie hier: {{2}}
```

**Reminder (German):**
```
Erinnerung {{1}}: Ihr Schichtplan wartet noch auf Bestätigung.
{{2}}
```

### Update Template Status After Approval

```sql
UPDATE notify.provider_templates
SET approval_status = 'APPROVED', approval_status_at = NOW()
WHERE template_key = 'PORTAL_INVITE' AND wa_template_name = 'portal_invite_v1';
```

---

## Webhook Configuration

### Meta Webhook Endpoint

Configure Meta to send webhooks to:
```
POST https://your-domain.com/api/webhooks/whatsapp/meta
```

### Webhook Verification

Meta sends a GET request to verify the webhook:
```
GET /api/webhooks/whatsapp/meta?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=CHALLENGE
```

Response: Return the `hub.challenge` value if token matches.

### Webhook Events

The system processes these webhook events:
- `sent` → Message accepted by Meta
- `delivered` → Message delivered to device
- `read` → Message read by recipient
- `failed` → Delivery failed

---

## Driver Contact Management

### Phone Number Format

All phone numbers must be in **E.164 format**:
- Format: `+CountryCodeNumber`
- Example: `+436641234567` (Austria)

The system automatically normalizes common formats:
- `0664 123 4567` → `+436641234567`
- `00436641234567` → `+436641234567`
- `+43 664 1234567` → `+436641234567`

### Import Driver Contacts

```python
from api.services.daily_plan_importer import DailyPlanImporter

# Create contact via API
POST /api/driver-contacts
{
    "driver_id": "uuid-here",
    "display_name": "Max Mustermann",
    "phone": "0664 123 4567",  # Auto-normalized
    "consent_whatsapp": true,
    "consent_source": "MANUAL"
}
```

### Consent Management

```python
# Grant consent
POST /api/driver-contacts/{id}/consent
{
    "consent": true,
    "source": "PORTAL"  # PORTAL, APP, MANUAL
}

# Revoke consent (opt-out)
POST /api/driver-contacts/{id}/consent
{
    "consent": false,
    "source": "MANUAL"
}
```

### Bulk Consent Update

```python
POST /api/driver-contacts/bulk-consent
{
    "driver_ids": ["uuid1", "uuid2", "uuid3"],
    "consent": true,
    "source": "IMPORT"
}
```

---

## Daily Plan Import & Verification

### Workflow

1. **Create Plan**
   ```python
   POST /api/daily-plans
   {
       "plan_date": "2026-01-15",
       "source_url": "https://docs.google.com/spreadsheets/d/...",
       "site_id": "site-uuid"
   }
   ```

2. **Import Rows**
   ```python
   POST /api/daily-plans/{id}/import
   {
       "rows": [
           {"row_number": 1, "driver_name": "Max M.", "driver_id": "D001", ...},
           ...
       ]
   }
   ```

3. **Verify Plan**
   ```python
   POST /api/daily-plans/{id}/verify

   # Response includes:
   {
       "report_id": "uuid",
       "can_publish": true/false,
       "verified_count": 10,
       "failed_count": 0,
       "dm_eligible_count": 8,
       "blocking_issues": []
   }
   ```

4. **Check DM Eligibility**
   ```python
   GET /api/daily-plans/{id}/dm-eligibility

   # Returns per-driver eligibility
   ```

### Verification Error Codes

| Code | Description | Blocking? |
|------|-------------|-----------|
| `MISSING_DRIVER_ID` | No driver ID in source | Yes |
| `DRIVER_NOT_IN_MDL` | Unknown driver | Yes |
| `NO_DRIVER_CONTACT` | No contact record | Yes |
| `NO_PHONE_NUMBER` | Missing phone | Yes |
| `INVALID_PHONE_FORMAT` | Bad phone format | Yes |
| `MISSING_CONSENT` | No WhatsApp consent | No (warning) |
| `OPTED_OUT` | Driver opted out | No (warning) |

---

## Approval Policy

### Risk Levels

| Level | Required Approvals | Triggers |
|-------|-------------------|----------|
| `LOW` | 1 | < 10 affected drivers |
| `MEDIUM` | 1 | Standard operations |
| `HIGH` | 2 | > 10 drivers OR freeze period |
| `CRITICAL` | 2 | Rest-time impacts |

### Request Approval

```python
from api.services.approval_policy import ApprovalPolicyService, calculate_risk_context

# Assess risk first
context = calculate_risk_context(
    affected_drivers=driver_list,
    near_rest_time_violations=violations,
    is_freeze_period=False,
    hours_to_deadline=6
)

assessment = await service.assess_action("PUBLISH", "PLAN", context)
# assessment.risk_level, assessment.required_approvals

# Create approval request
request_id = await service.request_approval(
    action_type="PUBLISH",
    entity_type="PLAN",
    entity_id=plan_id,
    entity_name="Weekly Plan Week 3",
    requested_by="dispatcher@example.com",
    action_payload={"plan_id": str(plan_id), "snapshot_id": str(snapshot_id)},
    evidence={"affected_drivers": driver_ids, "affected_count": len(driver_ids)},
    context=context
)
```

### Submit Approval

```python
result = await service.submit_decision(
    request_id=request_id,
    user_id=approver_uuid,
    user_email="approver@example.com",
    user_role="tenant_admin",
    decision="APPROVE",
    reason="Reviewed and approved"
)

if result.is_complete and result.final_status == "APPROVED":
    # Execute the action using result.action_payload
    pass
```

### Emergency Override

```python
result = await service.emergency_override(
    request_id=request_id,
    user_id=approver_uuid,
    user_email="admin@example.com",
    justification="Urgent coverage needed - driver called in sick"
)

# IMPORTANT: Review due within 24 hours
# Check pending reviews:
reviews = await service.get_pending_reviews()
```

---

## Operational Procedures

### Pre-Launch Checklist

- [ ] Meta WhatsApp Business account configured
- [ ] Access token and phone number ID set
- [ ] Webhook endpoint registered and verified
- [ ] Templates submitted and approved by Meta
- [ ] Provider activated in database
- [ ] Test message sent successfully

### Daily Operations

1. **Import daily plans** from Google Sheets
2. **Run verification** to check driver resolution
3. **Review DM eligibility** report
4. **Send notifications** only to eligible drivers

### Consent Audit

```sql
-- View recent consent changes
SELECT
    al.created_at,
    al.action,
    al.entity_id,
    al.changes->>'driver_id' as driver_id,
    al.changes->'consent_whatsapp' as consent_change
FROM auth.audit_log al
WHERE al.entity_type = 'driver_contact'
  AND al.action IN ('CONSENT_GRANTED', 'CONSENT_REVOKED', 'OPT_OUT')
ORDER BY al.created_at DESC
LIMIT 50;
```

### Monitoring

```sql
-- Provider health
SELECT provider_key, health_status, consecutive_failures, last_success_at
FROM notify.providers WHERE channel = 'WHATSAPP';

-- DM queue status
SELECT status, COUNT(*) FROM notify.dm_queue GROUP BY status;

-- Consent coverage
SELECT
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE consent_whatsapp) as consented,
    ROUND(100.0 * COUNT(*) FILTER (WHERE consent_whatsapp) / COUNT(*), 1) as consent_rate
FROM masterdata.driver_contacts
WHERE status = 'active';
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Messages not sending | Provider inactive | Activate provider, check credentials |
| Template rejected | Not approved by Meta | Submit template for approval |
| Consent check failing | Missing consent | Ensure driver has `consent_whatsapp = TRUE` |
| Phone validation failing | Wrong format | Use E.164 format (`+CountryCode...`) |
| Webhook not working | Wrong verify token | Check `WHATSAPP_META_WEBHOOK_VERIFY_TOKEN` |

### Debug Commands

```bash
# Test phone normalization
curl -X POST "http://localhost:8000/api/driver-contacts/validate-phone?phone=0664123456"

# Check DM eligibility
curl "http://localhost:8000/api/driver-contacts/driver/{driver_id}/dm-eligibility"

# View contactable drivers
curl "http://localhost:8000/api/driver-contacts/contactable"
```

---

## Security Notes

1. **Never log access tokens** - Use environment variables only
2. **Webhook signatures** - Always verify HMAC signatures
3. **Consent audit** - All consent changes are permanently logged
4. **RLS enforcement** - All queries are tenant-isolated
5. **Template-only** - No free text messages to prevent abuse

---

## Support

For issues:
1. Check provider health in database
2. Review webhook events in `notify.webhook_events`
3. Check audit log for consent history
4. Verify template approval status

**Contact:** See `CLAUDE.md` for project contacts.
