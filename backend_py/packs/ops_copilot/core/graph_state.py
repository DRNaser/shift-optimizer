"""
LangGraph State Schema for Ops-Copilot

Defines the state that flows through the graph nodes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Annotated, Sequence
from operator import add


class StopReason(str, Enum):
    """Reasons for stopping graph execution."""

    COMPLETE = "complete"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PAIRING_REQUIRED = "pairing_required"
    PAIRING_FAILED = "pairing_failed"
    PAIRING_SUCCESS = "pairing_success"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"
    MAX_TOOL_CALLS_EXCEEDED = "max_tool_calls_exceeded"
    TIMEOUT = "timeout"
    NO_NEW_EVIDENCE = "no_new_evidence"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"


class Intent(str, Enum):
    """Classified user intents."""

    GREETING = "greeting"
    HELP = "help"
    CREATE_TICKET = "create_ticket"
    VIEW_TICKETS = "view_tickets"
    UPDATE_TICKET = "update_ticket"
    AUDIT_COMMENT = "audit_comment"
    BROADCAST_OPS = "broadcast_ops"
    BROADCAST_DRIVER = "broadcast_driver"
    VIEW_SCHEDULE = "view_schedule"
    VIEW_DRIVER = "view_driver"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


@dataclass
class IdentityInfo:
    """Resolved WhatsApp identity information."""

    identity_id: str
    tenant_id: int
    site_id: Optional[int]
    user_id: str
    user_email: str
    user_display_name: Optional[str]
    role_name: str
    permissions: List[str]


@dataclass
class ContextItem:
    """Retrieved context item (playbook, memory, entity)."""

    type: str  # playbook, memory, entity
    id: str
    content: Dict[str, Any]
    relevance_score: float = 1.0


@dataclass
class MemoryCandidate:
    """Candidate memory to persist after conversation."""

    memory_type: str  # PREFERENCE, CORRECTION, CONTEXT, ENTITY, ACTION_HISTORY
    content: Dict[str, Any]
    expires_days: Optional[int] = None


@dataclass
class Message:
    """Conversation message."""

    role: str  # user, assistant, system
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OpsCopilotState:
    """
    State schema for the Ops-Copilot LangGraph.

    This state flows through all nodes and accumulates information
    during processing.
    """

    # ==========================================================================
    # Input (from webhook)
    # ==========================================================================

    wa_user_id: str = ""
    wa_phone_hash: str = ""
    message_id: str = ""
    input_text: str = ""
    trace_id: str = ""

    # ==========================================================================
    # Identity (resolved from wa_user_id)
    # ==========================================================================

    is_paired: bool = False
    identity: Optional[IdentityInfo] = None

    # Thread identity (deterministic)
    thread_id: str = ""

    # ==========================================================================
    # Conversation
    # ==========================================================================

    messages: List[Message] = field(default_factory=list)

    # ==========================================================================
    # Intent Classification
    # ==========================================================================

    current_intent: Intent = Intent.UNKNOWN
    intent_confidence: float = 0.0
    intent_entities: Dict[str, Any] = field(default_factory=dict)

    # ==========================================================================
    # Context Retrieval
    # ==========================================================================

    retrieved_context: List[ContextItem] = field(default_factory=list)

    # ==========================================================================
    # Tool Execution
    # ==========================================================================

    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    empty_result_streak: int = 0  # For "no new evidence" abort

    # ==========================================================================
    # 2-Phase Commit
    # ==========================================================================

    pending_draft_id: Optional[str] = None
    pending_action_type: Optional[str] = None
    pending_action_payload: Optional[Dict[str, Any]] = None
    awaiting_confirmation: bool = False

    # ==========================================================================
    # Pairing
    # ==========================================================================

    pairing_otp_candidate: Optional[str] = None
    pairing_result: Optional[Dict[str, Any]] = None

    # ==========================================================================
    # Output
    # ==========================================================================

    reply_text: str = ""
    output_draft_id: Optional[str] = None

    # ==========================================================================
    # Memory Candidates
    # ==========================================================================

    memory_candidates: List[MemoryCandidate] = field(default_factory=list)

    # ==========================================================================
    # Execution Tracking
    # ==========================================================================

    step_count: int = 0
    tool_call_count: int = 0
    started_at: datetime = field(default_factory=datetime.utcnow)
    stop_reason: Optional[StopReason] = None
    error_message: Optional[str] = None

    # ==========================================================================
    # Helpers
    # ==========================================================================

    def add_message(self, role: str, content: str, **metadata) -> None:
        """Add a message to the conversation."""
        self.messages.append(
            Message(role=role, content=content, metadata=metadata)
        )

    def get_conversation_history(self, max_messages: int = 10) -> List[Dict[str, str]]:
        """Get recent conversation history for LLM context."""
        recent = self.messages[-max_messages:]
        return [{"role": m.role, "content": m.content} for m in recent]

    def increment_step(self) -> bool:
        """
        Increment step count and check if max exceeded.

        Returns True if can continue, False if should stop.
        """
        from ..config import get_config

        self.step_count += 1
        config = get_config()

        if self.step_count >= config.max_steps_per_turn:
            self.stop_reason = StopReason.MAX_STEPS_EXCEEDED
            return False
        return True

    def increment_tool_calls(self) -> bool:
        """
        Increment tool call count and check if max exceeded.

        Returns True if can continue, False if should stop.
        """
        from ..config import get_config

        self.tool_call_count += 1
        config = get_config()

        if self.tool_call_count >= config.max_tool_calls:
            self.stop_reason = StopReason.MAX_TOOL_CALLS_EXCEEDED
            return False
        return True

    def check_timeout(self) -> bool:
        """
        Check if execution has timed out.

        Returns True if can continue, False if should stop.
        """
        from ..config import get_config

        config = get_config()
        elapsed = (datetime.utcnow() - self.started_at).total_seconds()

        if elapsed >= config.timeout_seconds:
            self.stop_reason = StopReason.TIMEOUT
            return False
        return True

    def record_empty_result(self) -> bool:
        """
        Record an empty tool result and check for abort condition.

        Returns True if can continue, False if should stop (no new evidence).
        """
        self.empty_result_streak += 1
        if self.empty_result_streak >= 3:
            self.stop_reason = StopReason.NO_NEW_EVIDENCE
            return False
        return True

    def record_non_empty_result(self) -> None:
        """Reset empty result streak on non-empty result."""
        self.empty_result_streak = 0

    def to_checkpoint_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for checkpointing."""
        return {
            "wa_user_id": self.wa_user_id,
            "thread_id": self.thread_id,
            "is_paired": self.is_paired,
            "identity": self.identity.__dict__ if self.identity else None,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
            "current_intent": self.current_intent.value,
            "pending_draft_id": self.pending_draft_id,
            "awaiting_confirmation": self.awaiting_confirmation,
            "step_count": self.step_count,
            "tool_call_count": self.tool_call_count,
        }

    @classmethod
    def from_checkpoint_dict(cls, data: Dict[str, Any]) -> "OpsCopilotState":
        """Restore state from checkpoint dictionary."""
        state = cls()
        state.wa_user_id = data.get("wa_user_id", "")
        state.thread_id = data.get("thread_id", "")
        state.is_paired = data.get("is_paired", False)

        if data.get("identity"):
            state.identity = IdentityInfo(**data["identity"])

        state.messages = [
            Message(
                role=m["role"],
                content=m["content"],
                timestamp=datetime.fromisoformat(m["timestamp"]),
                metadata=m.get("metadata", {}),
            )
            for m in data.get("messages", [])
        ]

        state.current_intent = Intent(data.get("current_intent", "unknown"))
        state.pending_draft_id = data.get("pending_draft_id")
        state.awaiting_confirmation = data.get("awaiting_confirmation", False)
        state.step_count = data.get("step_count", 0)
        state.tool_call_count = data.get("tool_call_count", 0)

        return state
