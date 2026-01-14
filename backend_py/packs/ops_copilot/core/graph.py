"""
LangGraph Orchestrator Definition

Defines the state machine graph for Ops-Copilot message processing.

Graph Flow:
    [START]
        -> load_identity
        -> pairing_handler (if not paired, ends with pairing instructions)
        -> intent_router
        -> retrieve_context
        -> read_tools (optional, for queries)
        -> compose_answer
        -> prepare_write (if write intent)
        -> [END] (with reply or awaiting confirmation)

    [CONFIRM/CANCEL]
        -> load_identity
        -> confirm_handler
        -> commit_write (if confirmed)
        -> [END]
"""

from typing import Dict, Any, Callable, Optional
from datetime import datetime
from dataclasses import asdict

from .graph_state import OpsCopilotState, StopReason, Intent, IdentityInfo
from .nodes import (
    load_identity_node,
    pairing_handler_node,
    intent_router_node,
    retrieve_context_node,
    read_tools_node,
    compose_answer_node,
    prepare_write_node,
    commit_write_node,
    learn_candidate_node,
)
from ..config import get_config
from ..observability.tracing import get_logger
from ..observability.metrics import record_graph_steps, record_response_latency

logger = get_logger("graph")


# =============================================================================
# Graph Definition
# =============================================================================


