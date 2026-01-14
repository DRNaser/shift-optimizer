"""
Drafts Router - 2-Phase Commit Management

Handles confirmation and cancellation of pending write actions.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.security.internal_rbac import (
    InternalUserContext,
    require_session,
)

from ..schemas import (
    ConfirmDraftRequest,
    DraftResponse,
    DraftStatus,
    ActionType,
    ErrorResponse,
)
from ...security.rbac import ActionContext
from ...observability.metrics import record_write_action
from ...observability.tracing import get_logger, create_trace_context

router = APIRouter(prefix="/drafts", tags=["ops-copilot-drafts"])
logger = get_logger("drafts")


@router.get(
    "/{draft_id}",
    response_model=DraftResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Draft not found"},
    },
    summary="Get draft status",
    description="Get the current status of a draft.",
)
async def get_draft(
    request: Request,
    draft_id: str,
    user: InternalUserContext = Depends(require_session),
):
    """Get draft by ID."""
    draft = await _get_draft(request, draft_id)

    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found",
        )

    # Check tenant access
    if not user.is_platform_admin:
        if draft["tenant_id"] != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft not found",
            )

    return DraftResponse(
        draft_id=draft["id"],
        status=DraftStatus(draft["status"]),
        action_type=ActionType(draft["action_type"]),
        preview_text=draft["preview_text"],
        expires_at=draft["expires_at"],
        commit_result=draft.get("commit_result"),
        commit_error=draft.get("commit_error"),
    )


@router.post(
    "/{draft_id}/confirm",
    response_model=DraftResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid draft state"},
        403: {"model": ErrorResponse, "description": "Permission denied"},
        404: {"model": ErrorResponse, "description": "Draft not found"},
        410: {"model": ErrorResponse, "description": "Draft expired"},
    },
    summary="Confirm or cancel a pending draft",
    description="""
    2-phase commit: User confirms or cancels a prepared write action.

    Called when user sends "CONFIRM" or "CANCEL" in WhatsApp chat.

    **Rules:**
    - Only drafts in PENDING_CONFIRM status can be confirmed/cancelled
    - User must have permission for the action type
    - Approver roles (tenant_admin, operator_admin) can confirm any draft
    - Regular users can only confirm their own drafts
    """,
)
async def confirm_draft(
    request: Request,
    draft_id: str,
    body: ConfirmDraftRequest,
    user: InternalUserContext = Depends(require_session),
):
    """Confirm or cancel a draft."""
    ctx = create_trace_context(
        tenant_id=user.tenant_id or user.active_tenant_id,
    )

    # Get draft
    draft = await _get_draft(request, draft_id)

    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found",
        )

    # Check tenant access
    if not user.is_platform_admin:
        if draft["tenant_id"] != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Draft not found",
            )

    # =========================================================
    # RBAC CHECK FIRST - before revealing draft status
    # This prevents unauthorized users from probing draft states
    # =========================================================
    action_ctx = ActionContext.from_user_context(user)
    can_commit, reason = action_ctx.can_commit(
        draft["identity_user_id"],  # Created by
        draft["action_type"],
    )

    if not can_commit:
        logger.warning(
            "draft_confirm_denied",
            draft_id=draft_id,
            user_id=str(user.user_id),
            reason=reason,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {reason}",
        )

    # =========================================================
    # NOW check draft status (only after RBAC passes)
    # =========================================================
    if draft["status"] != "PENDING_CONFIRM":
        if draft["status"] == "EXPIRED":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Draft has expired",
            )
        elif draft["status"] == "COMMITTED":
            # Idempotent response for authorized user
            return DraftResponse(
                draft_id=draft["id"],
                status=DraftStatus(draft["status"]),
                action_type=ActionType(draft["action_type"]),
                preview_text=draft["preview_text"],
                expires_at=draft["expires_at"],
                commit_result=draft.get("commit_result"),
                commit_error=draft.get("commit_error"),
            )
        elif draft["status"] == "CANCELLED":
            # Cannot confirm cancelled draft
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Draft was cancelled",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Draft is in {draft['status']} status",
            )

    # Check expiry
    if draft["expires_at"] < datetime.now(timezone.utc):
        await _expire_draft(request, draft_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Draft has expired",
        )

    # Process confirmation or cancellation
    if body.confirmed:
        # Execute the action
        result = await _commit_draft(request, draft_id, draft)
        record_write_action(draft["tenant_id"], draft["action_type"], "committed")

        logger.info(
            "draft_committed",
            draft_id=draft_id,
            action_type=draft["action_type"],
            committed_by=str(user.user_id),
        )

        return DraftResponse(
            draft_id=draft["id"],
            status=DraftStatus.COMMITTED,
            action_type=ActionType(draft["action_type"]),
            preview_text=draft["preview_text"],
            expires_at=draft["expires_at"],
            commit_result=result,
        )
    else:
        # Cancel the draft
        await _cancel_draft(request, draft_id)
        record_write_action(draft["tenant_id"], draft["action_type"], "cancelled")

        logger.info(
            "draft_cancelled",
            draft_id=draft_id,
            action_type=draft["action_type"],
            cancelled_by=str(user.user_id),
        )

        return DraftResponse(
            draft_id=draft["id"],
            status=DraftStatus.CANCELLED,
            action_type=ActionType(draft["action_type"]),
            preview_text=draft["preview_text"],
            expires_at=draft["expires_at"],
        )


@router.get(
    "",
    response_model=list[DraftResponse],
    summary="List pending drafts",
    description="List all pending drafts for the current thread/user.",
)
async def list_drafts(
    request: Request,
    thread_id: Optional[str] = None,
    status_filter: Optional[DraftStatus] = None,
    user: InternalUserContext = Depends(require_session),
):
    """List drafts for current tenant."""
    tenant_id = user.tenant_id or user.active_tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required",
        )

    drafts = await _list_drafts(request, tenant_id, thread_id, status_filter)
    return [
        DraftResponse(
            draft_id=d["id"],
            status=DraftStatus(d["status"]),
            action_type=ActionType(d["action_type"]),
            preview_text=d["preview_text"],
            expires_at=d["expires_at"],
            commit_result=d.get("commit_result"),
            commit_error=d.get("commit_error"),
        )
        for d in drafts
    ]


# =============================================================================
# Helper Functions
# =============================================================================


async def _get_draft(request: Request, draft_id: str) -> Optional[dict]:
    """Get draft by ID."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.id, d.tenant_id, d.thread_id, d.identity_id,
                    d.action_type, d.payload, d.preview_text, d.status,
                    d.expires_at, d.confirmed_at, d.committed_at,
                    d.commit_result, d.commit_error,
                    i.user_id as identity_user_id
                FROM ops.drafts d
                JOIN ops.whatsapp_identities i ON i.id = d.identity_id
                WHERE d.id = %s::uuid
                """,
                (draft_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "tenant_id": row[1],
                    "thread_id": row[2],
                    "identity_id": str(row[3]),
                    "action_type": row[4],
                    "payload": row[5],
                    "preview_text": row[6],
                    "status": row[7],
                    "expires_at": row[8],
                    "confirmed_at": row[9],
                    "committed_at": row[10],
                    "commit_result": row[11],
                    "commit_error": row[12],
                    "identity_user_id": str(row[13]),
                }
            return None
    except Exception as e:
        logger.warning("draft_lookup_failed", error=str(e))
        return None


async def _expire_draft(request: Request, draft_id: str) -> None:
    """Mark draft as expired."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.drafts
                SET status = 'EXPIRED', updated_at = NOW()
                WHERE id = %s::uuid AND status = 'PENDING_CONFIRM'
                """,
                (draft_id,),
            )
            conn.commit()
    except Exception as e:
        logger.warning("expire_draft_failed", error=str(e))
        conn.rollback()


async def _cancel_draft(request: Request, draft_id: str) -> None:
    """Mark draft as cancelled."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ops.drafts
                SET status = 'CANCELLED', updated_at = NOW()
                WHERE id = %s::uuid AND status = 'PENDING_CONFIRM'
                """,
                (draft_id,),
            )
            conn.commit()

            # Record event
            cur.execute(
                """
                INSERT INTO ops.events (tenant_id, thread_id, event_type, payload)
                SELECT tenant_id, thread_id, 'DRAFT_CANCELLED', jsonb_build_object('draft_id', %s)
                FROM ops.drafts WHERE id = %s::uuid
                """,
                (draft_id, draft_id),
            )
            conn.commit()
    except Exception as e:
        logger.warning("cancel_draft_failed", error=str(e))
        conn.rollback()


async def _commit_draft(request: Request, draft_id: str, draft: dict) -> dict:
    """
    Execute the draft action with atomic status guard.

    SECURITY INVARIANT:
        The UPDATE uses WHERE status='PENDING_CONFIRM' to ensure:
        - Only one concurrent request can execute the action
        - Race conditions result in idempotent response, not double execution
    """
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    action_type = draft["action_type"]
    payload = draft["payload"]

    try:
        with conn.cursor() as cur:
            # =========================================================
            # ATOMIC STATUS GUARD - claim the draft before executing
            # This prevents race conditions where two requests both
            # pass RBAC and status checks, then both execute
            # =========================================================
            cur.execute(
                """
                UPDATE ops.drafts
                SET status = 'COMMITTING', updated_at = NOW()
                WHERE id = %s::uuid AND status = 'PENDING_CONFIRM'
                RETURNING id, commit_result
                """,
                (draft_id,),
            )
            claimed = cur.fetchone()

            if not claimed:
                # Race condition: another request got here first
                # Check if already committed (idempotent case)
                cur.execute(
                    "SELECT status, commit_result FROM ops.drafts WHERE id = %s::uuid",
                    (draft_id,),
                )
                existing = cur.fetchone()
                if existing and existing[0] == "COMMITTED" and existing[1]:
                    # Already committed - return cached result
                    return existing[1]
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Draft state changed during commit",
                )

            # =========================================================
            # Execute action (only if we claimed the draft)
            # =========================================================
            if action_type == "CREATE_TICKET":
                result = await _execute_create_ticket(cur, draft, payload)
            elif action_type == "AUDIT_COMMENT":
                result = await _execute_audit_comment(cur, draft, payload)
            elif action_type == "WHATSAPP_BROADCAST_OPS":
                result = await _execute_broadcast_ops(cur, draft, payload)
            elif action_type == "WHATSAPP_BROADCAST_DRIVER":
                result = await _execute_broadcast_driver(cur, draft, payload)
            else:
                raise ValueError(f"Unknown action type: {action_type}")

            # =========================================================
            # Finalize commit - mark as COMMITTED with result
            # =========================================================
            cur.execute(
                """
                UPDATE ops.drafts
                SET status = 'COMMITTED',
                    confirmed_at = NOW(),
                    committed_at = NOW(),
                    commit_result = %s,
                    updated_at = NOW()
                WHERE id = %s::uuid AND status = 'COMMITTING'
                RETURNING id
                """,
                (result, draft_id),
            )
            finalized = cur.fetchone()

            if not finalized:
                # Should not happen - we had the lock
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Draft commit finalization failed",
                )

            # Record event (only once - we confirmed we did the commit)
            cur.execute(
                """
                INSERT INTO ops.events (tenant_id, thread_id, event_type, payload)
                VALUES (%s, %s, 'DRAFT_COMMITTED', %s)
                """,
                (
                    draft["tenant_id"],
                    draft["thread_id"],
                    {"draft_id": draft_id, "action_type": action_type, "result": result},
                ),
            )

            conn.commit()
            return result

    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.exception("commit_draft_failed", draft_id=draft_id, error=str(e))

        # Update draft with error (revert from COMMITTING if needed)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ops.drafts
                    SET status = 'PENDING_CONFIRM',
                        commit_error = %s,
                        updated_at = NOW()
                    WHERE id = %s::uuid AND status = 'COMMITTING'
                    """,
                    (str(e), draft_id),
                )
                conn.commit()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to commit action: {str(e)}",
        )


