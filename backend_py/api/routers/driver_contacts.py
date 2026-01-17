"""
SOLVEREIGN V4.6 - Driver Contacts API
======================================

Endpoints for managing driver contact information:
- CRUD operations for driver contacts
- WhatsApp consent management
- E.164 phone validation
- DM eligibility verification

NON-NEGOTIABLES:
- All phone numbers must be E.164 format
- Consent changes are audited
- tenant_id comes from session binding, NEVER from client
- DM blocked if consent_whatsapp != TRUE
"""

import logging
import re
from typing import Optional, List
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Request, HTTPException, status, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from ..security.internal_rbac import (
    InternalUserContext,
    require_session,
    require_permission,
    get_rbac_repository,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/driver-contacts", tags=["driver-contacts"])


# =============================================================================
# DATABASE CONNECTION HELPER
# =============================================================================

def get_conn_with_rls_context(request: Request, user: InternalUserContext):
    """
    Get database connection with RLS context set for the user's tenant.

    Uses the RBAC repository's connection and sets the RLS context variables.
    Connection is managed per-request via request.state (autocommit=True).

    Args:
        request: FastAPI request object
        user: Authenticated user context

    Returns:
        psycopg connection with RLS context configured
    """
    repo = get_rbac_repository(request)
    conn = repo.conn

    # Set RLS context
    tenant_id = user.get_effective_tenant_id()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config('app.current_user_id', %s, TRUE)",
            (str(user.user_id),)
        )
        if tenant_id is not None:
            cur.execute(
                "SELECT set_config('app.current_tenant_id', %s, TRUE)",
                (str(tenant_id),)
            )
        if user.site_id:
            cur.execute(
                "SELECT set_config('app.current_site_id', %s, TRUE)",
                (str(user.site_id),)
            )
        if user.is_platform_admin:
            cur.execute(
                "SELECT set_config('app.is_platform_admin', 'true', TRUE)"
            )

    return conn


# =============================================================================
# PHONE VALIDATION
# =============================================================================

E164_PATTERN = re.compile(r'^\+[1-9][0-9]{6,14}$')

def validate_e164(phone: str) -> bool:
    """Validate phone number is in E.164 format."""
    return bool(E164_PATTERN.match(phone))

def normalize_to_e164(phone: str, default_country_code: str = "+43") -> Optional[str]:
    """
    Normalize phone number to E.164 format.

    Args:
        phone: Phone number in various formats
        default_country_code: Default country code (Austria)

    Returns:
        E.164 formatted phone or None if invalid
    """
    if not phone:
        return None

    # Remove all non-digit characters except leading +
    clean = re.sub(r'[^0-9+]', '', phone)

    # Handle different formats
    if clean.startswith('+'):
        result = clean
    elif clean.startswith('00'):
        result = '+' + clean[2:]
    elif clean.startswith('0'):
        result = default_country_code + clean[1:]
    else:
        result = '+' + clean

    return result if validate_e164(result) else None


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class DriverContactCreate(BaseModel):
    """Create driver contact request."""
    driver_id: UUID = Field(..., description="Canonical driver UUID from MDL")
    display_name: str = Field(..., min_length=1, max_length=255, description="Driver display name")
    phone: str = Field(..., description="Phone number (will be normalized to E.164)")
    site_id: Optional[UUID] = Field(None, description="Site UUID")
    driver_external_id: Optional[str] = Field(None, description="Original external ID")
    consent_whatsapp: bool = Field(False, description="WhatsApp consent")
    consent_source: Optional[str] = Field(None, description="Consent source (PORTAL, APP, MANUAL)")
    department: Optional[str] = Field(None, description="Department for grouping")
    notes: Optional[str] = Field(None, description="Admin notes")

    @validator('phone')
    def validate_phone(cls, v):
        normalized = normalize_to_e164(v)
        if not normalized:
            raise ValueError(f"Invalid phone number format. Must be E.164 (e.g., +436641234567). Got: {v}")
        return normalized


class DriverContactUpdate(BaseModel):
    """Update driver contact request."""
    display_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, description="Phone number (will be normalized)")
    site_id: Optional[UUID] = None
    department: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = Field(None, description="active, inactive, or blocked")

    @validator('phone')
    def validate_phone(cls, v):
        if v is None:
            return v
        normalized = normalize_to_e164(v)
        if not normalized:
            raise ValueError(f"Invalid phone number format. Got: {v}")
        return normalized

    @validator('status')
    def validate_status(cls, v):
        if v is not None and v not in ('active', 'inactive', 'blocked'):
            raise ValueError("Status must be 'active', 'inactive', or 'blocked'")
        return v


