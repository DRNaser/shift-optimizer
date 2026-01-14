"""
Broadcast Router - Template Management

Handles CRUD operations for broadcast templates.
"""

from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status

from api.security.internal_rbac import (
    InternalUserContext,
    require_session,
    require_permission,
)

from ..schemas import (
    CreateBroadcastTemplateRequest,
    UpdateBroadcastTemplateRequest,
    BroadcastTemplateResponse,
    SubscriptionResponse,
    BroadcastAudience,
    ErrorResponse,
)
from ...security.rbac import PERMISSION_BROADCAST_OPS, PERMISSION_BROADCAST_DRIVER
from ...observability.tracing import get_logger

router = APIRouter(prefix="/broadcast", tags=["ops-copilot-broadcast"])
logger = get_logger("broadcast")


# =============================================================================
# Templates
# =============================================================================


@router.get(
    "/templates",
    response_model=List[BroadcastTemplateResponse],
    summary="List broadcast templates",
    description="List available broadcast templates.",
)
async def list_templates(
    request: Request,
    audience: Optional[BroadcastAudience] = None,
    include_system: bool = Query(True, description="Include system templates"),
    user: InternalUserContext = Depends(require_session),
):
    """List broadcast templates."""
    tenant_id = user.tenant_id or user.active_tenant_id

    templates = await _list_templates(
        request,
        tenant_id=tenant_id,
        audience=audience,
        include_system=include_system,
    )
    return templates


@router.post(
    "/templates",
    response_model=BroadcastTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create broadcast template",
    description="Create a new broadcast template.",
)
async def create_template(
    request: Request,
    body: CreateBroadcastTemplateRequest,
    user: InternalUserContext = Depends(require_permission(PERMISSION_BROADCAST_OPS)),
):
    """Create a broadcast template."""
    tenant_id = user.tenant_id or user.active_tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required",
        )

    # Validate DRIVER templates require WhatsApp template info
    if body.audience == BroadcastAudience.DRIVER:
        if not body.wa_template_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="DRIVER templates require wa_template_name",
            )
        # Check permission for driver broadcasts
        if not user.is_platform_admin and PERMISSION_BROADCAST_DRIVER not in user.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission required: ops_copilot.broadcast.driver",
            )

    template = await _create_template(
        request,
        tenant_id=tenant_id,
        template_key=body.template_key,
        audience=body.audience,
        body_template=body.body_template,
        expected_params=body.expected_params,
        wa_template_name=body.wa_template_name,
        wa_template_namespace=body.wa_template_namespace,
        wa_template_language=body.wa_template_language,
    )

    logger.info(
        "template_created",
        template_id=template["id"],
        template_key=body.template_key,
        audience=body.audience.value,
    )

    return BroadcastTemplateResponse(**template)


@router.get(
    "/templates/{template_id}",
    response_model=BroadcastTemplateResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Template not found"},
    },
    summary="Get template",
    description="Get template details by ID.",
)
async def get_template(
    request: Request,
    template_id: str,
    user: InternalUserContext = Depends(require_session),
):
    """Get template by ID."""
    template = await _get_template(request, template_id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    # Check access (system templates or own tenant)
    tenant_id = user.tenant_id or user.active_tenant_id
    if template["tenant_id"] is not None and not user.is_platform_admin:
        if template["tenant_id"] != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found",
            )

    return BroadcastTemplateResponse(**template)


@router.patch(
    "/templates/{template_id}",
    response_model=BroadcastTemplateResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Template not found"},
    },
    summary="Update template",
    description="Update a broadcast template.",
)
async def update_template(
    request: Request,
    template_id: str,
    body: UpdateBroadcastTemplateRequest,
    user: InternalUserContext = Depends(require_permission(PERMISSION_BROADCAST_OPS)),
):
    """Update a template."""
    template = await _get_template(request, template_id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    # Check access
    tenant_id = user.tenant_id or user.active_tenant_id
    if template["tenant_id"] is not None and not user.is_platform_admin:
        if template["tenant_id"] != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found",
            )

    # Cannot update system templates unless platform admin
    if template["tenant_id"] is None and not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify system templates",
        )

    updated = await _update_template(
        request,
        template_id=template_id,
        body_template=body.body_template,
        expected_params=body.expected_params,
        is_active=body.is_active,
        is_deprecated=body.is_deprecated,
    )

    logger.info(
        "template_updated",
        template_id=template_id,
    )

    return BroadcastTemplateResponse(**updated)