async def _execute_create_ticket(cur, draft: dict, payload: dict) -> dict:
    """Execute CREATE_TICKET action."""
    from uuid import uuid4

    ticket_id = str(uuid4())
    cur.execute(
        """
        INSERT INTO ops.tickets (
            id, tenant_id, site_id, category, priority, title, description,
            status, assigned_to, driver_id, tour_id, source, source_thread_id,
            source_draft_id, created_by
        ) VALUES (
            %s::uuid, %s, %s, %s, %s, %s, %s,
            'OPEN', %s::uuid, %s, %s, 'COPILOT', %s, %s::uuid, %s::uuid
        )
        RETURNING ticket_number
        """,
        (
            ticket_id,
            draft["tenant_id"],
            payload.get("site_id"),
            payload["category"],
            payload.get("priority", "MEDIUM"),
            payload["title"],
            payload["description"],
            payload.get("assigned_to"),
            payload.get("driver_id"),
            payload.get("tour_id"),
            draft["thread_id"],
            draft["id"],
            draft["identity_user_id"],
        ),
    )
    ticket_number = cur.fetchone()[0]

    # Add initial comment if provided
    if payload.get("initial_comment"):
        cur.execute(
            """
            INSERT INTO ops.ticket_comments (
                ticket_id, tenant_id, comment_type, content,
                source, source_thread_id, created_by
            ) VALUES (%s::uuid, %s, 'NOTE', %s, 'COPILOT', %s, %s::uuid)
            """,
            (
                ticket_id,
                draft["tenant_id"],
                payload["initial_comment"],
                draft["thread_id"],
                draft["identity_user_id"],
            ),
        )

    return {
        "ticket_id": ticket_id,
        "ticket_number": ticket_number,
    }