class ConsentUpdate(BaseModel):
    """Update consent request."""
    consent: bool = Field(..., description="Grant (true) or revoke (false) consent")
    source: str = Field("MANUAL", description="Consent source (PORTAL, APP, MANUAL)")


class DriverContactResponse(BaseModel):
    """Driver contact response."""
    id: UUID
    driver_id: UUID
    display_name: str
    phone_e164: str
    site_id: Optional[UUID]
    driver_external_id: Optional[str]
    consent_whatsapp: bool
    consent_whatsapp_at: Optional[datetime]
    consent_source: Optional[str]
    opt_out_at: Optional[datetime]
    status: str
    department: Optional[str]
    last_contacted_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class DMEligibilityResponse(BaseModel):
    """DM eligibility check response."""
    driver_id: UUID
    can_send: bool
    display_name: Optional[str]
    phone_e164: Optional[str]
    errors: List[str] = Field(default_factory=list)


class BulkConsentRequest(BaseModel):
    """Bulk consent update request."""
    driver_ids: List[UUID] = Field(..., min_items=1, max_items=100)
    consent: bool
    source: str = Field("MANUAL")


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("", response_model=List[DriverContactResponse])
async def list_driver_contacts(
    request: Request,
    site_id: Optional[UUID] = Query(None, description="Filter by site"),
    status: Optional[str] = Query(None, description="Filter by status"),
    consent_whatsapp: Optional[bool] = Query(None, description="Filter by consent"),
    search: Optional[str] = Query(None, description="Search by name or phone"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: InternalUserContext = Depends(require_permission("tenant.drivers.read")),
):
    """List driver contacts for the current tenant."""
    conn = get_conn_with_rls_context(request, user)
    with conn.cursor() as cur:
        # Build query
        conditions = ["tenant_id = %s"]
        params = [user.get_effective_tenant_id()]

        if site_id:
            conditions.append("site_id = %s")
            params.append(str(site_id))

        if status:
            conditions.append("status = %s")
            params.append(status)

        if consent_whatsapp is not None:
            conditions.append("consent_whatsapp = %s")
            params.append(consent_whatsapp)

        if search:
            conditions.append("(display_name ILIKE %s OR phone_e164 LIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])

        params.extend([limit, offset])

        query = f"""
            SELECT id, driver_id, display_name, phone_e164, site_id,
                   driver_external_id, consent_whatsapp, consent_whatsapp_at,
                   consent_source, opt_out_at, status, department,
                   last_contacted_at, created_at, updated_at
            FROM masterdata.driver_contacts
            WHERE {' AND '.join(conditions)}
            ORDER BY display_name
            LIMIT %s OFFSET %s
        """

        cur.execute(query, params)
        rows = cur.fetchall()

        return [
            DriverContactResponse(
                id=row[0], driver_id=row[1], display_name=row[2],
                phone_e164=row[3], site_id=row[4], driver_external_id=row[5],
                consent_whatsapp=row[6], consent_whatsapp_at=row[7],
                consent_source=row[8], opt_out_at=row[9], status=row[10],
                department=row[11], last_contacted_at=row[12],
                created_at=row[13], updated_at=row[14]
            )
            for row in rows
        ]


@router.get("/{contact_id}", response_model=DriverContactResponse)
async def get_driver_contact(
    contact_id: UUID,
    request: Request,
    user: InternalUserContext = Depends(require_permission("tenant.drivers.read")),
):
    """Get a specific driver contact."""
    conn = get_conn_with_rls_context(request, user)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, driver_id, display_name, phone_e164, site_id,
                   driver_external_id, consent_whatsapp, consent_whatsapp_at,
                   consent_source, opt_out_at, status, department,
                   last_contacted_at, created_at, updated_at
            FROM masterdata.driver_contacts
            WHERE id = %s AND tenant_id = %s
        """, (str(contact_id), user.get_effective_tenant_id()))

        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Driver contact not found")

        return DriverContactResponse(
            id=row[0], driver_id=row[1], display_name=row[2],
            phone_e164=row[3], site_id=row[4], driver_external_id=row[5],
            consent_whatsapp=row[6], consent_whatsapp_at=row[7],
            consent_source=row[8], opt_out_at=row[9], status=row[10],
            department=row[11], last_contacted_at=row[12],
            created_at=row[13], updated_at=row[14]
        )


@router.post("", response_model=DriverContactResponse, status_code=201)
async def create_driver_contact(
    body: DriverContactCreate,
    request: Request,
    user: InternalUserContext = Depends(require_permission("tenant.drivers.write")),
):
    """Create a new driver contact."""
    conn = get_conn_with_rls_context(request, user)
    try:
        with conn.cursor() as cur:
            tenant_id = user.get_effective_tenant_id()

            # Use upsert function
            cur.execute("""
                SELECT masterdata.upsert_driver_contact(
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                tenant_id,
                str(body.driver_id),
                body.display_name,
                body.phone,  # Already normalized by validator
                str(body.site_id) if body.site_id else None,
                body.consent_whatsapp,
                body.consent_source,
                '{}'  # metadata
            ))

            contact_id = cur.fetchone()[0]

            # Update additional fields
            if body.driver_external_id or body.department or body.notes:
                cur.execute("""
                    UPDATE masterdata.driver_contacts
                    SET driver_external_id = COALESCE(%s, driver_external_id),
                        department = COALESCE(%s, department),
                        notes = COALESCE(%s, notes)
                    WHERE id = %s
                """, (body.driver_external_id, body.department, body.notes, str(contact_id)))

            # Fetch and return created contact
            cur.execute("""
                SELECT id, driver_id, display_name, phone_e164, site_id,
                       driver_external_id, consent_whatsapp, consent_whatsapp_at,
                       consent_source, opt_out_at, status, department,
                       last_contacted_at, created_at, updated_at
                FROM masterdata.driver_contacts
                WHERE id = %s
            """, (str(contact_id),))

            row = cur.fetchone()

            logger.info(f"Created driver contact {contact_id} for driver {body.driver_id}")

            return DriverContactResponse(
                id=row[0], driver_id=row[1], display_name=row[2],
                phone_e164=row[3], site_id=row[4], driver_external_id=row[5],
                consent_whatsapp=row[6], consent_whatsapp_at=row[7],
                consent_source=row[8], opt_out_at=row[9], status=row[10],
                department=row[11], last_contacted_at=row[12],
                created_at=row[13], updated_at=row[14]
            )
    except Exception as e:
        if "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="Driver contact already exists (duplicate phone or driver_id)"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{contact_id}", response_model=DriverContactResponse)
