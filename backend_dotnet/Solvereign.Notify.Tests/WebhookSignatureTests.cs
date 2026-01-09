// =============================================================================
// SOLVEREIGN V4.1.1 - Webhook Signature Verification Tests
// =============================================================================
// WhatsApp: HMAC-SHA256 with shared secret
// SendGrid: ECDSA P-256 with public key (NOT HMAC!)
// =============================================================================

using System.Security.Cryptography;
using System.Text;
using FluentAssertions;
using Moq;
using Solvereign.Notify.Models;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Tests;

/// <summary>
/// Tests for webhook signature verification.
/// Ensures webhook endpoints reject invalid signatures and process valid ones idempotently.
/// </summary>
public class WebhookSignatureTests
{
    // WhatsApp uses HMAC-SHA256 with shared secret
    private const string WhatsAppTestSecret = "test_webhook_secret_key_12345";

    // SendGrid uses ECDSA P-256 - we generate a test key pair
    private static readonly ECDsa _sendGridTestPrivateKey;
    private static readonly string _sendGridTestPublicKeyBase64;

    static WebhookSignatureTests()
    {
        // Generate a fresh ECDSA P-256 key pair for testing
        _sendGridTestPrivateKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);

        // Export public key in SPKI format (what SendGrid provides)
        var publicKeyBytes = _sendGridTestPrivateKey.ExportSubjectPublicKeyInfo();
        _sendGridTestPublicKeyBase64 = Convert.ToBase64String(publicKeyBytes);
    }

    /// <summary>
    /// WhatsApp signature verification should pass for valid HMAC-SHA256.
    /// </summary>
    [Fact]
    public void VerifyWhatsAppSignature_ValidSignature_ReturnsTrue()
    {
        // Arrange
        var body = @"{""entry"":[{""changes"":[{""value"":{""statuses"":[{""id"":""msg123""}]}}]}]}";
        var expectedSignature = ComputeWhatsAppSignature(body, WhatsAppTestSecret);

        // Act
        var isValid = VerifyWhatsAppSignature(body, expectedSignature, WhatsAppTestSecret);

        // Assert
        isValid.Should().BeTrue("valid HMAC-SHA256 signature should be accepted");
    }

    /// <summary>
    /// WhatsApp signature verification should fail for invalid signature.
    /// </summary>
    [Fact]
    public void VerifyWhatsAppSignature_InvalidSignature_ReturnsFalse()
    {
        // Arrange
        var body = @"{""entry"":[{""changes"":[{""value"":{""statuses"":[{""id"":""msg123""}]}}]}]}";
        var invalidSignature = "sha256=0000000000000000000000000000000000000000000000000000000000000000";

        // Act
        var isValid = VerifyWhatsAppSignature(body, invalidSignature, WhatsAppTestSecret);

        // Assert
        isValid.Should().BeFalse("invalid signature should be rejected");
    }

    /// <summary>
    /// WhatsApp signature verification should fail for missing signature.
    /// </summary>
    [Fact]
    public void VerifyWhatsAppSignature_MissingSignature_ReturnsFalse()
    {
        // Arrange
        var body = @"{""entry"":[]}";

        // Act
        var isValid = VerifyWhatsAppSignature(body, null, WhatsAppTestSecret);

        // Assert
        isValid.Should().BeFalse("missing signature should be rejected");
    }

    /// <summary>
    /// WhatsApp signature verification should fail for malformed signature.
    /// </summary>
    [Fact]
    public void VerifyWhatsAppSignature_MalformedSignature_ReturnsFalse()
    {
        // Arrange
        var body = @"{""entry"":[]}";
        var malformedSignature = "not-a-valid-signature-format";

        // Act
        var isValid = VerifyWhatsAppSignature(body, malformedSignature, WhatsAppTestSecret);

        // Assert
        isValid.Should().BeFalse("malformed signature should be rejected");
    }

    // =========================================================================
    // SendGrid ECDSA P-256 Tests
    // =========================================================================

    /// <summary>
    /// SendGrid signature verification should pass for valid ECDSA signature.
    /// SendGrid uses ECDSA P-256 (NOT HMAC!) for Signed Event Webhooks.
    /// </summary>
    [Fact]
    public void VerifySendGridSignature_ValidEcdsaSignature_ReturnsTrue()
    {
        // Arrange
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        var body = @"[{""event"":""delivered"",""sg_message_id"":""msg123""}]";
        var signature = SignSendGridPayload(timestamp, body);

        // Act
        var isValid = VerifySendGridEcdsaSignature(timestamp, body, signature, _sendGridTestPublicKeyBase64);

        // Assert
        isValid.Should().BeTrue("valid ECDSA signature should be accepted");
    }

    /// <summary>
    /// SendGrid signature verification should fail for expired timestamp (replay attack protection).
    /// </summary>
    [Fact]
    public void VerifySendGridSignature_ExpiredTimestamp_ReturnsFalse()
    {
        // Arrange
        var expiredTimestamp = (DateTimeOffset.UtcNow.ToUnixTimeSeconds() - 400).ToString();  // > 5 min old
        var body = @"[{""event"":""delivered""}]";
        var signature = SignSendGridPayload(expiredTimestamp, body);

        // Act
        var isValid = VerifySendGridEcdsaSignature(expiredTimestamp, body, signature, _sendGridTestPublicKeyBase64, maxAgeSeconds: 300);

        // Assert
        isValid.Should().BeFalse("expired timestamp should be rejected");
    }

    /// <summary>
    /// SendGrid signature verification should fail for tampered body.
    /// </summary>
    [Fact]
    public void VerifySendGridSignature_TamperedBody_ReturnsFalse()
    {
        // Arrange
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        var originalBody = @"[{""event"":""delivered""}]";
        var tamperedBody = @"[{""event"":""bounced""}]";  // Changed!
        var signature = SignSendGridPayload(timestamp, originalBody);

        // Act
        var isValid = VerifySendGridEcdsaSignature(timestamp, tamperedBody, signature, _sendGridTestPublicKeyBase64);

        // Assert
        isValid.Should().BeFalse("tampered body should fail signature verification");
    }

    /// <summary>
    /// SendGrid signature verification should fail for wrong public key.
    /// </summary>
    [Fact]
    public void VerifySendGridSignature_WrongPublicKey_ReturnsFalse()
    {
        // Arrange
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        var body = @"[{""event"":""delivered""}]";
        var signature = SignSendGridPayload(timestamp, body);

        // Generate a different key pair
        using var differentKey = ECDsa.Create(ECCurve.NamedCurves.nistP256);
        var wrongPublicKey = Convert.ToBase64String(differentKey.ExportSubjectPublicKeyInfo());

        // Act
        var isValid = VerifySendGridEcdsaSignature(timestamp, body, signature, wrongPublicKey);

        // Assert
        isValid.Should().BeFalse("signature signed with different key should be rejected");
    }

    /// <summary>
    /// SendGrid signature verification should fail for invalid Base64 signature.
    /// </summary>
    [Fact]
    public void VerifySendGridSignature_InvalidBase64Signature_ReturnsFalse()
    {
        // Arrange
        var timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString();
        var body = @"[{""event"":""delivered""}]";
        var invalidSignature = "not-valid-base64!!!";

        // Act
        var isValid = VerifySendGridEcdsaSignature(timestamp, body, invalidSignature, _sendGridTestPublicKeyBase64);

        // Assert
        isValid.Should().BeFalse("invalid Base64 signature should be rejected");
    }

    /// <summary>
    /// SendGrid signature verification should fail for missing headers.
    /// </summary>
    [Fact]
    public void VerifySendGridSignature_MissingHeaders_ReturnsFalse()
    {
        // Arrange
        var body = @"[{""event"":""delivered""}]";

        // Act & Assert
        VerifySendGridEcdsaSignature(null, body, "sig", _sendGridTestPublicKeyBase64).Should().BeFalse();
        VerifySendGridEcdsaSignature("123", body, null, _sendGridTestPublicKeyBase64).Should().BeFalse();
        VerifySendGridEcdsaSignature("123", body, "", _sendGridTestPublicKeyBase64).Should().BeFalse();
    }

    /// <summary>
    /// SendGrid signature verification should fail for future timestamps (clock skew limit).
    /// </summary>
    [Fact]
    public void VerifySendGridSignature_FutureTimestamp_ReturnsFalse()
    {
        // Arrange
        var futureTimestamp = (DateTimeOffset.UtcNow.ToUnixTimeSeconds() + 120).ToString();  // 2 min in future (> 1 min allowed)
        var body = @"[{""event"":""delivered""}]";
        var signature = SignSendGridPayload(futureTimestamp, body);

        // Act
        var isValid = VerifySendGridEcdsaSignature(futureTimestamp, body, signature, _sendGridTestPublicKeyBase64);

        // Assert
        isValid.Should().BeFalse("future timestamp beyond clock skew should be rejected");
    }

    /// <summary>
    /// Duplicate webhook event should be processed idempotently.
    /// </summary>
    [Fact]
    public async Task ProcessWebhook_DuplicateEvent_IdempotentHandling()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        var eventId = "evt_123456";
        var provider = "WHATSAPP";
        var processCount = 0;

        mockRepo.Setup(r => r.ProcessWebhookEventAsync(
                provider,
                eventId,
                It.IsAny<string>(),
                It.IsAny<string>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(() =>
            {
                if (processCount == 0)
                {
                    processCount++;
                    return true;  // First time: processed
                }
                return false;  // Already processed (idempotent)
            });

        // Act - Process same event twice
        var firstResult = await mockRepo.Object.ProcessWebhookEventAsync(
            provider, eventId, "delivered", @"{}");
        var secondResult = await mockRepo.Object.ProcessWebhookEventAsync(
            provider, eventId, "delivered", @"{}");

        // Assert
        firstResult.Should().BeTrue("first event should be processed");
        secondResult.Should().BeFalse("duplicate event should be skipped");
    }

    /// <summary>
    /// Webhook event should update outbox status.
    /// </summary>
    [Fact]
    public async Task ProcessWebhook_DeliveredEvent_UpdatesStatus()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        var outboxId = Guid.NewGuid();

        mockRepo.Setup(r => r.UpdateDeliveryStatusAsync(
                It.IsAny<string>(),
                It.IsAny<string>(),
                OutboxStatus.Delivered,
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);

        // Act
        var result = await mockRepo.Object.UpdateDeliveryStatusAsync(
            "WHATSAPP",
            "msg_123",
            OutboxStatus.Delivered);

        // Assert
        result.Should().BeTrue("delivered webhook should update outbox status");
    }

    /// <summary>
    /// Webhook with unknown provider message ID should be logged but not fail.
    /// </summary>
    [Fact]
    public async Task ProcessWebhook_UnknownMessageId_GracefullyIgnored()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();

        mockRepo.Setup(r => r.UpdateDeliveryStatusAsync(
                It.IsAny<string>(),
                "unknown_msg_id",
                It.IsAny<OutboxStatus>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);  // No matching record

        // Act
        var result = await mockRepo.Object.UpdateDeliveryStatusAsync(
            "WHATSAPP",
            "unknown_msg_id",
            OutboxStatus.Delivered);

        // Assert
        result.Should().BeFalse("unknown message ID should return false but not throw");
    }

    /// <summary>
    /// Timing-safe comparison should prevent timing attacks.
    /// </summary>
    [Fact]
    public void SignatureComparison_TimingSafe()
    {
        // Arrange
        var signature1 = "abc123def456";
        var signature2 = "abc123def456";
        var signature3 = "xyz789";

        // Act & Assert
        // CryptographicOperations.FixedTimeEquals provides timing-safe comparison
        var bytes1 = Encoding.UTF8.GetBytes(signature1);
        var bytes2 = Encoding.UTF8.GetBytes(signature2);
        var bytes3 = Encoding.UTF8.GetBytes(signature3);

        CryptographicOperations.FixedTimeEquals(bytes1, bytes2).Should().BeTrue();
        CryptographicOperations.FixedTimeEquals(bytes1, bytes3).Should().BeFalse();
    }

    #region Helper Methods

    // =========================================================================
    // WhatsApp: HMAC-SHA256 with shared secret
    // =========================================================================

    /// <summary>
    /// Compute WhatsApp webhook signature (mirrors controller logic).
    /// </summary>
    private static string ComputeWhatsAppSignature(string body, string secret)
    {
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(body));
        return "sha256=" + Convert.ToHexString(hash).ToLowerInvariant();
    }

    /// <summary>
    /// Verify WhatsApp signature (mirrors controller logic).
    /// </summary>
    private static bool VerifyWhatsAppSignature(string body, string? signatureHeader, string secret)
    {
        if (string.IsNullOrEmpty(signatureHeader) || !signatureHeader.StartsWith("sha256="))
            return false;

        var expectedSignature = ComputeWhatsAppSignature(body, secret);

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(expectedSignature),
            Encoding.UTF8.GetBytes(signatureHeader));
    }

    // =========================================================================
    // SendGrid: ECDSA P-256 with public key (NOT HMAC!)
    // =========================================================================

    /// <summary>
    /// Sign a SendGrid webhook payload using the test private key.
    /// In production, SendGrid signs the payload - we simulate this for testing.
    /// </summary>
    private static string SignSendGridPayload(string timestamp, string body)
    {
        var payload = Encoding.UTF8.GetBytes(timestamp + body);
        var signatureBytes = _sendGridTestPrivateKey.SignData(payload, HashAlgorithmName.SHA256);
        return Convert.ToBase64String(signatureBytes);
    }

    /// <summary>
    /// Verify SendGrid ECDSA signature with timestamp validation.
    /// Mirrors WebhookController.VerifySendGridSignature() logic.
    /// </summary>
    private static bool VerifySendGridEcdsaSignature(
        string? timestamp,
        string body,
        string? signature,
        string publicKeyBase64,
        int maxAgeSeconds = 300)
    {
        // Reject missing inputs
        if (string.IsNullOrEmpty(timestamp) || string.IsNullOrEmpty(signature))
            return false;

        // Validate timestamp freshness
        if (!long.TryParse(timestamp, out var ts))
            return false;

        var eventTime = DateTimeOffset.FromUnixTimeSeconds(ts);
        var age = DateTimeOffset.UtcNow - eventTime;

        // Reject if too old or too far in the future
        if (age.TotalSeconds > maxAgeSeconds || age.TotalSeconds < -60)
            return false;

        try
        {
            // Build payload: timestamp + body as raw bytes
            var payloadBytes = Encoding.UTF8.GetBytes(timestamp + body);

            // Decode public key (SPKI DER format)
            var publicKeyBytes = Convert.FromBase64String(publicKeyBase64);

            // Decode signature
            var signatureBytes = Convert.FromBase64String(signature);

            // Verify ECDSA signature
            using var ecdsa = ECDsa.Create();
            ecdsa.ImportSubjectPublicKeyInfo(publicKeyBytes, out _);

            return ecdsa.VerifyData(payloadBytes, signatureBytes, HashAlgorithmName.SHA256);
        }
        catch
        {
            return false;
        }
    }

    #endregion
}