@router.delete(
    "/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse, "description": "Template not found"},
    },
    summary="Deprecate template",
    description="Mark a template as deprecated (soft delete).",
)
async def deprecate_template(
    request: Request,
    template_id: str,
    user: InternalUserContext = Depends(require_permission(PERMISSION_BROADCAST_OPS)),
):
    """Deprecate a template."""
    template = await _get_template(request, template_id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found",
        )

    # Check access
    tenant_id = user.tenant_id or user.active_tenant_id
    if template["tenant_id"] is not None and not user.is_platform_admin:
        if template["tenant_id"] != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Template not found",
            )

    await _deprecate_template(request, template_id)

    logger.info(
        "template_deprecated",
        template_id=template_id,
    )


# =============================================================================
# Subscriptions
# =============================================================================


@router.get(
    "/subscriptions",
    response_model=List[SubscriptionResponse],
    summary="List subscriptions",
    description="List driver broadcast subscriptions.",
)
async def list_subscriptions(
    request: Request,
    driver_id: Optional[str] = None,
    is_subscribed: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: InternalUserContext = Depends(require_permission(PERMISSION_BROADCAST_DRIVER)),
):
    """List broadcast subscriptions."""
    tenant_id = user.tenant_id or user.active_tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required",
        )

    subscriptions = await _list_subscriptions(
        request,
        tenant_id=tenant_id,
        driver_id=driver_id,
        is_subscribed=is_subscribed,
        limit=limit,
        offset=offset,
    )
    return subscriptions


# =============================================================================
# Helper Functions
# =============================================================================


async def _list_templates(
    request: Request,
    tenant_id: Optional[int],
    audience: Optional[BroadcastAudience] = None,
    include_system: bool = True,
) -> List[BroadcastTemplateResponse]:
    """List templates for a tenant."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            conditions = ["is_active = TRUE"]
            params = []

            if include_system and tenant_id:
                conditions.append("(tenant_id = %s OR tenant_id IS NULL)")
                params.append(tenant_id)
            elif tenant_id:
                conditions.append("tenant_id = %s")
                params.append(tenant_id)
            else:
                conditions.append("tenant_id IS NULL")

            if audience:
                conditions.append("audience = %s")
                params.append(audience.value)

            query = f"""
                SELECT id, tenant_id, template_key, audience, body_template,
                       expected_params, wa_template_name, is_approved, approval_status,
                       is_active, is_deprecated, created_at, updated_at
                FROM ops.broadcast_templates
                WHERE {' AND '.join(conditions)}
                ORDER BY tenant_id NULLS FIRST, template_key
            """

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                BroadcastTemplateResponse(
                    id=str(row[0]),
                    tenant_id=row[1],
                    template_key=row[2],
                    audience=BroadcastAudience(row[3]),
                    body_template=row[4],
                    expected_params=row[5] or [],
                    wa_template_name=row[6],
                    is_approved=row[7],
                    approval_status=row[8],
                    is_active=row[9],
                    is_deprecated=row[10],
                    created_at=row[11],
                    updated_at=row[12],
                )
                for row in rows
            ]
    except Exception as e:
        logger.warning("list_templates_failed", error=str(e))
        return []


async def _get_template(request: Request, template_id: str) -> Optional[dict]:
    """Get template by ID."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, template_key, audience, body_template,
                       expected_params, wa_template_name, wa_template_namespace,
                       wa_template_language, allowed_placeholders,
                       is_approved, approval_status, approved_at,
                       is_active, is_deprecated, created_at, updated_at
                FROM ops.broadcast_templates
                WHERE id = %s::uuid
                """,
                (template_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "tenant_id": row[1],
                    "template_key": row[2],
                    "audience": BroadcastAudience(row[3]),
                    "body_template": row[4],
                    "expected_params": row[5] or [],
                    "wa_template_name": row[6],
                    "wa_template_namespace": row[7],
                    "wa_template_language": row[8],
                    "allowed_placeholders": row[9] or [],
                    "is_approved": row[10],
                    "approval_status": row[11],
                    "approved_at": row[12],
                    "is_active": row[13],
                    "is_deprecated": row[14],
                    "created_at": row[15],
                    "updated_at": row[16],
                }
            return None
    except Exception as e:
        logger.warning("get_template_failed", error=str(e))
        return None


async def _create_template(
    request: Request,
    tenant_id: int,
    template_key: str,
    audience: BroadcastAudience,
    body_template: str,
    expected_params: List[str],
    wa_template_name: Optional[str] = None,
    wa_template_namespace: Optional[str] = None,
    wa_template_language: str = "de",
) -> dict:
    """Create a template."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    try:
        with conn.cursor() as cur:
            template_id = str(uuid4())

            # DRIVER templates start as not approved
            is_approved = audience == BroadcastAudience.OPS

            cur.execute(
                """
                INSERT INTO ops.broadcast_templates (
                    id, tenant_id, template_key, audience, body_template,
                    expected_params, wa_template_name, wa_template_namespace,
                    wa_template_language, is_approved, approval_status
                ) VALUES (
                    %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING created_at, updated_at
                """,
                (
                    template_id,
                    tenant_id,
                    template_key,
                    audience.value,
                    body_template,
                    expected_params,
                    wa_template_name,
                    wa_template_namespace,
                    wa_template_language,
                    is_approved,
                    "PENDING" if audience == BroadcastAudience.DRIVER else None,
                ),
            )
            row = cur.fetchone()
            conn.commit()

            return {
                "id": template_id,
                "tenant_id": tenant_id,
                "template_key": template_key,
                "audience": audience,
                "body_template": body_template,
                "expected_params": expected_params,
                "wa_template_name": wa_template_name,
                "is_approved": is_approved,
                "approval_status": "PENDING" if audience == BroadcastAudience.DRIVER else None,
                "is_active": True,
                "is_deprecated": False,
                "created_at": row[0],
                "updated_at": row[1],
            }
    except Exception as e:
        logger.exception("create_template_failed", error=str(e))
        conn.rollback()
        if "duplicate key" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Template with key '{template_key}' already exists",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create template",
        )


