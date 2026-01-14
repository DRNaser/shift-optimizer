"""
LangGraph Node Implementations

Each node is a function that takes (conn, state) and returns updated state.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from uuid import uuid4
import re

from .graph_state import (
    OpsCopilotState,
    StopReason,
    Intent,
    IdentityInfo,
    ContextItem,
    MemoryCandidate,
)
from .identity import resolve_identity, get_or_create_thread, generate_thread_id
from .pairing import parse_pair_command, verify_pairing_otp
from .memory import retrieve_memories
from ..security.rbac import can_perform_action, ActionContext
from ..observability.tracing import get_logger
from ..config import get_config

logger = get_logger("nodes")


# =============================================================================
# Node: load_identity
# =============================================================================


async def load_identity_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Load and resolve WhatsApp identity.

    Sets: is_paired, identity, thread_id
    """
    identity = await resolve_identity(conn, state.wa_user_id)

    if identity:
        state.is_paired = True
        state.identity = IdentityInfo(
            identity_id=identity["identity_id"],
            tenant_id=identity["tenant_id"],
            site_id=identity.get("site_id"),
            user_id=identity["user_id"],
            user_email=identity["email"],
            user_display_name=identity.get("display_name"),
            role_name=identity["role_name"],
            permissions=identity["permissions"],
        )
        state.thread_id = identity.get("thread_id") or generate_thread_id(
            identity["tenant_id"],
            identity.get("site_id"),
            state.wa_user_id,
        )

        logger.debug(
            "identity_loaded",
            identity_id=identity["identity_id"],
            tenant_id=identity["tenant_id"],
            role=identity["role_name"],
        )
    else:
        state.is_paired = False
        logger.debug("identity_not_paired", wa_user_id=state.wa_user_id)

    return state


# =============================================================================
# Node: pairing_handler
# =============================================================================


