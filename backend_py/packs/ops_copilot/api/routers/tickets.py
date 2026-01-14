"""
Tickets Router - Internal Ticketing System

Handles CRUD operations for tickets created via Ops-Copilot.
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
    CreateTicketRequest,
    UpdateTicketRequest,
    AddTicketCommentRequest,
    TicketResponse,
    TicketCommentResponse,
    TicketStatus,
    TicketCategory,
    TicketPriority,
    ErrorResponse,
)
from ...security.rbac import PERMISSION_TICKETS_WRITE, PERMISSION_TICKETS_READ
from ...observability.tracing import get_logger

router = APIRouter(prefix="/tickets", tags=["ops-copilot-tickets"])
logger = get_logger("tickets")


@router.get(
    "",
    response_model=List[TicketResponse],
    summary="List tickets",
    description="List tickets with optional filtering.",
)
async def list_tickets(
    request: Request,
    status_filter: Optional[TicketStatus] = Query(None, alias="status"),
    category: Optional[TicketCategory] = None,
    priority: Optional[TicketPriority] = None,
    assigned_to: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: InternalUserContext = Depends(require_permission(PERMISSION_TICKETS_READ)),
):
    """List tickets for current tenant."""
    tenant_id = user.tenant_id or user.active_tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required",
        )

    tickets = await _list_tickets(
        request,
        tenant_id,
        status_filter=status_filter,
        category=category,
        priority=priority,
        assigned_to=assigned_to,
        limit=limit,
        offset=offset,
    )
    return tickets


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create ticket",
    description="Create a new ticket.",
)
async def create_ticket(
    request: Request,
    body: CreateTicketRequest,
    user: InternalUserContext = Depends(require_permission(PERMISSION_TICKETS_WRITE)),
):
    """Create a new ticket."""
    tenant_id = user.tenant_id or user.active_tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant context required",
        )

    ticket = await _create_ticket(
        request,
        tenant_id=tenant_id,
        site_id=body.site_id or user.site_id,
        category=body.category,
        priority=body.priority,
        title=body.title,
        description=body.description,
        assigned_to=body.assigned_to,
        driver_id=body.driver_id,
        tour_id=body.tour_id,
        created_by=str(user.user_id),
        source="MANUAL",
    )

    logger.info(
        "ticket_created",
        ticket_id=ticket["id"],
        ticket_number=ticket["ticket_number"],
        category=body.category.value,
    )

    return TicketResponse(**ticket)


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Ticket not found"},
    },
    summary="Get ticket",
    description="Get ticket details by ID.",
)
async def get_ticket(
    request: Request,
    ticket_id: str,
    user: InternalUserContext = Depends(require_permission(PERMISSION_TICKETS_READ)),
):
    """Get ticket by ID."""
    ticket = await _get_ticket(request, ticket_id)

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    # Check tenant access
    if not user.is_platform_admin:
        if ticket["tenant_id"] != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found",
            )

    return TicketResponse(**ticket)


@router.patch(
    "/{ticket_id}",
    response_model=TicketResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Ticket not found"},
    },
    summary="Update ticket",
    description="Update ticket status, priority, or assignment.",
)
async def update_ticket(
    request: Request,
    ticket_id: str,
    body: UpdateTicketRequest,
    user: InternalUserContext = Depends(require_permission(PERMISSION_TICKETS_WRITE)),
):
    """Update a ticket."""
    ticket = await _get_ticket(request, ticket_id)

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    # Check tenant access
    if not user.is_platform_admin:
        if ticket["tenant_id"] != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found",
            )

    updated = await _update_ticket(
        request,
        ticket_id,
        status=body.status,
        priority=body.priority,
        assigned_to=body.assigned_to,
        updated_by=str(user.user_id),
    )

    logger.info(
        "ticket_updated",
        ticket_id=ticket_id,
        changes={
            "status": body.status.value if body.status else None,
            "priority": body.priority.value if body.priority else None,
            "assigned_to": body.assigned_to,
        },
    )

    return TicketResponse(**updated)


@router.get(
    "/{ticket_id}/comments",
    response_model=List[TicketCommentResponse],
    responses={
        404: {"model": ErrorResponse, "description": "Ticket not found"},
    },
    summary="List ticket comments",
    description="List all comments on a ticket.",
)
async def list_ticket_comments(
    request: Request,
    ticket_id: str,
    user: InternalUserContext = Depends(require_permission(PERMISSION_TICKETS_READ)),
):
    """List comments on a ticket."""
    ticket = await _get_ticket(request, ticket_id)

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    # Check tenant access
    if not user.is_platform_admin:
        if ticket["tenant_id"] != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found",
            )

    comments = await _list_comments(request, ticket_id)
    return [TicketCommentResponse(**c) for c in comments]


@router.post(
    "/{ticket_id}/comments",
    response_model=TicketCommentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorResponse, "description": "Ticket not found"},
    },
    summary="Add ticket comment",
    description="Add a comment to a ticket.",
)
async def add_ticket_comment(
    request: Request,
    ticket_id: str,
    body: AddTicketCommentRequest,
    user: InternalUserContext = Depends(require_permission(PERMISSION_TICKETS_WRITE)),
):
    """Add a comment to a ticket."""
    ticket = await _get_ticket(request, ticket_id)

    if not ticket:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    # Check tenant access
    if not user.is_platform_admin:
        if ticket["tenant_id"] != user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found",
            )

    comment = await _add_comment(
        request,
        ticket_id=ticket_id,
        tenant_id=ticket["tenant_id"],
        content=body.content,
        created_by=str(user.user_id),
        source="MANUAL",
    )

    logger.info(
        "ticket_comment_added",
        ticket_id=ticket_id,
        comment_id=comment["id"],
    )

    return TicketCommentResponse(**comment)


# =============================================================================
# Helper Functions
# =============================================================================


async def _list_tickets(
    request: Request,
    tenant_id: int,
    status_filter: Optional[TicketStatus] = None,
    category: Optional[TicketCategory] = None,
    priority: Optional[TicketPriority] = None,
    assigned_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[dict]:
    """List tickets for a tenant."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            query = """
                SELECT id, ticket_number, tenant_id, site_id, category, priority,
                       title, description, status, assigned_to, driver_id,
                       source, created_by, created_at, updated_at, resolved_at
                FROM ops.tickets
                WHERE tenant_id = %s
            """
            params = [tenant_id]

            if status_filter:
                query += " AND status = %s"
                params.append(status_filter.value)

            if category:
                query += " AND category = %s"
                params.append(category.value)

            if priority:
                query += " AND priority = %s"
                params.append(priority.value)

            if assigned_to:
                query += " AND assigned_to = %s::uuid"
                params.append(assigned_to)

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            rows = cur.fetchall()

            return [
                {
                    "id": str(row[0]),
                    "ticket_number": row[1],
                    "tenant_id": row[2],
                    "site_id": row[3],
                    "category": TicketCategory(row[4]),
                    "priority": TicketPriority(row[5]),
                    "title": row[6],
                    "description": row[7],
                    "status": TicketStatus(row[8]),
                    "assigned_to": str(row[9]) if row[9] else None,
                    "driver_id": row[10],
                    "source": row[11],
                    "created_by": str(row[12]),
                    "created_at": row[13],
                    "updated_at": row[14],
                    "resolved_at": row[15],
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning("list_tickets_failed", error=str(e))
        return []


async def _get_ticket(request: Request, ticket_id: str) -> Optional[dict]:
    """Get ticket by ID."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return None

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, ticket_number, tenant_id, site_id, category, priority,
                       title, description, status, assigned_to, driver_id,
                       source, created_by, created_at, updated_at, resolved_at
                FROM ops.tickets
                WHERE id = %s::uuid
                """,
                (ticket_id,),
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": str(row[0]),
                    "ticket_number": row[1],
                    "tenant_id": row[2],
                    "site_id": row[3],
                    "category": TicketCategory(row[4]),
                    "priority": TicketPriority(row[5]),
                    "title": row[6],
                    "description": row[7],
                    "status": TicketStatus(row[8]),
                    "assigned_to": str(row[9]) if row[9] else None,
                    "driver_id": row[10],
                    "source": row[11],
                    "created_by": str(row[12]),
                    "created_at": row[13],
                    "updated_at": row[14],
                    "resolved_at": row[15],
                }
            return None
    except Exception as e:
        logger.warning("get_ticket_failed", error=str(e))
        return None


async def _create_ticket(
    request: Request,
    tenant_id: int,
    site_id: Optional[int],
    category: TicketCategory,
    priority: TicketPriority,
    title: str,
    description: str,
    assigned_to: Optional[str],
    driver_id: Optional[str],
    tour_id: Optional[int],
    created_by: str,
    source: str = "MANUAL",
    source_thread_id: Optional[str] = None,
) -> dict:
    """Create a ticket."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )

    try:
        with conn.cursor() as cur:
            ticket_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO ops.tickets (
                    id, tenant_id, site_id, category, priority, title, description,
                    status, assigned_to, driver_id, tour_id, source, source_thread_id,
                    created_by
                ) VALUES (
                    %s::uuid, %s, %s, %s, %s, %s, %s,
                    'OPEN', %s::uuid, %s, %s, %s, %s, %s::uuid
                )
                RETURNING ticket_number, created_at, updated_at
                """,
                (
                    ticket_id,
                    tenant_id,
                    site_id,
                    category.value,
                    priority.value,
                    title,
                    description,
                    assigned_to,
                    driver_id,
                    tour_id,
                    source,
                    source_thread_id,
                    created_by,
                ),
            )
            row = cur.fetchone()
            conn.commit()

            return {
                "id": ticket_id,
                "ticket_number": row[0],
                "tenant_id": tenant_id,
                "site_id": site_id,
                "category": category,
                "priority": priority,
                "title": title,
                "description": description,
                "status": TicketStatus.OPEN,
                "assigned_to": assigned_to,
                "driver_id": driver_id,
                "source": source,
                "created_by": created_by,
                "created_at": row[1],
                "updated_at": row[2],
                "resolved_at": None,
            }
    except Exception as e:
        logger.exception("create_ticket_failed", error=str(e))
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create ticket",
        )


async def _update_ticket(
    request: Request,
    ticket_id: str,
    status: Optional[TicketStatus] = None,
    priority: Optional[TicketPriority] = None,
    assigned_to: Optional[str] = None,
    updated_by: str = None,
) -> dict:
    """Update a ticket."""
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

            if status:
                updates.append("status = %s")
                params.append(status.value)
                if status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
                    updates.append("resolved_at = NOW()")
                elif status == TicketStatus.CLOSED:
                    updates.append("closed_at = NOW()")

            if priority:
                updates.append("priority = %s")
                params.append(priority.value)

            if assigned_to is not None:
                if assigned_to:
                    updates.append("assigned_to = %s::uuid")
                    params.append(assigned_to)
                else:
                    updates.append("assigned_to = NULL")

            params.append(ticket_id)

            cur.execute(
                f"""
                UPDATE ops.tickets
                SET {', '.join(updates)}
                WHERE id = %s::uuid
                RETURNING id, ticket_number, tenant_id, site_id, category, priority,
                          title, description, status, assigned_to, driver_id,
                          source, created_by, created_at, updated_at, resolved_at
                """,
                params,
            )
            row = cur.fetchone()
            conn.commit()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Ticket not found",
                )

            return {
                "id": str(row[0]),
                "ticket_number": row[1],
                "tenant_id": row[2],
                "site_id": row[3],
                "category": TicketCategory(row[4]),
                "priority": TicketPriority(row[5]),
                "title": row[6],
                "description": row[7],
                "status": TicketStatus(row[8]),
                "assigned_to": str(row[9]) if row[9] else None,
                "driver_id": row[10],
                "source": row[11],
                "created_by": str(row[12]),
                "created_at": row[13],
                "updated_at": row[14],
                "resolved_at": row[15],
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("update_ticket_failed", error=str(e))
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update ticket",
        )


async def _list_comments(request: Request, ticket_id: str) -> List[dict]:
    """List comments on a ticket."""
    conn = request.state.rbac_conn if hasattr(request.state, "rbac_conn") else None
    if not conn:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, ticket_id, comment_type, content, source, created_by, created_at
                FROM ops.ticket_comments
                WHERE ticket_id = %s::uuid
                ORDER BY created_at ASC
                """,
                (ticket_id,),
            )
            rows = cur.fetchall()

            return [
                {
                    "id": row[0],
                    "ticket_id": str(row[1]),
                    "comment_type": row[2],
                    "content": row[3],
                    "source": row[4],
                    "created_by": str(row[5]),
                    "created_at": row[6],
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning("list_comments_failed", error=str(e))
        return []


async def _add_comment(
    request: Request,
    ticket_id: str,
    tenant_id: int,
    content: str,
    created_by: str,
    source: str = "MANUAL",
    comment_type: str = "NOTE",
    source_thread_id: Optional[str] = None,
) -> dict:
    """Add a comment to a ticket."""
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
                INSERT INTO ops.ticket_comments (
                    ticket_id, tenant_id, comment_type, content, source,
                    source_thread_id, created_by
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid)
                RETURNING id, created_at
                """,
                (
                    ticket_id,
                    tenant_id,
                    comment_type,
                    content,
                    source,
                    source_thread_id,
                    created_by,
                ),
            )
            row = cur.fetchone()
            conn.commit()

            return {
                "id": row[0],
                "ticket_id": ticket_id,
                "comment_type": comment_type,
                "content": content,
                "source": source,
                "created_by": created_by,
                "created_at": row[1],
            }
    except Exception as e:
        logger.exception("add_comment_failed", error=str(e))
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add comment",
        )
