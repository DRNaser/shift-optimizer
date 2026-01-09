// =============================================================================
// SOLVEREIGN V4.1 - Webhook Controllers (Signature Verification)
// =============================================================================

using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Solvereign.Notify.Models;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Api;

/// <summary>
/// Webhook endpoints for provider delivery callbacks.
/// SECURITY: All webhooks verify signatures before processing.
/// </summary>
[ApiController]
[Route("api/notify/webhooks")]
public class WebhookController : ControllerBase
{
    private readonly INotifyRepository _repository;
    private readonly WhatsAppConfig _whatsAppConfig;
    private readonly SendGridConfig _sendGridConfig;
    private readonly ILogger<WebhookController> _logger;

    public WebhookController(
        INotifyRepository repository,
        IOptions<WhatsAppConfig> whatsAppConfig,
        IOptions<SendGridConfig> sendGridConfig,
        ILogger<WebhookController> logger)
    {
        _repository = repository;
        _whatsAppConfig = whatsAppConfig.Value;
        _sendGridConfig = sendGridConfig.Value;
        _logger = logger;
    }

    // =========================================================================
    // WhatsApp Webhook
    // =========================================================================

    /// <summary>
    /// WhatsApp webhook verification (GET).
    /// Meta sends this to verify webhook URL during setup.
    /// </summary>
    [HttpGet("whatsapp")]
    public IActionResult VerifyWhatsApp(
        [FromQuery(Name = "hub.mode")] string hubMode,
        [FromQuery(Name = "hub.verify_token")] string hubVerifyToken,
        [FromQuery(Name = "hub.challenge")] string hubChallenge)
    {
        if (hubMode == "subscribe" && hubVerifyToken == _whatsAppConfig.WebhookVerifyToken)
        {
            _logger.LogInformation("WhatsApp webhook verified");
            return Ok(int.Parse(hubChallenge));
        }

        _logger.LogWarning("WhatsApp webhook verification failed. InvalidToken");
        return Forbid();
    }

    /// <summary>
    /// WhatsApp webhook handler (POST).
    /// SECURITY: Verifies X-Hub-Signature-256 header.
    /// </summary>
    [HttpPost("whatsapp")]
    public async Task<IActionResult> HandleWhatsApp(CancellationToken ct)
    {
        // Read raw body for signature verification
        using var reader = new StreamReader(Request.Body);
        var body = await reader.ReadToEndAsync(ct);

        // Verify signature
        var signature = Request.Headers["X-Hub-Signature-256"].FirstOrDefault();
        if (!VerifyWhatsAppSignature(body, signature))
        {
            _logger.LogWarning("WhatsApp webhook signature verification failed");
            return Unauthorized(new { error = "invalid_signature" });
        }

        // Parse events
        var events = ParseWhatsAppWebhook(body);

        _logger.LogInformation("WhatsApp webhook received. Events: {Count}", events.Count);

        // Process events idempotently
        var processedCount = 0;
        foreach (var evt in events)
        {
            // For WhatsApp, we need tenant_id - derive from outbox lookup or use default
            // In production, you'd look up the tenant from provider_message_id
            var tenantId = await GetTenantIdFromMessageAsync(evt.ProviderMessageId, ct);
            if (tenantId.HasValue)
            {
                var isNew = await _repository.ProcessWebhookEventAsync(evt, tenantId.Value, ct);
                if (isNew) processedCount++;
            }
        }

        return Ok(new { received = true, events_processed = processedCount });
    }

    private bool VerifyWhatsAppSignature(string body, string? signatureHeader)
    {
        if (string.IsNullOrEmpty(_whatsAppConfig.WebhookSecret))
        {
            _logger.LogWarning("WhatsApp webhook secret not configured - skipping verification");
            return true;  // In dev mode, allow without signature
        }

        if (string.IsNullOrEmpty(signatureHeader) || !signatureHeader.StartsWith("sha256="))
        {
            return false;
        }

        var signature = signatureHeader["sha256=".Length..];
        var expectedSignature = ComputeHmacSha256(body, _whatsAppConfig.WebhookSecret);

        return CryptographicOperations.FixedTimeEquals(
            Convert.FromHexString(signature),
            Convert.FromHexString(expectedSignature));
    }