async def pairing_handler_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Handle pairing flow for unpaired users.

    Detects "PAIR <OTP>" command and processes pairing.
    """
    if state.is_paired:
        return state

    # Check for PAIR command
    otp = parse_pair_command(state.input_text)

    if otp:
        state.pairing_otp_candidate = otp

        # Attempt pairing
        result = await verify_pairing_otp(
            conn=conn,
            wa_user_id=state.wa_user_id,
            wa_phone_hash=state.wa_phone_hash,
            otp=otp,
        )

        state.pairing_result = result

        if result.get("success"):
            state.is_paired = True
            state.stop_reason = StopReason.PAIRING_SUCCESS
            state.reply_text = (
                "Successfully paired! You can now use the Ops Assistant.\n"
                "Try asking: 'What can you help me with?'"
            )

            # Reload identity
            identity = await resolve_identity(conn, state.wa_user_id)
            if identity:
                state.identity = IdentityInfo(
                    identity_id=identity["identity_id"],
                    tenant_id=identity["tenant_id"],
                    site_id=identity.get("site_id"),
                    user_id=identity["user_id"],
                    user_email=identity["email"],
                    user_display_name=identity.get("display_name"),
                    role_name=identity["role_name"],
                    permissions=identity["permissions"],
                )
                state.thread_id = generate_thread_id(
                    identity["tenant_id"],
                    identity.get("site_id"),
                    state.wa_user_id,
                )
        else:
            error = result.get("error", "UNKNOWN")
            state.stop_reason = StopReason.PAIRING_FAILED

            if error == "INVALID_OTP":
                remaining = result.get("remaining_attempts", 0)
                state.reply_text = f"Invalid code. {remaining} attempts remaining."
            elif error == "MAX_ATTEMPTS_EXCEEDED":
                state.reply_text = "Too many failed attempts. Please request a new code."
            elif error == "NO_VALID_INVITE":
                state.reply_text = "No valid pairing invite found. Please request a new code."
            elif error == "ALREADY_PAIRED":
                state.reply_text = "This WhatsApp number is already paired."
            else:
                state.reply_text = "Pairing failed. Please try again or contact support."

        return state

    # Not paired and no PAIR command - send instructions
    state.reply_text = (
        "Hi! I'm the SOLVEREIGN Ops Assistant.\n"
        "To get started, ask your admin for a pairing code, "
        "then send: PAIR <your-code>"
    )

    return state


# =============================================================================
# Node: intent_router
# =============================================================================


async def intent_router_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Classify user intent from message text.

    Sets: current_intent, intent_confidence, intent_entities
    """
    text = state.input_text.lower().strip()

    # Simple rule-based intent classification (MVP)
    # In production, use LLM-based classification

    # Greetings
    if any(g in text for g in ["hallo", "hi", "hello", "guten tag", "servus", "moin"]):
        state.current_intent = Intent.GREETING
        state.intent_confidence = 0.9
        return state

    # Help
    if any(h in text for h in ["help", "hilfe", "was kannst du", "what can you"]):
        state.current_intent = Intent.HELP
        state.intent_confidence = 0.9
        return state

    # Confirm/Cancel
    if text in ["confirm", "ja", "bestätigen", "yes"]:
        state.current_intent = Intent.CONFIRM
        state.intent_confidence = 1.0
        return state

    if text in ["cancel", "nein", "abbrechen", "no"]:
        state.current_intent = Intent.CANCEL
        state.intent_confidence = 1.0
        return state

    # Ticket creation
    ticket_patterns = [
        r"create.*ticket",
        r"ticket.*erstellen",
        r"neues.*ticket",
        r"melde.*krankmeldung",
        r"sick.*call",
        r"krankmeldung",
        r"schichttausch",
        r"shift.*swap",
    ]
    for pattern in ticket_patterns:
        if re.search(pattern, text):
            state.current_intent = Intent.CREATE_TICKET
            state.intent_confidence = 0.8
            # Extract entities
            state.intent_entities = _extract_ticket_entities(text)
            return state

    # View tickets
    if any(v in text for v in ["show tickets", "zeige tickets", "meine tickets", "offene tickets"]):
        state.current_intent = Intent.VIEW_TICKETS
        state.intent_confidence = 0.8
        return state

    # Broadcast
    if any(b in text for b in ["broadcast", "nachricht senden", "rundschreiben"]):
        if "driver" in text or "fahrer" in text:
            state.current_intent = Intent.BROADCAST_DRIVER
        else:
            state.current_intent = Intent.BROADCAST_OPS
        state.intent_confidence = 0.7
        return state

    # View schedule
    if any(s in text for s in ["schedule", "dienstplan", "schichtplan"]):
        state.current_intent = Intent.VIEW_SCHEDULE
        state.intent_confidence = 0.7
        return state

    # Unknown
    state.current_intent = Intent.UNKNOWN
    state.intent_confidence = 0.3

    return state


def _extract_ticket_entities(text: str) -> Dict[str, Any]:
    """Extract entities for ticket creation."""
    entities = {}

    # Category detection
    if any(k in text for k in ["krank", "sick"]):
        entities["category"] = "SICK_CALL"
    elif any(t in text for t in ["tausch", "swap"]):
        entities["category"] = "SHIFT_SWAP"
    elif any(v in text for v in ["fahrzeug", "vehicle", "auto"]):
        entities["category"] = "VEHICLE_ISSUE"

    # Priority detection
    if any(u in text for u in ["urgent", "dringend", "sofort"]):
        entities["priority"] = "URGENT"
    elif any(h in text for h in ["wichtig", "high"]):
        entities["priority"] = "HIGH"

    return entities


# =============================================================================
# Node: retrieve_context
# =============================================================================