async def update_driver_contact(
    contact_id: UUID,
    body: DriverContactUpdate,
    request: Request,
    user: InternalUserContext = Depends(require_permission("tenant.drivers.write")),
):
    """Update a driver contact."""
    conn = get_conn_with_rls_context(request, user)
    with conn.cursor() as cur:
        # Build update query dynamically
        updates = []
        params = []

        if body.display_name is not None:
            updates.append("display_name = %s")
            params.append(body.display_name)

        if body.phone is not None:
            updates.append("phone_e164 = %s")
            params.append(body.phone)  # Already normalized

        if body.site_id is not None:
            updates.append("site_id = %s")
            params.append(str(body.site_id))

        if body.department is not None:
            updates.append("department = %s")
            params.append(body.department)

        if body.notes is not None:
            updates.append("notes = %s")
            params.append(body.notes)

        if body.status is not None:
            updates.append("status = %s")
            params.append(body.status)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = NOW()")
        params.extend([str(contact_id), user.get_effective_tenant_id()])

        cur.execute(f"""
            UPDATE masterdata.driver_contacts
            SET {', '.join(updates)}
            WHERE id = %s AND tenant_id = %s
            RETURNING id
        """, params)

        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Driver contact not found")

        # Fetch updated contact
        cur.execute("""
            SELECT id, driver_id, display_name, phone_e164, site_id,
                   driver_external_id, consent_whatsapp, consent_whatsapp_at,
                   consent_source, opt_out_at, status, department,
                   last_contacted_at, created_at, updated_at
            FROM masterdata.driver_contacts
            WHERE id = %s
        """, (str(contact_id),))

        row = cur.fetchone()

        return DriverContactResponse(
            id=row[0], driver_id=row[1], display_name=row[2],
            phone_e164=row[3], site_id=row[4], driver_external_id=row[5],
            consent_whatsapp=row[6], consent_whatsapp_at=row[7],
            consent_source=row[8], opt_out_at=row[9], status=row[10],
            department=row[11], last_contacted_at=row[12],
            created_at=row[13], updated_at=row[14]
        )