    private static List<WebhookEvent> ParseWhatsAppWebhook(string body)
    {
        var events = new List<WebhookEvent>();

        try
        {
            var doc = JsonDocument.Parse(body);
            var entries = doc.RootElement.GetProperty("entry");

            foreach (var entry in entries.EnumerateArray())
            {
                var changes = entry.GetProperty("changes");
                foreach (var change in changes.EnumerateArray())
                {
                    var value = change.GetProperty("value");
                    if (!value.TryGetProperty("statuses", out var statuses))
                        continue;

                    foreach (var status in statuses.EnumerateArray())
                    {
                        var statusValue = status.GetProperty("status").GetString()?.ToUpperInvariant();
                        var eventType = statusValue switch
                        {
                            "SENT" => "SENT",
                            "DELIVERED" => "DELIVERED",
                            "READ" => "READ",
                            "FAILED" => "FAILED",
                            _ => null
                        };

                        if (eventType == null) continue;

                        events.Add(new WebhookEvent
                        {
                            Provider = "WHATSAPP",
                            ProviderEventId = status.GetProperty("id").GetString() + "_" + statusValue,
                            EventType = eventType,
                            EventTimestamp = DateTimeOffset.FromUnixTimeSeconds(
                                long.Parse(status.GetProperty("timestamp").GetString() ?? "0")),
                            ProviderMessageId = status.GetProperty("id").GetString(),
                            PayloadHash = ComputeSha256(body)[..16]  // Truncated hash for debugging
                        });
                    }
                }
            }
        }
        catch (Exception ex)
        {
            // Log but don't fail - return empty list
            Console.Error.WriteLine($"WhatsApp webhook parse error: {ex.Message}");
        }

        return events;
    }

    // =========================================================================
    // SendGrid Webhook
    // =========================================================================

    /// <summary>
    /// SendGrid Event Webhook handler.
    /// SECURITY: Verifies signature header if configured.
    /// </summary>
    [HttpPost("sendgrid")]
    public async Task<IActionResult> HandleSendGrid(CancellationToken ct)
    {
        // Read raw body
        using var reader = new StreamReader(Request.Body);
        var body = await reader.ReadToEndAsync(ct);

        // Verify signature if configured
        var signature = Request.Headers["X-Twilio-Email-Event-Webhook-Signature"].FirstOrDefault();
        var timestamp = Request.Headers["X-Twilio-Email-Event-Webhook-Timestamp"].FirstOrDefault();

        if (!VerifySendGridSignature(body, signature, timestamp))
        {
            _logger.LogWarning("SendGrid webhook signature verification failed");
            return Unauthorized(new { error = "invalid_signature" });
        }

        // Parse events
        var events = ParseSendGridWebhook(body);

        _logger.LogInformation("SendGrid webhook received. Events: {Count}", events.Count);

        // Process events idempotently
        var processedCount = 0;
        foreach (var evt in events)
        {
            var tenantId = await GetTenantIdFromMessageAsync(evt.ProviderMessageId, ct);
            if (tenantId.HasValue)
            {
                var isNew = await _repository.ProcessWebhookEventAsync(evt, tenantId.Value, ct);
                if (isNew) processedCount++;
            }
        }

        return Ok(new { received = true, events_processed = processedCount });
    }

    /// <summary>
    /// Verify SendGrid Signed Event Webhook signature using ECDSA P-256.
    /// Supports dual-key rotation: tries primary key first, then secondary if configured.
    /// See: https://docs.sendgrid.com/for-developers/tracking-events/getting-started-event-webhook-security-features
    /// </summary>
    /// <param name="rawBody">Raw request body bytes (MUST be original bytes, not re-serialized JSON)</param>
    /// <param name="signature">X-Twilio-Email-Event-Webhook-Signature header (Base64 ECDSA signature)</param>
    /// <param name="timestamp">X-Twilio-Email-Event-Webhook-Timestamp header (Unix timestamp string)</param>
    private bool VerifySendGridSignature(string rawBody, string? signature, string? timestamp)
    {
        // Dev mode: skip verification if no public key configured
        if (string.IsNullOrEmpty(_sendGridConfig.WebhookPublicKey))
        {
            _logger.LogWarning("SendGrid webhook public key not configured - SKIPPING VERIFICATION (dev mode only!)");
            return true;
        }

        // Reject missing headers
        if (string.IsNullOrEmpty(signature) || string.IsNullOrEmpty(timestamp))
        {
            _logger.LogWarning("SendGrid webhook missing signature or timestamp header");
            return false;
        }

        // Validate timestamp freshness first (applies to all keys)
        if (!ValidateTimestamp(timestamp, out var payloadBytes, rawBody))
        {
            return false;
        }

        // Decode signature once (applies to all keys)
        byte[] signatureBytes;
        try
        {
            signatureBytes = Convert.FromBase64String(signature);
        }
        catch (FormatException)
        {
            _logger.LogWarning("SendGrid webhook signature is not valid Base64");
            return false;
        }

        // Try primary key
        if (VerifyWithPublicKey(payloadBytes, signatureBytes, _sendGridConfig.WebhookPublicKey, "primary"))
        {
            return true;
        }

        // Try secondary key (dual-key rotation window)
        if (!string.IsNullOrEmpty(_sendGridConfig.WebhookPublicKeySecondary))
        {
            _logger.LogInformation("SendGrid primary key failed, trying secondary (key rotation mode)");
            if (VerifyWithPublicKey(payloadBytes, signatureBytes, _sendGridConfig.WebhookPublicKeySecondary, "secondary"))
            {
                return true;
            }
        }

        _logger.LogWarning("SendGrid webhook ECDSA signature verification FAILED (all keys)");
        return false;
    }

