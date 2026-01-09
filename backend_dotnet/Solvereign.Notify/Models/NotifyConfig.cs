// =============================================================================
// SOLVEREIGN V4.1 - Notification Configuration
// =============================================================================

namespace Solvereign.Notify.Models;

/// <summary>
/// Worker configuration.
/// </summary>
public sealed class NotifyWorkerConfig
{
    public const string SectionName = "NotifyWorker";

    /// <summary>Poll interval in seconds.</summary>
    public int PollIntervalSeconds { get; set; } = 5;

    /// <summary>Messages per batch.</summary>
    public int BatchSize { get; set; } = 10;

    /// <summary>Max parallel sends within a batch.</summary>
    public int MaxParallelSends { get; set; } = 5;

    /// <summary>Max retry attempts before DEAD.</summary>
    public int MaxAttempts { get; set; } = 5;

    /// <summary>Base backoff in seconds (exponential: base * 5^attempt).</summary>
    public int BaseBackoffSeconds { get; set; } = 60;

    /// <summary>Lock duration in seconds for claimed messages.</summary>
    public int LockDurationSeconds { get; set; } = 300;

    /// <summary>Reaper interval in seconds (for stuck SENDING messages).</summary>
    public int ReaperIntervalSeconds { get; set; } = 60;

    /// <summary>Max age for stuck messages before release.</summary>
    public int StuckMaxAgeMinutes { get; set; } = 10;

    /// <summary>Worker instance ID (for lock tracking).</summary>
    public string WorkerId { get; set; } = Environment.MachineName + "-" + Guid.NewGuid().ToString("N")[..8];

    /// <summary>Graceful shutdown timeout in seconds.</summary>
    public int ShutdownTimeoutSeconds { get; set; } = 30;
}

/// <summary>
/// WhatsApp provider configuration.
/// </summary>
public sealed class WhatsAppConfig
{
    public const string SectionName = "WhatsApp";

    public string? PhoneNumberId { get; set; }
    public string? AccessToken { get; set; }
    public string ApiVersion { get; set; } = "v18.0";
    public string? WebhookVerifyToken { get; set; }
    public string? WebhookSecret { get; set; }  // For signature verification
    public int TimeoutSeconds { get; set; } = 30;
}

/// <summary>
/// SendGrid provider configuration.
/// </summary>
public sealed class SendGridConfig
{
    public const string SectionName = "SendGrid";

    public string? ApiKey { get; set; }
    public string? FromEmail { get; set; }
    public string FromName { get; set; } = "SOLVEREIGN";

    /// <summary>
    /// SendGrid Signed Event Webhook PUBLIC KEY (ECDSA P-256).
    /// Obtained from SendGrid Settings → Mail Settings → Event Webhook → Signature Verification.
    /// Format: Base64-encoded public key (NOT PEM format).
    /// Example: "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE..."
    /// </summary>
    public string? WebhookPublicKey { get; set; }

    /// <summary>
    /// Secondary public key for key rotation (dual-key window).
    /// During rotation: set new key as primary, keep old key as secondary for 1 hour.
    /// After rotation: clear this field.
    /// </summary>
    public string? WebhookPublicKeySecondary { get; set; }

    /// <summary>
    /// Maximum age in seconds for webhook timestamps (replay attack protection).
    /// Default: 300 (5 minutes).
    /// </summary>
    public int WebhookMaxAgeSeconds { get; set; } = 300;

    public int TimeoutSeconds { get; set; } = 30;
}

/// <summary>
/// Tenant notification preferences (quiet hours, rate limits).
/// </summary>
public sealed class TenantNotifyConfig
{
    /// <summary>Do not send between these hours (local tenant time).</summary>
    public TimeOnly QuietHoursStart { get; set; } = new(22, 0);
    public TimeOnly QuietHoursEnd { get; set; } = new(6, 0);
    public string Timezone { get; set; } = "Europe/Vienna";

    /// <summary>Max messages per minute per provider.</summary>
    public int RateLimitPerMinute { get; set; } = 100;

    /// <summary>Check if current time is in quiet hours.</summary>
    public bool IsQuietHours(DateTimeOffset now)
    {
        try
        {
            var tz = TimeZoneInfo.FindSystemTimeZoneById(Timezone);
            var localTime = TimeZoneInfo.ConvertTime(now, tz).TimeOfDay;
            var localTimeOnly = TimeOnly.FromTimeSpan(localTime);

            // Handle overnight quiet hours (e.g., 22:00 - 06:00)
            if (QuietHoursStart > QuietHoursEnd)
            {
                return localTimeOnly >= QuietHoursStart || localTimeOnly <= QuietHoursEnd;
            }
            return localTimeOnly >= QuietHoursStart && localTimeOnly <= QuietHoursEnd;
        }
        catch
        {
            return false;  // On timezone error, don't block sends
        }
    }
}