async def _execute_audit_comment(cur, draft: dict, payload: dict) -> dict:
    """Execute AUDIT_COMMENT action."""
    cur.execute(
        """
        INSERT INTO auth.audit_log (
            event_type, user_id, tenant_id, details
        ) VALUES ('OPS_COPILOT_COMMENT', %s::uuid, %s, %s)
        RETURNING id
        """,
        (
            draft["identity_user_id"],
            draft["tenant_id"],
            {
                "comment": payload["comment"],
                "thread_id": draft["thread_id"],
                "reference_type": payload.get("reference_type"),
                "reference_id": payload.get("reference_id"),
            },
        ),
    )
    audit_id = cur.fetchone()[0]
    return {"audit_log_id": audit_id}


async def _execute_broadcast_ops(cur, draft: dict, payload: dict) -> dict:
    """Execute WHATSAPP_BROADCAST_OPS action (stub - enqueue only)."""
    # Stub implementation - just record the intent
    cur.execute(
        """
        INSERT INTO ops.events (tenant_id, thread_id, event_type, payload)
        VALUES (%s, %s, 'BROADCAST_ENQUEUED', %s)
        RETURNING event_id
        """,
        (
            draft["tenant_id"],
            draft["thread_id"],
            {
                "audience": "OPS",
                "message": payload["message"],
                "recipient_count": len(payload.get("recipient_ids", [])),
            },
        ),
    )
    event_id = str(cur.fetchone()[0])
    return {
        "broadcast_enqueued": True,
        "event_id": event_id,
        "note": "Actual WhatsApp sending not implemented in MVP",
    }