async def retrieve_context_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Retrieve relevant context for the conversation.

    Loads: playbooks, memories, relevant entities
    """
    if not state.identity:
        return state

    context_items = []

    # Retrieve memories
    memories = await retrieve_memories(
        conn=conn,
        tenant_id=state.identity.tenant_id,
        thread_id=state.thread_id,
        limit=10,
    )

    for mem in memories:
        context_items.append(
            ContextItem(
                type="memory",
                id=mem["id"],
                content=mem["content"],
                relevance_score=mem["relevance_score"],
            )
        )

    # Retrieve relevant playbooks based on intent
    playbooks = await _retrieve_playbooks(
        conn=conn,
        tenant_id=state.identity.tenant_id,
        intent=state.current_intent,
    )

    for pb in playbooks:
        context_items.append(
            ContextItem(
                type="playbook",
                id=pb["id"],
                content={
                    "title": pb["title"],
                    "content": pb["content_markdown"],
                    "category": pb["category"],
                },
                relevance_score=1.0,
            )
        )

    state.retrieved_context = context_items

    logger.debug(
        "context_retrieved",
        memory_count=len(memories),
        playbook_count=len(playbooks),
    )

    return state


async def _retrieve_playbooks(
    conn,
    tenant_id: int,
    intent: Intent,
) -> List[Dict[str, Any]]:
    """Retrieve relevant playbooks for intent."""
    # Map intents to playbook categories
    category_map = {
        Intent.CREATE_TICKET: ["ESCALATION", "SICK_CALL", "SHIFT_SWAP", "GENERAL"],
        Intent.BROADCAST_OPS: ["GENERAL"],
        Intent.BROADCAST_DRIVER: ["GENERAL"],
    }

    categories = category_map.get(intent, [])
    if not categories:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, content_markdown, category
                FROM ops.playbooks
                WHERE tenant_id = %s
                  AND is_active = TRUE
                  AND (category = ANY(%s) OR category IS NULL)
                ORDER BY category NULLS LAST
                LIMIT 3
                """,
                (tenant_id, categories),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "content_markdown": row[2],
                    "category": row[3],
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning("retrieve_playbooks_failed", error=str(e))
        return []


# =============================================================================
# Node: read_tools
# =============================================================================


async def read_tools_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Execute read-only tools to gather information.

    Called for VIEW_* intents.
    """
    if not state.identity:
        return state

    if state.current_intent == Intent.VIEW_TICKETS:
        result = await _read_tickets(conn, state)
        state.tool_results.append({"tool": "view_tickets", "result": result})
        if result:
            state.record_non_empty_result()
        else:
            if not state.record_empty_result():
                return state

    elif state.current_intent == Intent.VIEW_SCHEDULE:
        # Placeholder for schedule viewing
        state.tool_results.append({
            "tool": "view_schedule",
            "result": {"note": "Schedule viewing not implemented in MVP"},
        })

    state.increment_tool_calls()

    return state


async def _read_tickets(conn, state: OpsCopilotState) -> List[Dict[str, Any]]:
    """Read user's tickets."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, ticket_number, title, category, priority, status, created_at
                FROM ops.tickets
                WHERE tenant_id = %s
                  AND (created_by = %s::uuid OR assigned_to = %s::uuid)
                  AND status NOT IN ('CLOSED')
                ORDER BY created_at DESC
                LIMIT 5
                """,
                (
                    state.identity.tenant_id,
                    state.identity.user_id,
                    state.identity.user_id,
                ),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": str(row[0]),
                    "number": row[1],
                    "title": row[2],
                    "category": row[3],
                    "priority": row[4],
                    "status": row[5],
                    "created_at": row[6].isoformat() if row[6] else None,
                }
                for row in rows
            ]
    except Exception as e:
        logger.warning("read_tickets_failed", error=str(e))
        return []


# =============================================================================
# Node: compose_answer
# =============================================================================


async def compose_answer_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Compose the response to the user.

    Uses context, tool results, and intent to generate reply.
    """
    if state.current_intent == Intent.GREETING:
        name = state.identity.user_display_name or state.identity.user_email.split("@")[0]
        state.reply_text = (
            f"Hallo {name}! Wie kann ich dir helfen?\n\n"
            "Du kannst mich zum Beispiel fragen:\n"
            "- 'Zeige meine Tickets'\n"
            "- 'Erstelle eine Krankmeldung'\n"
            "- 'Hilfe'"
        )
        return state

    if state.current_intent == Intent.HELP:
        state.reply_text = (
            "Ich bin der SOLVEREIGN Ops-Assistent. Ich kann dir helfen mit:\n\n"
            "**Tickets:**\n"
            "- Krankmeldungen erstellen\n"
            "- Schichttausch anfragen\n"
            "- Tickets anzeigen\n\n"
            "**Kommunikation:**\n"
            "- Nachrichten an Kollegen senden\n\n"
            "Frag einfach, was du brauchst!"
        )
        return state

    if state.current_intent == Intent.VIEW_TICKETS:
        tickets = next(
            (r["result"] for r in state.tool_results if r["tool"] == "view_tickets"),
            [],
        )
        if tickets:
            lines = ["**Deine offenen Tickets:**\n"]
            for t in tickets:
                lines.append(f"- OPS-{t['number']}: {t['title']} ({t['status']})")
            state.reply_text = "\n".join(lines)
        else:
            state.reply_text = "Du hast keine offenen Tickets."
        return state

    if state.current_intent == Intent.UNKNOWN:
        state.reply_text = (
            "Entschuldigung, ich habe dich nicht verstanden.\n"
            "Versuche es mit 'Hilfe' für eine Liste der Möglichkeiten."
        )
        return state

    # For write intents, reply will be set in prepare_write
    return state