@router.post("/{contact_id}/consent", response_model=DriverContactResponse)
async def update_consent(
    contact_id: UUID,
    body: ConsentUpdate,
    request: Request,
    user: InternalUserContext = Depends(require_permission("tenant.drivers.write")),
):
    """Update WhatsApp consent for a driver contact."""
    conn = get_conn_with_rls_context(request, user)
    with conn.cursor() as cur:
        # Get driver_id for the contact
        cur.execute("""
            SELECT driver_id FROM masterdata.driver_contacts
            WHERE id = %s AND tenant_id = %s
        """, (str(contact_id), user.get_effective_tenant_id()))

        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Driver contact not found")

        driver_id = row[0]

        # Use the consent function (handles audit)
        cur.execute("""
            SELECT masterdata.set_whatsapp_consent(%s, %s, %s, %s)
        """, (user.get_effective_tenant_id(), str(driver_id), body.consent, body.source))

        logger.info(
            f"Updated WhatsApp consent for contact {contact_id}: "
            f"consent={body.consent}, source={body.source}"
        )

        # Fetch updated contact
        cur.execute("""
            SELECT id, driver_id, display_name, phone_e164, site_id,
                   driver_external_id, consent_whatsapp, consent_whatsapp_at,
                   consent_source, opt_out_at, status, department,
                   last_contacted_at, created_at, updated_at
            FROM masterdata.driver_contacts
            WHERE id = %s
        """, (str(contact_id),))

        row = cur.fetchone()

        return DriverContactResponse(
            id=row[0], driver_id=row[1], display_name=row[2],
            phone_e164=row[3], site_id=row[4], driver_external_id=row[5],
            consent_whatsapp=row[6], consent_whatsapp_at=row[7],
            consent_source=row[8], opt_out_at=row[9], status=row[10],
            department=row[11], last_contacted_at=row[12],
            created_at=row[13], updated_at=row[14]
        )


@router.post("/bulk-consent")
async def bulk_update_consent(
    body: BulkConsentRequest,
    request: Request,
    user: InternalUserContext = Depends(require_permission("tenant.drivers.write")),
):
    """Update WhatsApp consent for multiple drivers at once."""
    conn = get_conn_with_rls_context(request, user)
    with conn.cursor() as cur:
        tenant_id = user.get_effective_tenant_id()

        updated = 0
        not_found = []

        for driver_id in body.driver_ids:
            cur.execute("""
                SELECT masterdata.set_whatsapp_consent(%s, %s, %s, %s)
            """, (tenant_id, str(driver_id), body.consent, body.source))

            result = cur.fetchone()[0]
            if result:
                updated += 1
            else:
                not_found.append(str(driver_id))

        logger.info(
            f"Bulk consent update: {updated} updated, "
            f"{len(not_found)} not found, consent={body.consent}"
        )

        return {
            "updated_count": updated,
            "not_found_count": len(not_found),
            "not_found_driver_ids": not_found[:10],  # Limit response size
            "consent": body.consent,
            "source": body.source
        }


@router.get("/driver/{driver_id}/dm-eligibility", response_model=DMEligibilityResponse)
async def check_dm_eligibility(
    driver_id: UUID,
    request: Request,
    user: InternalUserContext = Depends(require_permission("tenant.drivers.read")),
):
    """Check if a driver can receive WhatsApp DMs (fail-fast check)."""
    conn = get_conn_with_rls_context(request, user)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT masterdata.verify_contact_for_dm(%s, %s)
        """, (user.get_effective_tenant_id(), str(driver_id)))

        result = cur.fetchone()[0]

        return DMEligibilityResponse(
            driver_id=driver_id,
            can_send=result.get('can_send', False),
            display_name=result.get('display_name'),
            phone_e164=result.get('phone_e164'),
            errors=result.get('errors', [])
        )


@router.get("/contactable")
async def list_contactable_drivers(
    request: Request,
    site_id: Optional[UUID] = Query(None, description="Filter by site"),
    user: InternalUserContext = Depends(require_permission("tenant.drivers.read")),
):
    """List all drivers who can be contacted via WhatsApp."""
    conn = get_conn_with_rls_context(request, user)
    with conn.cursor() as cur:
        site_param = str(site_id) if site_id else None

        cur.execute("""
            SELECT driver_id, display_name, phone_e164, site_id, consent_whatsapp_at
            FROM masterdata.get_contactable_drivers(%s, NULL, %s)
        """, (user.get_effective_tenant_id(), site_param))

        rows = cur.fetchall()

        return {
            "contactable_count": len(rows),
            "drivers": [
                {
                    "driver_id": row[0],
                    "display_name": row[1],
                    "phone_e164": row[2],
                    "site_id": row[3],
                    "consent_at": row[4].isoformat() if row[4] else None
                }
                for row in rows
            ]
        }


@router.post("/validate-phone")
async def validate_phone_number(
    request: Request,
    phone: str = Query(..., description="Phone number to validate"),
    user: InternalUserContext = Depends(require_session),
):
    """Validate and normalize a phone number to E.164 format."""
    normalized = normalize_to_e164(phone)

    return {
        "original": phone,
        "normalized": normalized,
        "valid": normalized is not None,
        "format": "E.164" if normalized else None,
        "error": None if normalized else "Cannot normalize to E.164 format"
    }