async def _update_template(
    request: Request,
    template_id: str,
    body_template: Optional[str] = None,
    expected_params: Optional[List[str]] = None,
    is_active: Optional[bool] = None,
    is_deprecated: Optional[bool] = None,
) -> dict:
    """Update a template."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    try:
        with conn.cursor() as cur:
            updates = ["updated_at = NOW()"]
            params = []

            if body_template is not None:
                updates.append("body_template = %s")
                params.append(body_template)

            if expected_params is not None:
                updates.append("expected_params = %s")
                params.append(expected_params)

            if is_active is not None:
                updates.append("is_active = %s")
                params.append(is_active)

            if is_deprecated is not None:
                updates.append("is_deprecated = %s")
                params.append(is_deprecated)

            params.append(template_id)

            cur.execute(
                f"""
                UPDATE ops.broadcast_templates
                SET {', '.join(updates)}
                WHERE id = %s::uuid
                RETURNING id, tenant_id, template_key, audience, body_template,
                          expected_params, wa_template_name, is_approved, approval_status,
                          is_active, is_deprecated, created_at, updated_at
                """,
                params,
            )
            row = cur.fetchone()
            conn.commit()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Template not found",
                )

            return {
                "id": str(row[0]),
                "tenant_id": row[1],
                "template_key": row[2],
                "audience": BroadcastAudience(row[3]),
                "body_template": row[4],
                "expected_params": row[5] or [],
                "wa_template_name": row[6],
                "is_approved": row[7],
                "approval_status": row[8],
                "is_active": row[9],
                "is_deprecated": row[10],
                "created_at": row[11],
                "updated_at": row[12],
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_template_failed", error=str(e))
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update template",
        )


async def _deprecate_template(request: Request, template_id: str) -> None:
    """Deprecate a template."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.broadcast_templates
                SET is_deprecated = TRUE, is_active = FALSE, updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (template_id,),
            )
            conn.commit()
    except Exception as e:
        logger.exception("deprecate_template_failed", error=str(e))
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deprecate template",
        )


async def _list_subscriptions(
    request: Request,
    tenant_id: int,
    driver_id: Optional[str] = None,
    is_subscribed: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[SubscriptionResponse]:
    """List subscriptions for a tenant."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            conditions = ["tenant_id = %s"]
            params = [tenant_id]

            if driver_id:
                conditions.append("driver_id = %s")
                params.append(driver_id)

            if is_subscribed is not None:
                conditions.append("is_subscribed = %s")
                params.append(is_subscribed)

            params.extend([limit, offset])

            query = f"""
                SELECT id, tenant_id, driver_id, wa_user_id, is_subscribed,
                       consent_given_at, consent_source, unsubscribed_at
                FROM ops.broadcast_subscriptions
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                SubscriptionResponse(
                    id=str(row[0]),
                    tenant_id=row[1],
                    driver_id=row[2],
                    wa_user_id=row[3],
                    is_subscribed=row[4],
                    consent_given_at=row[5],
                    consent_source=row[6],
                    unsubscribed_at=row[7],
                )
                for row in rows
            ]
    except Exception as e:
        logger.warning("list_subscriptions_failed", error=str(e))
        return []