# =============================================================================
# Node: prepare_write
# =============================================================================


async def prepare_write_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Prepare a write action for 2-phase commit.

    Creates draft and asks for confirmation.
    """
    if not state.identity:
        state.reply_text = "Authentifizierung erforderlich."
        return state

    # Check permission
    action_type = _intent_to_action_type(state.current_intent)
    if not action_type:
        return state

    permissions = set(state.identity.permissions)
    if not can_perform_action(permissions, action_type, state.identity.role_name):
        state.reply_text = "Du hast keine Berechtigung für diese Aktion."
        return state

    # Build payload
    payload = _build_action_payload(state)
    preview = _generate_preview(action_type, payload)

    # Create draft
    config = get_config()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=config.draft_expires_minutes)

    try:
        with conn.cursor() as cur:
            draft_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO ops.drafts (
                    id, tenant_id, thread_id, identity_id,
                    action_type, payload, preview_text, expires_at
                ) VALUES (%s::uuid, %s, %s, %s::uuid, %s, %s, %s, %s)
                """,
                (
                    draft_id,
                    state.identity.tenant_id,
                    state.thread_id,
                    state.identity.identity_id,
                    action_type,
                    payload,
                    preview,
                    expires_at,
                ),
            )

            # Record event
            cur.execute(
                """
                INSERT INTO ops.events (
                    tenant_id, thread_id, event_type, payload
                ) VALUES (%s, %s, 'DRAFT_CREATED', %s)
                """,
                (state.identity.tenant_id, state.thread_id, {"draft_id": draft_id, "action_type": action_type}),
            )

            conn.commit()

            state.pending_draft_id = draft_id
            state.pending_action_type = action_type
            state.pending_action_payload = payload
            state.awaiting_confirmation = True
            state.output_draft_id = draft_id

            state.reply_text = (
                f"Ich habe folgende Aktion vorbereitet:\n\n{preview}\n\n"
                "Antworte mit **CONFIRM** um fortzufahren oder **CANCEL** um abzubrechen."
            )

            logger.info(
                "draft_created",
                draft_id=draft_id,
                action_type=action_type,
            )

    except Exception as e:
        logger.exception("prepare_write_failed", error=str(e))
        conn.rollback()
        state.reply_text = "Fehler beim Vorbereiten der Aktion. Bitte versuche es erneut."

    return state


def _intent_to_action_type(intent: Intent) -> Optional[str]:
    """Map intent to action type."""
    mapping = {
        Intent.CREATE_TICKET: "CREATE_TICKET",
        Intent.AUDIT_COMMENT: "AUDIT_COMMENT",
        Intent.BROADCAST_OPS: "WHATSAPP_BROADCAST_OPS",
        Intent.BROADCAST_DRIVER: "WHATSAPP_BROADCAST_DRIVER",
    }
    return mapping.get(intent)


def _build_action_payload(state: OpsCopilotState) -> Dict[str, Any]:
    """Build action payload from state."""
    entities = state.intent_entities

    if state.current_intent == Intent.CREATE_TICKET:
        return {
            "category": entities.get("category", "OTHER"),
            "priority": entities.get("priority", "MEDIUM"),
            "title": f"Ticket from {state.identity.user_email}",
            "description": state.input_text,
        }

    return {}