async def _execute_broadcast_driver(cur, draft: dict, payload: dict) -> dict:
    """
    Execute WHATSAPP_BROADCAST_DRIVER action with STRICT validation.

    Server-side enforcement (critical security):
    1. Template REQUIRED (free text forbidden for drivers)
    2. Template must be approved and audience=DRIVER
    3. Placeholders must be in allowed_placeholders
    4. All recipients must be opted-in
    5. Idempotency enforced via draft_id
    """
    tenant_id = draft["tenant_id"]
    thread_id = draft["thread_id"]

    # === VALIDATION 1: Template required (no free text for drivers) ===
    template_key = payload.get("template_key")
    if not template_key:
        raise ValueError("Driver broadcasts require a template (free text forbidden)")

    # === VALIDATION 2: Template exists, approved, audience=DRIVER ===
    cur.execute(
        """
        SELECT id, body_template, expected_params, allowed_placeholders,
               wa_template_name, is_approved, audience
        FROM ops.broadcast_templates
        WHERE template_key = %s
          AND (tenant_id = %s OR tenant_id IS NULL)
          AND is_active = TRUE
          AND is_deprecated = FALSE
        ORDER BY tenant_id NULLS LAST
        LIMIT 1
        """,
        (template_key, tenant_id),
    )
    template = cur.fetchone()

    if not template:
        raise ValueError(f"Template '{template_key}' not found or inactive")

    template_id, body_template, expected_params, allowed_placeholders, \
        wa_template_name, is_approved, audience = template

    if audience != "DRIVER":
        raise ValueError(f"Template audience is '{audience}', expected 'DRIVER'")

    if not is_approved:
        raise ValueError("Template is not approved by Meta")

    if not wa_template_name:
        raise ValueError("Template missing WhatsApp template name")

    # === VALIDATION 3: Placeholder allowlist ===
    params = payload.get("params", {})
    expected_params = expected_params or []
    allowed_placeholders = allowed_placeholders or expected_params

    # Check required params present
    missing_params = set(expected_params) - set(params.keys())
    if missing_params:
        raise ValueError(f"Missing required parameters: {', '.join(missing_params)}")

    # Check no illegal params (strict allowlist)
    if allowed_placeholders:
        illegal_params = set(params.keys()) - set(allowed_placeholders)
        if illegal_params:
            raise ValueError(f"Illegal parameters: {', '.join(illegal_params)}")

    # === VALIDATION 4: All recipients must be opted-in ===
    driver_ids = payload.get("driver_ids", [])
    if not driver_ids:
        raise ValueError("No driver recipients specified")

    cur.execute(
        """
        SELECT driver_id, is_subscribed
        FROM ops.broadcast_subscriptions
        WHERE tenant_id = %s
          AND driver_id = ANY(%s)
        """,
        (tenant_id, driver_ids),
    )
    subscriptions = {row[0]: row[1] for row in cur.fetchall()}

    not_found = [d for d in driver_ids if d not in subscriptions]
    opted_out = [d for d in driver_ids if d in subscriptions and not subscriptions[d]]

    if not_found:
        raise ValueError(f"Drivers not found in subscriptions: {len(not_found)} drivers")
    if opted_out:
        raise ValueError(f"Drivers not opted-in: {len(opted_out)} drivers")

    # All validation passed - enqueue the broadcast
    cur.execute(
        """
        INSERT INTO ops.events (tenant_id, thread_id, event_type, payload)
        VALUES (%s, %s, 'BROADCAST_ENQUEUED', %s)
        RETURNING event_id
        """,
        (
            tenant_id,
            thread_id,
            {
                "audience": "DRIVER",
                "template_id": str(template_id),
                "template_key": template_key,
                "wa_template_name": wa_template_name,
                "params": params,
                "driver_ids": driver_ids,
                "recipient_count": len(driver_ids),
                "draft_id": draft["id"],  # For idempotency tracking
            },
        ),
    )
    event_id = str(cur.fetchone()[0])

    logger.info(
        "driver_broadcast_enqueued",
        event_id=event_id,
        template_key=template_key,
        recipient_count=len(driver_ids),
    )

    return {
        "broadcast_enqueued": True,
        "event_id": event_id,
        "template_key": template_key,
        "recipient_count": len(driver_ids),
        "note": "Actual WhatsApp sending not implemented in MVP",
    }


