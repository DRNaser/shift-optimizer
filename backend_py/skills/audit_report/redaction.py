"""Redaction module for audit reports.

Provides data redaction for customer-safe vs internal audit packs.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from enum import Enum
import re
import hashlib
import json


class OutputMode(Enum):
    """Output mode for audit reports."""
    INTERNAL = "INTERNAL"
    CUSTOMER_SAFE = "CUSTOMER_SAFE"


@dataclass
class RedactionRule:
    """Defines what to redact and how."""
    pattern: str              # Regex or field name
    replacement: str          # What to replace with
    applies_to: OutputMode    # Which mode this applies to


# Standard redaction rules
REDACTION_RULES = [
    # Secrets and credentials
    RedactionRule(
        pattern=r'(password|secret|token|api_key|credential)["\s:=]+["\']?[\w\-\.]+["\']?',
        replacement=r'\1="[REDACTED]"',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
    # Email addresses (PII)
    RedactionRule(
        pattern=r'[\w\.-]+@[\w\.-]+\.\w+',
        replacement='[EMAIL_REDACTED]',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
    # IP addresses
    RedactionRule(
        pattern=r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        replacement='[IP_REDACTED]',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
    # Request IDs
    RedactionRule(
        pattern=r'request_id["\s:=]+["\']?[\w\-]+["\']?',
        replacement='request_id="[INTERNAL]"',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
    # Stack traces
    RedactionRule(
        pattern=r'Traceback \(most recent call last\):.*?(?=\n\n|\Z)',
        replacement='[See error code for details]',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
    # Internal paths
    RedactionRule(
        pattern=r'/backend_py/[\w/]+\.py',
        replacement='[INTERNAL_PATH]',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
    # Database URLs
    RedactionRule(
        pattern=r'postgresql://[\w:@\-\.]+/\w+',
        replacement='postgresql://[CONFIGURED]',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
    # Internal headers
    RedactionRule(
        pattern=r'X-SV-[\w\-]+',
        replacement='[INTERNAL_HEADER]',
        applies_to=OutputMode.CUSTOMER_SAFE
    ),
]

# Keys that should be removed entirely in customer-safe mode
SENSITIVE_KEYS = {
    'stack_trace', 'traceback', 'internal_error',
    'request_id', 'correlation_id', 'trace_id',
    'internal_config', 'debug_info', 'raw_query',
    'connection_string', 'secret', 'token'
}

# Patterns that MUST NOT appear in customer-safe output
FORBIDDEN_PATTERNS = [
    (r'Traceback', 'Stack trace found'),
    (r'password\s*[=:]\s*["\'][^"\']+["\']', 'Password found'),
    (r'secret\s*[=:]\s*["\'][^"\']+["\']', 'Secret found'),
    (r'token\s*[=:]\s*["\'][^"\']+["\']', 'Token found'),
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', 'IP address found'),
    (r'[\w\.-]+@[\w\.-]+\.\w+', 'Email address found'),
    (r'X-SV-Signature', 'Internal header found'),
    (r'request_id\s*[=:]\s*["\'][\w\-]+["\']', 'Request ID found'),
    (r'/backend_py/', 'Internal path found'),
]


class AuditRedactor:
    """Redacts sensitive information from audit packs."""

    def __init__(self, mode: OutputMode = OutputMode.CUSTOMER_SAFE):
        """Initialize redactor with output mode.

        Args:
            mode: OutputMode.INTERNAL for full details, CUSTOMER_SAFE for redacted
        """
        self.mode = mode
        self.rules = [r for r in REDACTION_RULES if r.applies_to == mode]

    def redact(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply redaction rules to data.

        Args:
            data: Dictionary to redact

        Returns:
            Redacted dictionary
        """
        if self.mode == OutputMode.INTERNAL:
            return data  # No redaction for internal

        return self._redact_recursive(data)

    def redact_text(self, text: str) -> str:
        """Apply redaction rules to text.

        Args:
            text: String to redact

        Returns:
            Redacted string
        """
        if self.mode == OutputMode.INTERNAL:
            return text

        return self._redact_string(text)

    def _redact_recursive(self, obj: Any) -> Any:
        """Recursively redact sensitive data."""
        if isinstance(obj, str):
            return self._redact_string(obj)
        elif isinstance(obj, dict):
            return {
                k: self._redact_recursive(v)
                for k, v in obj.items()
                if not self._should_remove_key(k)
            }
        elif isinstance(obj, list):
            return [self._redact_recursive(item) for item in obj]
        return obj

    def _redact_string(self, text: str) -> str:
        """Apply regex redaction rules to string."""
        result = text
        for rule in self.rules:
            result = re.sub(
                rule.pattern,
                rule.replacement,
                result,
                flags=re.DOTALL | re.IGNORECASE
            )
        return result

    def _should_remove_key(self, key: str) -> bool:
        """Check if key should be removed entirely."""
        if self.mode == OutputMode.INTERNAL:
            return False
        return key.lower() in SENSITIVE_KEYS

    def generate_redaction_audit(
        self,
        original: Dict[str, Any],
        redacted: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate audit of what was redacted (for internal records).

        Args:
            original: Original data before redaction
            redacted: Data after redaction

        Returns:
            Redaction audit record
        """
        return {
            'mode': self.mode.value,
            'original_hash': hashlib.sha256(
                json.dumps(original, sort_keys=True, default=str).encode()
            ).hexdigest(),
            'redacted_hash': hashlib.sha256(
                json.dumps(redacted, sort_keys=True, default=str).encode()
            ).hexdigest(),
            'fields_removed': self._count_removals(original, redacted),
            'patterns_applied': len(self.rules)
        }

    def _count_removals(self, original: Dict, redacted: Dict) -> int:
        """Count how many fields were removed."""
        def count_keys(obj):
            if isinstance(obj, dict):
                return len(obj) + sum(count_keys(v) for v in obj.values())
            elif isinstance(obj, list):
                return sum(count_keys(item) for item in obj)
            return 0
        return count_keys(original) - count_keys(redacted)


def verify_customer_safe(content: str) -> Dict[str, Any]:
    """Verify that customer-safe content contains no sensitive data.

    Args:
        content: Content to verify

    Returns:
        Verification result with violations
    """
    violations = []

    for pattern, message in FORBIDDEN_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        if matches:
            violations.append({
                'violation': message,
                'pattern': pattern,
                'matches': len(matches)
            })

    return {
        'passed': len(violations) == 0,
        'violations': violations,
    }