def _generate_preview(action_type: str, payload: Dict[str, Any]) -> str:
    """Generate human-readable preview."""
    if action_type == "CREATE_TICKET":
        return (
            f"**Ticket erstellen**\n"
            f"- Kategorie: {payload.get('category', 'OTHER')}\n"
            f"- Priorität: {payload.get('priority', 'MEDIUM')}\n"
            f"- Beschreibung: {payload.get('description', '')[:100]}..."
        )

    return f"Aktion: {action_type}"


# =============================================================================
# Node: commit_write
# =============================================================================


async def commit_write_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Execute a confirmed write action.

    Called after user sends CONFIRM.
    """
    if not state.pending_draft_id:
        state.reply_text = "Keine ausstehende Aktion gefunden."
        return state

    try:
        with conn.cursor() as cur:
            # Get draft
            cur.execute(
                """
                SELECT action_type, payload, status
                FROM ops.drafts
                WHERE id = %s::uuid
                """,
                (state.pending_draft_id,),
            )
            row = cur.fetchone()

            if not row:
                state.reply_text = "Entwurf nicht gefunden."
                return state

            action_type, payload, status = row[0], row[1], row[2]

            if status != "PENDING_CONFIRM":
                state.reply_text = f"Entwurf ist bereits {status}."
                return state

            # Execute action
            result = await _execute_action(conn, state, action_type, payload)

            # Update draft
            cur.execute(
                """
                UPDATE ops.drafts
                SET status = 'COMMITTED',
                    confirmed_at = NOW(),
                    committed_at = NOW(),
                    commit_result = %s,
                    updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (result, state.pending_draft_id),
            )

            # Record event
            cur.execute(
                """
                INSERT INTO ops.events (
                    tenant_id, thread_id, event_type, payload
                ) VALUES (%s, %s, 'DRAFT_COMMITTED', %s)
                """,
                (
                    state.identity.tenant_id,
                    state.thread_id,
                    {"draft_id": state.pending_draft_id, "result": result},
                ),
            )

            conn.commit()

            state.pending_draft_id = None
            state.awaiting_confirmation = False
            state.reply_text = f"Aktion erfolgreich ausgeführt.\n{result.get('message', '')}"

            logger.info(
                "draft_committed",
                draft_id=state.pending_draft_id,
                action_type=action_type,
            )

    except Exception as e:
        logger.exception("commit_write_failed", error=str(e))
        conn.rollback()
        state.reply_text = "Fehler beim Ausführen der Aktion."

    return state


async def _execute_action(
    conn,
    state: OpsCopilotState,
    action_type: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute the action and return result."""
    with conn.cursor() as cur:
        if action_type == "CREATE_TICKET":
            ticket_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO ops.tickets (
                    id, tenant_id, category, priority, title, description,
                    status, source, source_thread_id, created_by
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s, 'OPEN', 'COPILOT', %s, %s::uuid)
                RETURNING ticket_number
                """,
                (
                    ticket_id,
                    state.identity.tenant_id,
                    payload["category"],
                    payload["priority"],
                    payload["title"],
                    payload["description"],
                    state.thread_id,
                    state.identity.user_id,
                ),
            )
            ticket_number = cur.fetchone()[0]
            return {
                "ticket_id": ticket_id,
                "ticket_number": ticket_number,
                "message": f"Ticket OPS-{ticket_number} erstellt.",
            }

        return {"message": "Aktion ausgeführt."}


# =============================================================================
# Node: learn_candidate
# =============================================================================


async def learn_candidate_node(conn, state: OpsCopilotState) -> OpsCopilotState:
    """
    Extract memory candidates from conversation.

    Only episodic memory, no auto-approve playbooks in MVP.
    """
    # Example: If user corrected us, remember the correction
    # This is a placeholder for more sophisticated learning

    if state.current_intent == Intent.UNKNOWN:
        # User said something we didn't understand
        # Could be a learning opportunity
        state.memory_candidates.append(
            MemoryCandidate(
                memory_type="CONTEXT",
                content={
                    "message": state.input_text,
                    "intent": "UNKNOWN",
                    "note": "User message not understood - potential learning opportunity",
                },
                expires_days=7,
            )
        )

    return state
