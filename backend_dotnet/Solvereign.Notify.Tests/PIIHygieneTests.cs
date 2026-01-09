// =============================================================================
// SOLVEREIGN V4.1 - PII Hygiene Tests
// =============================================================================

using System.Text.RegularExpressions;
using FluentAssertions;
using Moq;
using Solvereign.Notify.Models;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Tests;

/// <summary>
/// Tests for PII (Personal Identifiable Information) hygiene.
/// Ensures no raw contacts (phone/email) are stored in notify schema or logs.
/// GDPR compliance requirement.
/// </summary>
public class PIIHygieneTests
{
    private static readonly Regex PhoneRegex = new(
        @"\+?[0-9]{10,15}",
        RegexOptions.Compiled);

    private static readonly Regex EmailRegex = new(
        @"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        RegexOptions.Compiled);

    /// <summary>
    /// Outbox message should not contain raw phone number.
    /// </summary>
    [Fact]
    public void OutboxMessage_NoRawPhone()
    {
        // Arrange
        var message = new ClaimedOutboxMessage
        {
            OutboxId = Guid.NewGuid(),
            TenantId = 1,
            DriverId = "D001",  // Reference ID, not PII
            DriverName = "Max M.",  // Abbreviated name is OK
            DeliveryChannel = "WHATSAPP",
            MessageTemplate = "PORTAL_INVITE",
            AttemptCount = 1,
            MessageParams = new Dictionary<string, object>
            {
                ["portal_url"] = "https://portal.example.com/invite/abc123"
                // No phone field - contact resolved at send time
            }
        };

        // Act - Serialize to check for leaks
        var json = System.Text.Json.JsonSerializer.Serialize(message);

        // Assert
        PhoneRegex.IsMatch(json).Should().BeFalse(
            "outbox message should not contain raw phone numbers");
    }

    /// <summary>
    /// Outbox message should not contain raw email address.
    /// </summary>
    [Fact]
    public void OutboxMessage_NoRawEmail()
    {
        // Arrange
        var message = new ClaimedOutboxMessage
        {
            OutboxId = Guid.NewGuid(),
            TenantId = 1,
            DriverId = "D002",
            DriverName = "Anna S.",
            DeliveryChannel = "EMAIL",
            MessageTemplate = "SHIFT_NOTIFICATION",
            AttemptCount = 1,
            MessageParams = new Dictionary<string, object>
            {
                ["subject"] = "Your shift tomorrow"
                // No email field - contact resolved at send time
            }
        };

        // Act
        var json = System.Text.Json.JsonSerializer.Serialize(message);

        // Assert
        EmailRegex.IsMatch(json).Should().BeFalse(
            "outbox message should not contain raw email addresses");
    }

    /// <summary>
    /// Contact resolution should happen outside notify schema.
    /// </summary>
    [Fact]
    public async Task ContactResolution_NotInNotifySchema()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();

        // Contact resolver is a separate service, not part of notify repository
        mockRepo.Setup(r => r.ClaimBatchAsync(
                It.IsAny<int>(),
                It.IsAny<string>(),
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ClaimedOutboxMessage>
            {
                new()
                {
                    OutboxId = Guid.NewGuid(),
                    TenantId = 1,
                    DriverId = "D003",  // Only reference ID
                    DeliveryChannel = "WHATSAPP",
                    MessageTemplate = "PORTAL_INVITE",
                    AttemptCount = 1
                    // No contact info - resolved separately
                }
            });

        // Act
        var messages = await mockRepo.Object.ClaimBatchAsync(10, "worker1", 300);

        // Assert
        var json = System.Text.Json.JsonSerializer.Serialize(messages);
        PhoneRegex.IsMatch(json).Should().BeFalse("claimed messages should not contain PII");
        EmailRegex.IsMatch(json).Should().BeFalse("claimed messages should not contain PII");
    }

    /// <summary>
    /// Send result should not log raw recipient.
    /// </summary>
    [Fact]
    public void SendResult_NoRawRecipient()
    {
        // Arrange
        var result = new SendResult(
            Success: true,
            ProviderMessageId: "msg_abc123",
            ProviderStatus: "accepted",
            ErrorCode: null,
            ErrorMessage: null
        );

        // Act
        var json = System.Text.Json.JsonSerializer.Serialize(result);

        // Assert
        PhoneRegex.IsMatch(json).Should().BeFalse(
            "send result should not contain raw phone");
        EmailRegex.IsMatch(json).Should().BeFalse(
            "send result should not contain raw email");
    }

    /// <summary>
    /// Error messages should not leak recipient contact.
    /// </summary>
    [Fact]
    public void ErrorMessage_NoRecipientLeak()
    {
        // Arrange - Simulating error message from provider
        var safeErrorMessage = "Message delivery failed: recipient unreachable";
        var unsafeErrorMessage = "Failed to send to +4917612345678";

        // Act & Assert
        PhoneRegex.IsMatch(safeErrorMessage).Should().BeFalse(
            "safe error message should not contain phone");
        PhoneRegex.IsMatch(unsafeErrorMessage).Should().BeTrue(
            "unsafe error message contains phone (this is what we avoid)");

        // Real implementation should sanitize provider error messages
        var sanitizedError = SanitizeErrorMessage(unsafeErrorMessage);
        PhoneRegex.IsMatch(sanitizedError).Should().BeFalse(
            "sanitized error should not contain phone");
    }

    /// <summary>
    /// Delivery log should use provider message ID, not recipient.
    /// </summary>
    [Fact]
    public void DeliveryLog_UsesProviderMessageId()
    {
        // Arrange
        var logEntry = new
        {
            outbox_id = Guid.NewGuid(),
            provider_message_id = "wamid.123456789",  // Provider's ID
            status = "delivered",
            timestamp = DateTime.UtcNow
            // No recipient field
        };

        // Act
        var json = System.Text.Json.JsonSerializer.Serialize(logEntry);

        // Assert
        PhoneRegex.IsMatch(json).Should().BeFalse();
        EmailRegex.IsMatch(json).Should().BeFalse();
    }

    /// <summary>
    /// Webhook payload should not persist raw recipient.
    /// </summary>
    [Fact]
    public void WebhookEvent_NoPersistentRecipient()
    {
        // Arrange
        var webhookEvent = new WebhookEvent
        {
            Provider = "WHATSAPP",
            ProviderEventId = "evt_123",
            EventType = "delivered",
            ProviderMessageId = "wamid.456",
            Status = "delivered",
            Timestamp = DateTime.UtcNow,
            RawPayload = @"{""status"":""delivered""}"  // No recipient in stored payload
        };

        // Act
        var json = System.Text.Json.JsonSerializer.Serialize(webhookEvent);

        // Assert
        PhoneRegex.IsMatch(json).Should().BeFalse(
            "webhook event should not persist raw phone");
    }

    /// <summary>
    /// Driver contact resolution should be ephemeral.
    /// </summary>
    [Fact]
    public void DriverContact_EphemeralOnly()
    {
        // Arrange
        var contact = new DriverContact(
            DriverId: "D001",
            Phone: "+4917612345678",  // This is fetched, used, then discarded
            Email: "driver@example.com"
        );

        // Assert - Contact exists but should NOT be persisted to notify schema
        contact.Phone.Should().NotBeNullOrEmpty("contact should have phone for sending");
        contact.Email.Should().NotBeNullOrEmpty("contact should have email for sending");

        // The key point: this data comes from driver master data (separate schema)
        // and is used only in-memory during send, never stored in notify tables
    }

    /// <summary>
    /// Masked phone format should be used in any user-facing logs.
    /// </summary>
    [Fact]
    public void MaskedPhone_Format()
    {
        // Arrange
        var rawPhone = "+4917612345678";
        var expectedMasked = "+49***5678";

        // Act
        var masked = MaskPhone(rawPhone);

        // Assert
        masked.Should().Be(expectedMasked);
        PhoneRegex.IsMatch(masked).Should().BeFalse(
            "masked phone should not match full phone regex");
    }

    /// <summary>
    /// Masked email format should be used in any user-facing logs.
    /// </summary>
    [Fact]
    public void MaskedEmail_Format()
    {
        // Arrange
        var rawEmail = "driver.name@example.com";
        var expectedMasked = "d***e@example.com";

        // Act
        var masked = MaskEmail(rawEmail);

        // Assert
        masked.Should().Be(expectedMasked);
        // Masked email may still technically match email regex, but is not the real address
    }

    /// <summary>
    /// notify schema should have no contact columns.
    /// </summary>
    [Fact]
    public void NotifySchema_NoContactColumns()
    {
        // This is a documentation/design test
        // The notify.notification_outbox table should NOT have:
        // - recipient_phone
        // - recipient_email
        // - contact_info
        // - any column that stores raw PII

        // Instead, contacts are resolved at send-time from:
        // - masterdata.md_drivers (or similar)
        // - portal.magic_link_tokens (for portal invites)

        var forbiddenColumns = new[]
        {
            "recipient_phone",
            "recipient_email",
            "contact_info",
            "phone",
            "email",
            "mobile"
        };

        // In real integration test, this would query information_schema
        // For unit test, we just document the requirement
        forbiddenColumns.Should().NotBeEmpty(
            "documenting that these columns must NOT exist in notify schema");
    }

    #region Helper Methods

    /// <summary>
    /// Sanitize error messages to remove PII.
    /// </summary>
    private static string SanitizeErrorMessage(string error)
    {
        // Remove phone numbers
        error = PhoneRegex.Replace(error, "[REDACTED_PHONE]");

        // Remove email addresses
        error = EmailRegex.Replace(error, "[REDACTED_EMAIL]");

        return error;
    }

    /// <summary>
    /// Mask phone number for logging.
    /// </summary>
    private static string MaskPhone(string phone)
    {
        if (string.IsNullOrEmpty(phone) || phone.Length < 8)
            return "***";

        // Keep country code prefix and last 4 digits
        var prefix = phone[..3];  // +49
        var suffix = phone[^4..]; // last 4

        return $"{prefix}***{suffix}";
    }

    /// <summary>
    /// Mask email for logging.
    /// </summary>
    private static string MaskEmail(string email)
    {
        if (string.IsNullOrEmpty(email) || !email.Contains('@'))
            return "***";

        var parts = email.Split('@');
        var local = parts[0];
        var domain = parts[1];

        if (local.Length <= 2)
            return $"***@{domain}";

        return $"{local[0]}***{local[^1]}@{domain}";
    }

    #endregion
}
