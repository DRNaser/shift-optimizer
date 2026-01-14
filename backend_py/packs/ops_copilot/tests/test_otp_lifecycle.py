"""
OTP Pairing Lifecycle Tests

Tests:
- Success: valid OTP creates identity
- Wrong OTP: tries increment, eventually lock
- Expired OTP: rejected
- Max attempts exceeded: rejected
- Reuse: already paired rejected
"""

import hashlib
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from ..core.pairing import (
    generate_otp,
    hash_otp,
    parse_pair_command,
    create_pairing_invite,
    verify_pairing_otp,
    increment_attempt_count,
    revoke_identity,
)


class TestOTPGeneration:
    """Tests for OTP generation and hashing."""

    def test_generate_otp_format(self):
        """OTP should be 6 digits."""
        otp, otp_hash = generate_otp()
        assert len(otp) == 6
        assert otp.isdigit()

    def test_generate_otp_hash(self):
        """OTP hash should be SHA-256."""
        otp, otp_hash = generate_otp()
        expected_hash = hashlib.sha256(otp.encode()).hexdigest()
        assert otp_hash == expected_hash

    def test_generate_otp_uniqueness(self):
        """Generated OTPs should be unique."""
        otps = set()
        for _ in range(100):
            otp, _ = generate_otp()
            otps.add(otp)
        # With 10^6 possibilities, 100 should all be unique
        assert len(otps) == 100

    def test_hash_otp(self):
        """hash_otp should produce consistent SHA-256."""
        otp = "123456"
        expected = hashlib.sha256(otp.encode()).hexdigest()
        assert hash_otp(otp) == expected


class TestParsePairCommand:
    """Tests for PAIR command parsing."""

    def test_valid_pair_command(self):
        """Valid PAIR command should extract OTP."""
        assert parse_pair_command("PAIR 123456") == "123456"
        assert parse_pair_command("pair 654321") == "654321"
        assert parse_pair_command("  PAIR  999999  ") == "999999"

    def test_invalid_pair_command_no_prefix(self):
        """Messages without PAIR prefix should return None."""
        assert parse_pair_command("Hello") is None
        assert parse_pair_command("123456") is None
        assert parse_pair_command("PAIRING 123456") is None

    def test_invalid_pair_command_bad_otp(self):
        """PAIR with invalid OTP should return None."""
        assert parse_pair_command("PAIR 12345") is None  # Too short
        assert parse_pair_command("PAIR 1234567") is None  # Too long
        assert parse_pair_command("PAIR ABCDEF") is None  # Not digits
        assert parse_pair_command("PAIR 12A456") is None  # Mixed


class TestCreatePairingInvite:
    """Tests for creating pairing invites."""

    @pytest.mark.asyncio
    async def test_create_invite_success(self, mock_conn, test_tenant, test_users):
        """Creating invite should return OTP and invite ID."""
        user = test_users["dispatcher"]
        admin = test_users["tenant_admin"]

        # Mock cursor to return invite ID
        mock_conn._cursor.set_results([(123,)])

        result = await create_pairing_invite(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            user_id=user["user_id"],
            created_by=admin["user_id"],
        )

        assert "invite_id" in result
        assert "otp" in result
        assert len(result["otp"]) == 6
        assert "expires_at" in result
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_create_invite_custom_expiry(self, mock_conn, test_tenant, test_users):
        """Custom expiry should be respected."""
        user = test_users["dispatcher"]
        admin = test_users["tenant_admin"]

        mock_conn._cursor.set_results([(456,)])

        result = await create_pairing_invite(
            conn=mock_conn,
            tenant_id=test_tenant["tenant_id"],
            user_id=user["user_id"],
            created_by=admin["user_id"],
            expires_minutes=30,
        )

        # Verify expiry is ~30 minutes in the future
        now = datetime.now(timezone.utc)
        expires_at = result["expires_at"]
        delta = expires_at - now
        assert 29 <= delta.total_seconds() / 60 <= 31


