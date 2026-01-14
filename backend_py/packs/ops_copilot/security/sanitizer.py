"""
SOLVEREIGN Ops Copilot - Input Sanitizer (P2 Fix)
=================================================

Guardrails for preventing prompt injection and unsafe content.

This module is PRE-LLM - it establishes the safety patterns before
any LLM integration is wired up.

Key Principles:
1. Driver broadcasts are TEMPLATE-ONLY (no free text)
2. Ops broadcasts allow free text but sanitize for logging
3. No user input should trigger tool execution
4. No internal URLs, secrets, or sensitive data in outputs

Usage:
    from security.sanitizer import (
        sanitize_user_input,
        sanitize_llm_output,
        is_safe_for_broadcast,
        detect_injection_patterns,
    )
"""

import re
import html
import logging
from typing import Tuple, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# =============================================================================
# INJECTION PATTERN DETECTION
# =============================================================================

# Patterns that indicate potential prompt injection attempts
INJECTION_PATTERNS = [
    # System prompt manipulation
    (r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|rules?|policies?)", "system_override"),
    (r"disregard\s+(all\s+)?(previous|above|prior)", "system_override"),
    (r"forget\s+(everything|all|your)\s+(instructions?|rules?|training)", "system_override"),
    (r"new\s+instructions?:", "system_override"),
    (r"system\s*:\s*", "system_prompt"),

    # Tool/function execution attempts
    (r"call\s+(function|tool|api|endpoint)", "tool_execution"),
    (r"execute\s+(function|command|code|script)", "tool_execution"),
    (r"run\s+(function|command|code|script)", "tool_execution"),
    (r"\{\s*\"?function\"?\s*:", "json_function_call"),

    # Data exfiltration attempts
    (r"(send|transmit|forward|email)\s+(to|data|this|all)", "exfiltration"),
    (r"export\s+(all|data|users|secrets?)", "exfiltration"),
    (r"(api[_-]?key|secret|password|token|credential)s?\s*[=:]", "credential_leak"),

    # URL injection (internal endpoints)
    (r"https?://localhost", "internal_url"),
    (r"https?://127\.0\.0\.1", "internal_url"),
    (r"https?://0\.0\.0\.0", "internal_url"),
    (r"https?://10\.\d+\.\d+\.\d+", "internal_url"),
    (r"https?://172\.(1[6-9]|2[0-9]|3[01])\.\d+\.\d+", "internal_url"),
    (r"https?://192\.168\.\d+\.\d+", "internal_url"),

    # SQL injection patterns (in case input reaches DB)
    (r";\s*(DROP|DELETE|UPDATE|INSERT|TRUNCATE)", "sql_injection"),
    (r"';\s*--", "sql_injection"),
    (r"UNION\s+SELECT", "sql_injection"),

    # Script injection
    (r"<script", "xss"),
    (r"javascript:", "xss"),
    (r"on(load|error|click|mouseover)\s*=", "xss"),
]

# Compile patterns for efficiency
_COMPILED_PATTERNS = [(re.compile(p, re.IGNORECASE), name) for p, name in INJECTION_PATTERNS]


@dataclass
class SanitizationResult:
    """Result of input sanitization."""
    is_safe: bool
    sanitized_text: str
    detected_patterns: List[str]
    warnings: List[str]


def detect_injection_patterns(text: str) -> List[Tuple[str, str]]:
    """
    Detect potential injection patterns in text.

    Returns:
        List of (pattern_name, matched_text) tuples
    """
    detections = []

    for pattern, name in _COMPILED_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            # Get first match for logging
            match_text = matches[0] if isinstance(matches[0], str) else matches[0][0]
            detections.append((name, match_text[:50]))

    return detections


def sanitize_user_input(
    text: str,
    max_length: int = 4096,
    allow_urls: bool = False,
    context: str = "unknown",
) -> SanitizationResult:
    """
    Sanitize user input for safe processing.

    This does NOT make input safe for LLM prompts - it's for logging,
    storage, and human display.

    Args:
        text: Raw user input
        max_length: Maximum allowed length
        allow_urls: Whether to allow external URLs
        context: Context for logging (e.g., "ticket_description")

    Returns:
        SanitizationResult with sanitized text and detected issues
    """
    warnings = []
    detected = []

    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length]
        warnings.append(f"Truncated to {max_length} chars")

    # Detect injection patterns
    injections = detect_injection_patterns(text)
    if injections:
        detected = [name for name, _ in injections]
        logger.warning(
            "potential_injection_detected",
            extra={
                "context": context,
                "patterns": detected,
                "input_length": len(text),
            }
        )

    # HTML-escape for safe display (doesn't modify original for storage)
    sanitized = html.escape(text)

    # Remove internal URLs if not allowed
    if not allow_urls:
        for pattern, name in _COMPILED_PATTERNS:
            if name == "internal_url":
                sanitized = pattern.sub("[INTERNAL_URL_REDACTED]", sanitized)

    # Determine safety
    is_safe = len(detected) == 0

    return SanitizationResult(
        is_safe=is_safe,
        sanitized_text=sanitized,
        detected_patterns=detected,
        warnings=warnings,
    )