class OpsCopilotGraph:
    """
    LangGraph-style state machine for Ops-Copilot.

    Implements bounded execution with:
    - max_steps_per_turn (default: 8)
    - max_tool_calls (default: 5)
    - timeout_seconds (default: 20)
    - "no new evidence" abort after 3 empty tool results
    """

    def __init__(self, conn):
        """
        Initialize the graph.

        Args:
            conn: Database connection for state persistence
        """
        self.conn = conn
        self.config = get_config()
        self.nodes: Dict[str, Callable] = {}
        self._setup_nodes()

    def _setup_nodes(self):
        """Register all graph nodes."""
        self.nodes = {
            "load_identity": load_identity_node,
            "pairing_handler": pairing_handler_node,
            "intent_router": intent_router_node,
            "retrieve_context": retrieve_context_node,
            "read_tools": read_tools_node,
            "compose_answer": compose_answer_node,
            "prepare_write": prepare_write_node,
            "commit_write": commit_write_node,
            "learn_candidate": learn_candidate_node,
        }

    async def process(self, state: OpsCopilotState) -> OpsCopilotState:
        """
        Process a message through the graph.

        Args:
            state: Initial state with input message

        Returns:
            Final state with reply and any side effects
        """
        logger.info(
            "graph_process_start",
            trace_id=state.trace_id,
            wa_user_id=state.wa_user_id,
        )

        try:
            # Node execution order
            # 1. Load identity
            state = await self._run_node("load_identity", state)
            if state.stop_reason:
                return state

            # 2. Handle pairing (if not paired)
            state = await self._run_node("pairing_handler", state)
            if state.stop_reason:
                return state

            # If still not paired after pairing handler, we're done
            if not state.is_paired:
                state.stop_reason = StopReason.PAIRING_REQUIRED
                return state

            # 3. Check for CONFIRM/CANCEL intent (2-phase commit)
            if self._is_confirm_cancel(state.input_text):
                return await self._handle_confirmation(state)

            # 4. Route intent
            state = await self._run_node("intent_router", state)
            if state.stop_reason:
                return state

            # 5. Retrieve context
            state = await self._run_node("retrieve_context", state)
            if state.stop_reason:
                return state

            # 6. Execute read tools (if applicable)
            if self._needs_read_tools(state):
                state = await self._run_node("read_tools", state)
                if state.stop_reason:
                    return state

            # 7. Compose answer
            state = await self._run_node("compose_answer", state)
            if state.stop_reason:
                return state

            # 8. Prepare write (if write intent)
            if self._is_write_intent(state.current_intent):
                state = await self._run_node("prepare_write", state)
                if state.stop_reason:
                    return state

                if state.awaiting_confirmation:
                    # Stop and wait for CONFIRM
                    state.stop_reason = StopReason.AWAITING_CONFIRMATION
                    return state

            # 9. Learn from conversation
            state = await self._run_node("learn_candidate", state)

            # Done
            state.stop_reason = StopReason.COMPLETE
            return state

        except Exception as e:
            logger.exception("graph_process_error", error=str(e))
            state.error_message = str(e)
            state.stop_reason = StopReason.ERROR
            state.reply_text = "Sorry, an error occurred. Please try again."
            return state

        finally:
            # Record metrics
            elapsed = (datetime.utcnow() - state.started_at).total_seconds()
            if state.identity:
                record_graph_steps(state.identity.tenant_id, state.step_count)
                record_response_latency(state.identity.tenant_id, elapsed)

            logger.info(
                "graph_process_complete",
                trace_id=state.trace_id,
                stop_reason=state.stop_reason.value if state.stop_reason else None,
                step_count=state.step_count,
                tool_calls=state.tool_call_count,
                elapsed_ms=int(elapsed * 1000),
            )

    async def _run_node(
        self,
        node_name: str,
        state: OpsCopilotState,
    ) -> OpsCopilotState:
        """
        Execute a single node with bounds checking.

        Args:
            node_name: Name of the node to execute
            state: Current state

        Returns:
            Updated state
        """
        # Check execution bounds
        if not state.increment_step():
            return state

        if not state.check_timeout():
            return state

        # Execute node
        node_fn = self.nodes.get(node_name)
        if not node_fn:
            logger.error("node_not_found", node_name=node_name)
            return state

        logger.debug(
            "node_execute",
            node=node_name,
            step=state.step_count,
        )

        state = await node_fn(self.conn, state)

        return state

    async def _handle_confirmation(
        self,
        state: OpsCopilotState,
    ) -> OpsCopilotState:
        """Handle CONFIRM/CANCEL commands for 2-phase commit."""
        text = state.input_text.strip().upper()

        if text == "CONFIRM":
            if not state.pending_draft_id:
                state.reply_text = "Nothing to confirm. Send a request first."
                state.stop_reason = StopReason.COMPLETE
                return state

            # Execute commit
            state = await self._run_node("commit_write", state)
            state.stop_reason = StopReason.COMPLETE
            return state

        elif text in ("CANCEL", "ABBRECHEN", "NEIN"):
            if state.pending_draft_id:
                # Cancel the pending draft
                await self._cancel_draft(state.pending_draft_id)
                state.pending_draft_id = None
                state.pending_action_type = None
                state.awaiting_confirmation = False
                state.reply_text = "Action cancelled."
            else:
                state.reply_text = "Nothing to cancel."

            state.stop_reason = StopReason.COMPLETE
            return state

        return state

    async def _cancel_draft(self, draft_id: str) -> None:
        """Cancel a pending draft."""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ops.drafts
                    SET status = 'CANCELLED', updated_at = NOW()
                    WHERE id = %s::uuid AND status = 'PENDING_CONFIRM'
                    """,
                    (draft_id,),
                )
                self.conn.commit()
        except Exception as e:
            logger.warning("cancel_draft_failed", error=str(e))
            self.conn.rollback()

    def _is_confirm_cancel(self, text: str) -> bool:
        """Check if message is a CONFIRM/CANCEL command."""
        text = text.strip().upper()
        return text in ("CONFIRM", "CANCEL", "JA", "NEIN", "ABBRECHEN", "BESTÄTIGEN")

    def _needs_read_tools(self, state: OpsCopilotState) -> bool:
        """Check if intent requires read tools."""
        read_intents = {
            Intent.VIEW_TICKETS,
            Intent.VIEW_SCHEDULE,
            Intent.VIEW_DRIVER,
        }
        return state.current_intent in read_intents

    def _is_write_intent(self, intent: Intent) -> bool:
        """Check if intent is a write action."""
        write_intents = {
            Intent.CREATE_TICKET,
            Intent.UPDATE_TICKET,
            Intent.AUDIT_COMMENT,
            Intent.BROADCAST_OPS,
            Intent.BROADCAST_DRIVER,
        }
        return intent in write_intents


# =============================================================================
# Entry Point
# =============================================================================


async def process_message(
    conn,
    wa_user_id: str,
    wa_phone_hash: str,
    message_id: str,
    text: str,
    trace_id: str,
) -> Dict[str, Any]:
    """
    Process an incoming WhatsApp message.

    Main entry point for the orchestrator.

    Args:
        conn: Database connection
        wa_user_id: WhatsApp user ID
        wa_phone_hash: SHA-256 hash of phone number
        message_id: Message ID for idempotency
        text: Message text
        trace_id: Request trace ID

    Returns:
        Result dict with reply_text and optional draft_id
    """
    # Initialize state
    state = OpsCopilotState(
        wa_user_id=wa_user_id,
        wa_phone_hash=wa_phone_hash,
        message_id=message_id,
        input_text=text,
        trace_id=trace_id,
        started_at=datetime.utcnow(),
    )

    # Add input message to conversation
    state.add_message("user", text)

    # Process through graph
    graph = OpsCopilotGraph(conn)
    final_state = await graph.process(state)

    # Persist memories if any
    if final_state.memory_candidates:
        await _persist_memories(conn, final_state)

    # Return result
    return {
        "reply_text": final_state.reply_text,
        "draft_id": final_state.output_draft_id,
        "stop_reason": final_state.stop_reason.value if final_state.stop_reason else None,
        "step_count": final_state.step_count,
        "tool_calls": final_state.tool_call_count,
    }


async def _persist_memories(
    conn,
    state: OpsCopilotState,
) -> None:
    """Persist memory candidates from conversation."""
    from .memory import store_memory

    if not state.identity:
        return

    for candidate in state.memory_candidates:
        try:
            await store_memory(
                conn=conn,
                tenant_id=state.identity.tenant_id,
                thread_id=state.thread_id,
                memory_type=candidate.memory_type,
                content=candidate.content,
                expires_days=candidate.expires_days,
            )
        except Exception as e:
            logger.warning(
                "memory_persist_failed",
                error=str(e),
                memory_type=candidate.memory_type,
            )