    /// <summary>
    /// Validate webhook timestamp freshness (replay attack protection).
    /// </summary>
    private bool ValidateTimestamp(string timestamp, out byte[] payloadBytes, string rawBody)
    {
        payloadBytes = Array.Empty<byte>();

        if (!long.TryParse(timestamp, out var ts))
        {
            _logger.LogWarning("SendGrid webhook timestamp invalid format");
            return false;
        }

        var eventTime = DateTimeOffset.FromUnixTimeSeconds(ts);
        var age = DateTimeOffset.UtcNow - eventTime;

        // Reject if too old (default 5 min) or from the future (> 1 min clock skew)
        if (age.TotalSeconds > _sendGridConfig.WebhookMaxAgeSeconds || age.TotalSeconds < -60)
        {
            _logger.LogWarning(
                "SendGrid webhook timestamp out of range. Age: {Age}s, Max: {Max}s",
                age.TotalSeconds, _sendGridConfig.WebhookMaxAgeSeconds);
            return false;
        }

        // Build payload: timestamp + rawBody (as raw bytes)
        payloadBytes = Encoding.UTF8.GetBytes(timestamp + rawBody);
        return true;
    }

    /// <summary>
    /// Verify ECDSA signature with a specific public key.
    /// </summary>
    private bool VerifyWithPublicKey(byte[] payloadBytes, byte[] signatureBytes, string publicKeyBase64, string keyName)
    {
        try
        {
            var publicKeyBytes = Convert.FromBase64String(publicKeyBase64);

            using var ecdsa = ECDsa.Create();
            ecdsa.ImportSubjectPublicKeyInfo(publicKeyBytes, out _);

            return ecdsa.VerifyData(payloadBytes, signatureBytes, HashAlgorithmName.SHA256);
        }
        catch (FormatException)
        {
            _logger.LogError("SendGrid webhook {KeyName} public key is not valid Base64", keyName);
            return false;
        }
        catch (CryptographicException ex)
        {
            _logger.LogDebug(ex, "SendGrid webhook {KeyName} key verification failed (expected during rotation)", keyName);
            return false;
        }
    }

    private static List<WebhookEvent> ParseSendGridWebhook(string body)
    {
        var events = new List<WebhookEvent>();

        try
        {
            var doc = JsonDocument.Parse(body);

            foreach (var element in doc.RootElement.EnumerateArray())
            {
                var sgEvent = element.GetProperty("event").GetString()?.ToLowerInvariant();
                var eventType = sgEvent switch
                {
                    "processed" or "deferred" => "SENT",
                    "delivered" => "DELIVERED",
                    "open" or "click" => "READ",
                    "bounce" or "blocked" or "dropped" or "spamreport" => "FAILED",
                    _ => null
                };

                if (eventType == null) continue;

                var messageId = element.GetProperty("sg_message_id").GetString() ?? "";
                // Remove .filter suffix
                var dotIndex = messageId.IndexOf('.');
                if (dotIndex > 0) messageId = messageId[..dotIndex];

                events.Add(new WebhookEvent
                {
                    Provider = "SENDGRID",
                    ProviderEventId = element.TryGetProperty("sg_event_id", out var eid)
                        ? eid.GetString() ?? Guid.NewGuid().ToString()
                        : Guid.NewGuid().ToString(),
                    EventType = eventType,
                    EventTimestamp = element.TryGetProperty("timestamp", out var ts)
                        ? DateTimeOffset.FromUnixTimeSeconds(ts.GetInt64())
                        : DateTimeOffset.UtcNow,
                    ProviderMessageId = messageId,
                    PayloadHash = ComputeSha256(body)[..16]
                });
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"SendGrid webhook parse error: {ex.Message}");
        }

        return events;
    }

    // =========================================================================
    // Helper Methods
    // =========================================================================

    private async Task<int?> GetTenantIdFromMessageAsync(string? providerMessageId, CancellationToken ct)
    {
        if (string.IsNullOrEmpty(providerMessageId))
            return null;

        // In production, look up tenant_id from outbox by provider_message_id
        // For now, return default tenant
        return 1;
    }

    private static string ComputeHmacSha256(string data, string secret)
    {
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(data));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    private static string ComputeSha256(string data)
    {
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(data));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