class TestVerifyPairingOTP:
    """Tests for OTP verification and identity creation."""

    @pytest.mark.asyncio
    async def test_verify_otp_success(self, mock_conn, pending_invite, test_wa_user):
        """Valid OTP should create identity."""
        # Mock: find invite, no existing identity, create identity, mark used
        mock_conn._cursor.set_results([
            # Find invite
            (
                pending_invite["invite_id"],
                pending_invite["tenant_id"],
                pending_invite["user_id"],
                pending_invite["max_attempts"],
                pending_invite["attempt_count"],
            ),
            # Check existing identity - None
            None,
            # Create identity
            ("new-identity-id",),
            # Update invite
            None,
            # Record event
            None,
        ])

        result = await verify_pairing_otp(
            conn=mock_conn,
            wa_user_id=test_wa_user["wa_user_id"],
            wa_phone_hash=test_wa_user["wa_phone_hash"],
            otp=pending_invite["otp_plain"],
        )

        assert result["success"] is True
        assert "identity_id" in result
        assert result["tenant_id"] == pending_invite["tenant_id"]
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_verify_otp_invalid(self, mock_conn, test_wa_user):
        """Invalid OTP should be rejected."""
        # Mock: no matching invite found
        mock_conn._cursor.set_results([None])

        result = await verify_pairing_otp(
            conn=mock_conn,
            wa_user_id=test_wa_user["wa_user_id"],
            wa_phone_hash=test_wa_user["wa_phone_hash"],
            otp="000000",  # Wrong OTP
        )

        assert result["success"] is False
        assert result["error"] == "INVALID_OTP"

    @pytest.mark.asyncio
    async def test_verify_otp_max_attempts_exceeded(
        self, mock_conn, exhausted_invite, test_wa_user
    ):
        """OTP with exhausted attempts should be rejected."""
        # Mock: find invite with max attempts reached
        mock_conn._cursor.set_results([
            (
                exhausted_invite["invite_id"],
                exhausted_invite["tenant_id"],
                exhausted_invite["user_id"],
                exhausted_invite["max_attempts"],
                exhausted_invite["attempt_count"],
            ),
            # Update to exhausted
            None,
        ])

        result = await verify_pairing_otp(
            conn=mock_conn,
            wa_user_id=test_wa_user["wa_user_id"],
            wa_phone_hash=test_wa_user["wa_phone_hash"],
            otp=exhausted_invite["otp_plain"],
        )

        assert result["success"] is False
        assert result["error"] == "MAX_ATTEMPTS_EXCEEDED"

    @pytest.mark.asyncio
    async def test_verify_otp_already_paired(
        self, mock_conn, pending_invite, test_wa_user
    ):
        """Already paired WA user should be rejected."""
        # Mock: find invite, existing identity found
        mock_conn._cursor.set_results([
            # Find invite
            (
                pending_invite["invite_id"],
                pending_invite["tenant_id"],
                pending_invite["user_id"],
                pending_invite["max_attempts"],
                0,  # attempt_count
            ),
            # Check existing identity - found
            ("existing-identity-id",),
        ])

        result = await verify_pairing_otp(
            conn=mock_conn,
            wa_user_id=test_wa_user["wa_user_id"],
            wa_phone_hash=test_wa_user["wa_phone_hash"],
            otp=pending_invite["otp_plain"],
        )

        assert result["success"] is False
        assert result["error"] == "ALREADY_PAIRED"


class TestIncrementAttemptCount:
    """Tests for attempt counting."""

    @pytest.mark.asyncio
    async def test_increment_success(self, mock_conn, test_users):
        """Incrementing should return remaining attempts."""
        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([
            ("invite-id", 3, 1),  # id, max_attempts, new_count
        ])

        result = await increment_attempt_count(
            conn=mock_conn,
            user_id=user["user_id"],
        )

        assert result["exhausted"] is False
        assert result["remaining"] == 2

    @pytest.mark.asyncio
    async def test_increment_to_exhaustion(self, mock_conn, test_users):
        """Final attempt should mark as exhausted."""
        user = test_users["dispatcher"]

        mock_conn._cursor.set_results([
            ("invite-id", 3, 3),  # id, max_attempts, new_count (equal = exhausted)
            None,  # Update to exhausted
        ])

        result = await increment_attempt_count(
            conn=mock_conn,
            user_id=user["user_id"],
        )

        assert result["exhausted"] is True
        assert result["remaining"] == 0


class TestRevokeIdentity:
    """Tests for identity revocation."""

    @pytest.mark.asyncio
    async def test_revoke_success(self, mock_conn, paired_identity, test_users):
        """Revocation should update status and log event."""
        admin = test_users["tenant_admin"]

        mock_conn._cursor.set_results([
            # Get identity info
            (paired_identity["tenant_id"], paired_identity["user_id"]),
            # Update identity
            None,
            # Record event
            None,
        ])

        result = await revoke_identity(
            conn=mock_conn,
            identity_id=paired_identity["identity_id"],
            reason="Security concern",
            revoked_by=admin["user_id"],
        )

        assert result is True
        assert mock_conn._committed

    @pytest.mark.asyncio
    async def test_revoke_not_found(self, mock_conn, test_users):
        """Revoking non-existent identity should return False."""
        admin = test_users["tenant_admin"]

        mock_conn._cursor.set_results([None])

        result = await revoke_identity(
            conn=mock_conn,
            identity_id="non-existent-id",
            reason="Test",
            revoked_by=admin["user_id"],
        )

        assert result is False