async def _list_drafts(
    request: Request,
    tenant_id: int,
    thread_id: Optional[str],
    status_filter: Optional[DraftStatus],
) -> list[dict]:
    """List drafts for a tenant."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, tenant_id, thread_id, action_type, preview_text,
                       status, expires_at, commit_result, commit_error
                FROM ops.drafts
                WHERE tenant_id = %s
            """
            params = [tenant_id]

            if thread_id:
                query += " AND thread_id = %s"
                params.append(thread_id)

            if status_filter:
                query += " AND status = %s"
                params.append(status_filter.value)

            query += " ORDER BY created_at DESC LIMIT 50"

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                {
                    "id": str(row[0]),
                    "tenant_id": row[1],
                    "thread_id": row[2],
                    "action_type": row[3],
                    "preview_text": row[4],
                    "status": row[5],
                    "expires_at": row[6],
                    "commit_result": row[7],
                    "commit_error": row[8],
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning("list_drafts_failed", error=str(e))
        return []


# =============================================================================
# Test-Compatible Helper Functions (for unit testing)
# =============================================================================


async def _create_draft(
    conn,
    tenant_id: int,
    thread_id: str,
    action_type: str,
    payload: dict,
    created_by: str,
    expires_minutes: int = 5,
) -> str:
    """
    Create a draft for 2-phase commit (test-compatible).

    Args:
        conn: Database connection
        tenant_id: Tenant ID
        thread_id: Thread ID
        action_type: Action type (CREATE_TICKET, AUDIT_COMMENT, etc.)
        payload: Action payload
        created_by: User ID who created the draft
        expires_minutes: Minutes until draft expires

    Returns:
        Draft ID
    """
    from uuid import uuid4

    draft_id = str(uuid4())
    preview_text = _generate_preview_text(action_type, payload)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.drafts (
                    id, tenant_id, thread_id, identity_id, action_type,
                    payload, preview_text, status, expires_at, created_by
                )
                SELECT
                    %s::uuid, %s, %s,
                    (SELECT id FROM ops.whatsapp_identities WHERE user_id = %s::uuid LIMIT 1),
                    %s, %s, %s, 'PENDING_CONFIRM',
                    NOW() + INTERVAL '%s minutes', %s::uuid
                RETURNING id
                """,
                (
                    draft_id,
                    tenant_id,
                    thread_id,
                    created_by,
                    action_type,
                    payload,
                    preview_text,
                    expires_minutes,
                    created_by,
                ),
            )
            result = cur.fetchone()
            conn.commit()
            return str(result[0]) if result else draft_id
    except Exception as e:
        conn.rollback()
        logger.warning("create_draft_failed", error=str(e))
        raise


async def _confirm_draft(
    conn,
    draft_id: str,
    user_id: str,
    user_permissions: list,
    role_name: str,
) -> dict:
    """
    Confirm a draft (test-compatible).

    Args:
        conn: Database connection
        draft_id: Draft ID
        user_id: User ID confirming
        user_permissions: List of user permissions
        role_name: User's role name

    Returns:
        Result dict with success status

    SECURITY INVARIANTS:
        1. RBAC checked BEFORE revealing draft status (no info leak)
        2. Atomic UPDATE with WHERE status='PENDING_CONFIRM' prevents double execution
        3. Only authorized users get idempotent success; others get 403
    """
    from datetime import datetime, timezone
    from ...security.rbac import can_commit_draft

    try:
        with conn.cursor() as cur:
            # Get draft with commit_result for idempotent response
            cur.execute(
                """
                SELECT tenant_id, thread_id, action_type, payload, status,
                       created_by, expires_at, commit_result
                FROM ops.drafts
                WHERE id = %s::uuid
                """,
                (draft_id,),
            )
            row = cur.fetchone()

            if not row:
                return {"success": False, "error": "Draft not found"}

            tenant_id, thread_id, action_type, payload, status, created_by, expires_at, commit_result = row

            # =========================================================
            # RBAC CHECK FIRST - before revealing any status information
            # This prevents unauthorized users from probing draft states
            # =========================================================
            allowed, reason = can_commit_draft(
                user_id=user_id,
                user_permissions=user_permissions,
                role_name=role_name,
                draft_created_by=str(created_by),
                action_type=action_type,
            )

            if not allowed:
                return {"success": False, "error": f"Permission denied: {reason}"}

            # =========================================================
            # NOW check status (only after RBAC passes)
            # =========================================================
            if status == "COMMITTED":
                # Already committed - return cached result (idempotent)
                return {
                    "success": True,
                    "idempotent": True,
                    "result_id": commit_result.get("result_id") if commit_result else None,
                }

            if status == "CONFIRMED":
                # Legacy status - treat as committed
                return {"success": True, "idempotent": True}

            if status == "CANCELLED":
                # Cannot confirm cancelled draft
                return {"success": False, "error": "Draft was cancelled"}

            if status != "PENDING_CONFIRM":
                return {"success": False, "error": f"Draft is in {status} status"}

            # Check expiry
            if expires_at < datetime.now(timezone.utc):
                return {"success": False, "error": "Draft has expired"}

            # Execute action (simplified for testing)
            from uuid import uuid4
            result_id = str(uuid4())

            # =========================================================
            # ATOMIC UPDATE with status guard - prevents race conditions
            # Only one concurrent request can succeed; others get idempotent response
            # =========================================================
            cur.execute(
                """
                UPDATE ops.drafts
                SET status = 'COMMITTED', confirmed_at = NOW(), committed_at = NOW(),
                    commit_result = %s, updated_at = NOW()
                WHERE id = %s::uuid AND status = 'PENDING_CONFIRM'
                RETURNING id
                """,
                ({"result_id": result_id}, draft_id),
            )
            updated = cur.fetchone()

            if not updated:
                # Race condition: another request committed first
                # Re-fetch to return idempotent response
                cur.execute(
                    "SELECT commit_result FROM ops.drafts WHERE id = %s::uuid",
                    (draft_id,),
                )
                existing = cur.fetchone()
                if existing and existing[0]:
                    return {
                        "success": True,
                        "idempotent": True,
                        "result_id": existing[0].get("result_id"),
                    }
                return {"success": False, "error": "Draft state changed during commit"}

            # Record event (only if we actually committed)
            cur.execute(
                """
                INSERT INTO ops.events (tenant_id, thread_id, event_type, payload)
                VALUES (%s, %s, 'DRAFT_COMMITTED', %s)
                """,
                (tenant_id, thread_id, {"draft_id": draft_id}),
            )

            conn.commit()
            return {"success": True, "result_id": result_id}

    except Exception as e:
        conn.rollback()
        logger.warning("confirm_draft_failed", error=str(e))
        return {"success": False, "error": str(e)}


async def _cancel_draft_internal(
    conn,
    draft_id: str,
    user_id: str,
) -> dict:
    """
    Cancel a draft (test-compatible).

    Args:
        conn: Database connection
        draft_id: Draft ID
        user_id: User ID cancelling

    Returns:
        Result dict with success status
    """
    try:
        with conn.cursor() as cur:
            # Get draft
            cur.execute(
                """
                SELECT tenant_id, thread_id, action_type, status, created_by
                FROM ops.drafts
                WHERE id = %s::uuid
                """,
                (draft_id,),
            )
            row = cur.fetchone()

            if not row:
                return {"success": False, "error": "Draft not found"}

            tenant_id, thread_id, action_type, status, created_by = row

            # Check status
            if status == "CANCELLED":
                return {"success": True, "idempotent": True}

            if status in ("CONFIRMED", "COMMITTED"):
                return {"success": False, "error": "Draft already confirmed/committed"}

            # Check ownership (non-admin must be owner)
            if str(created_by) != user_id:
                return {"success": False, "error": "Only owner can cancel draft"}

            # Cancel draft
            cur.execute(
                """
                UPDATE ops.drafts
                SET status = 'CANCELLED', updated_at = NOW()
                WHERE id = %s::uuid AND status = 'PENDING_CONFIRM'
                RETURNING id
                """,
                (draft_id,),
            )
            result = cur.fetchone()

            if result:
                conn.commit()
                return {"success": True}
            else:
                return {"success": False, "error": "Failed to cancel draft"}

    except Exception as e:
        conn.rollback()
        logger.warning("cancel_draft_internal_failed", error=str(e))
        return {"success": False, "error": str(e)}


def _generate_preview_text(action_type: str, payload: dict) -> str:
    """Generate human-readable preview text for a draft."""
    if action_type == "CREATE_TICKET":
        return f"Create ticket: {payload.get('title', 'Untitled')}"
    elif action_type == "AUDIT_COMMENT":
        comment = payload.get("comment", "")
        return f"Add comment: {comment[:50]}..." if len(comment) > 50 else f"Add comment: {comment}"
    elif action_type == "WHATSAPP_BROADCAST_OPS":
        msg = payload.get("message", "")
        return f"Broadcast to ops: {msg[:50]}..." if len(msg) > 50 else f"Broadcast to ops: {msg}"
    elif action_type == "WHATSAPP_BROADCAST_DRIVER":
        return f"Send template: {payload.get('template_key', 'unknown')}"
    else:
        return f"Action: {action_type}"