def sanitize_llm_output(
    text: str,
    strip_tool_calls: bool = True,
    strip_urls: bool = True,
) -> str:
    """
    Sanitize output from an LLM before displaying to users.

    Removes potentially dangerous content that an LLM might have been
    tricked into generating.

    Args:
        text: LLM-generated text
        strip_tool_calls: Remove JSON function call patterns
        strip_urls: Remove internal URLs

    Returns:
        Sanitized text safe for display
    """
    result = text

    if strip_tool_calls:
        # Remove JSON function call patterns
        result = re.sub(r'\{\s*"function"\s*:', "[FUNCTION_CALL_REMOVED]", result, flags=re.IGNORECASE)
        result = re.sub(r'\{\s*"tool"\s*:', "[TOOL_CALL_REMOVED]", result, flags=re.IGNORECASE)

    if strip_urls:
        # Remove internal URLs
        for pattern, name in _COMPILED_PATTERNS:
            if name == "internal_url":
                result = pattern.sub("[URL_REMOVED]", result)

    # HTML-escape
    result = html.escape(result)

    return result


def is_safe_for_broadcast(
    text: str,
    audience: str,  # "DRIVER" or "OPS"
) -> Tuple[bool, Optional[str]]:
    """
    Check if text is safe for broadcast.

    DRIVER broadcasts: Must use templates only (this rejects free text)
    OPS broadcasts: Allow free text but check for injection patterns

    Args:
        text: Text to check
        audience: "DRIVER" or "OPS"

    Returns:
        (is_safe, reason) - reason is None if safe
    """
    if audience == "DRIVER":
        # Driver broadcasts should NEVER have free-form text
        # They must go through template system
        # This function is called as a safety net
        if len(text) > 0:
            # Check if it looks like a template reference
            if not re.match(r"^[a-z0-9_]+$", text):
                return False, "Driver broadcasts must use templates, not free text"
        return True, None

    elif audience == "OPS":
        # Ops broadcasts allow free text but check for injections
        result = sanitize_user_input(text, context="ops_broadcast")
        if not result.is_safe:
            return False, f"Detected patterns: {', '.join(result.detected_patterns)}"
        return True, None

    else:
        return False, f"Unknown audience: {audience}"


def create_safe_broadcast_payload(
    template_key: str,
    params: dict,
    allowed_params: List[str],
) -> Tuple[bool, dict, Optional[str]]:
    """
    Create a safe broadcast payload by validating parameters.

    Ensures only allowed parameters are included and values are sanitized.

    Args:
        template_key: Template identifier
        params: User-provided parameters
        allowed_params: List of allowed parameter names

    Returns:
        (is_safe, sanitized_params, error_message)
    """
    sanitized = {}
    errors = []

    # Check for extra parameters
    extra_params = set(params.keys()) - set(allowed_params)
    if extra_params:
        errors.append(f"Unexpected parameters: {', '.join(extra_params)}")

    # Sanitize allowed parameters
    for key in allowed_params:
        if key in params:
            value = str(params[key])
            result = sanitize_user_input(value, max_length=500, context=f"param_{key}")

            if not result.is_safe:
                errors.append(f"Parameter {key} contains unsafe content")
            else:
                sanitized[key] = result.sanitized_text

    if errors:
        return False, {}, "; ".join(errors)

    return True, sanitized, None


# =============================================================================
# GUARDRAIL ENFORCEMENT
# =============================================================================

class InputGuardrails:
    """
    Centralized guardrail enforcement for Ops Copilot.

    Usage:
        guardrails = InputGuardrails()

        # Check incoming message
        result = guardrails.check_incoming_message(text)
        if not result.passed:
            return error_response(result.reason)

        # Check before draft creation
        result = guardrails.check_draft_payload(action_type, payload)
        if not result.passed:
            return error_response(result.reason)
    """

    @dataclass
    class CheckResult:
        passed: bool
        reason: Optional[str] = None
        sanitized: Optional[str] = None

    def check_incoming_message(self, text: str) -> CheckResult:
        """
        Check an incoming WhatsApp message for safety.

        Does NOT block - messages are logged and processed,
        but injection attempts are flagged.
        """
        result = sanitize_user_input(text, context="whatsapp_incoming")

        # Log but don't block - we want to see what attackers try
        if not result.is_safe:
            logger.warning(
                "guardrail_flagged_message",
                extra={
                    "patterns": result.detected_patterns,
                    "message_length": len(text),
                }
            )

        # For incoming messages, we allow processing but sanitize
        return self.CheckResult(
            passed=True,  # Always allow incoming for logging
            sanitized=result.sanitized_text,
        )

    def check_draft_payload(self, action_type: str, payload: dict) -> CheckResult:
        """
        Check a draft action payload before creation.

        This IS blocking - unsafe payloads are rejected.
        """
        # Check description field if present
        if "description" in payload:
            result = sanitize_user_input(
                str(payload["description"]),
                context=f"draft_{action_type}_description",
            )
            if not result.is_safe:
                return self.CheckResult(
                    passed=False,
                    reason=f"Description contains unsafe patterns: {result.detected_patterns}",
                )

        # Check title field if present
        if "title" in payload:
            result = sanitize_user_input(
                str(payload["title"]),
                context=f"draft_{action_type}_title",
                max_length=200,
            )
            if not result.is_safe:
                return self.CheckResult(
                    passed=False,
                    reason=f"Title contains unsafe patterns: {result.detected_patterns}",
                )

        return self.CheckResult(passed=True)

    def check_broadcast_params(
        self,
        audience: str,
        params: dict,
        allowed_params: List[str],
    ) -> CheckResult:
        """
        Check broadcast parameters for safety.
        """
        is_safe, sanitized, error = create_safe_broadcast_payload(
            template_key="",  # Not needed for validation
            params=params,
            allowed_params=allowed_params,
        )

        if not is_safe:
            return self.CheckResult(passed=False, reason=error)

        return self.CheckResult(passed=True, sanitized=str(sanitized))


# Singleton instance
guardrails = InputGuardrails()
