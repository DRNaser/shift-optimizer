// =============================================================================
// SOLVEREIGN V4.1 - Notification Models
// =============================================================================

namespace Solvereign.Notify.Models;

/// <summary>
/// Outbox message status state machine.
/// PENDING -> SENDING -> SENT -> DELIVERED
/// PENDING -> SENDING -> RETRYING -> SENDING -> ... -> DEAD
/// </summary>
public enum OutboxStatus
{
    Pending,
    Sending,
    Sent,
    Delivered,
    Retrying,
    Skipped,
    Failed,
    Dead,
    Cancelled
}

/// <summary>
/// Delivery channel types.
/// </summary>
public enum DeliveryChannel
{
    WhatsApp,
    Email,
    Sms,
    Push
}

/// <summary>
/// Skip reason codes for SKIPPED status.
/// </summary>
public static class SkipReason
{
    public const string OptOut = "OPT_OUT";
    public const string QuietHours = "QUIET_HOURS";
    public const string NoContact = "NO_CONTACT";
    public const string ConsentMissing = "CONSENT_MISSING";
    public const string InvalidContact = "INVALID_CONTACT";
}

/// <summary>
/// Error codes for provider failures.
/// </summary>
public static class ErrorCodes
{
    // Transient (retryable)
    public const string ProviderTimeout = "PROVIDER_TIMEOUT";
    public const string Provider429 = "PROVIDER_429";
    public const string Provider5xx = "PROVIDER_5XX";
    public const string NetworkError = "NETWORK_ERROR";
    public const string LockExpired = "LOCK_EXPIRED";

    // Permanent (non-retryable)
    public const string ProviderInvalidRecipient = "PROVIDER_INVALID_RECIPIENT";
    public const string ProviderTemplateError = "PROVIDER_TEMPLATE_ERROR";
    public const string ProviderAuthError = "PROVIDER_AUTH_ERROR";
    public const string ProviderBounced = "PROVIDER_BOUNCED";
    public const string ProviderBlocked = "PROVIDER_BLOCKED";
}

/// <summary>
/// Outbox message claimed by worker for processing.
/// </summary>
public sealed record ClaimedOutboxMessage
{
    public required Guid OutboxId { get; init; }
    public required int TenantId { get; init; }
    public required string DriverId { get; init; }
    public string? DriverName { get; init; }
    public required string DeliveryChannel { get; init; }
    public required string MessageTemplate { get; init; }
    public Dictionary<string, object>? MessageParams { get; init; }
    public string? PortalUrl { get; init; }
    public required int AttemptCount { get; init; }
    public Guid? SnapshotId { get; init; }
    public Guid? JobId { get; init; }

    public DeliveryChannel Channel => DeliveryChannel switch
    {
        "WHATSAPP" => Models.DeliveryChannel.WhatsApp,
        "EMAIL" => Models.DeliveryChannel.Email,
        "SMS" => Models.DeliveryChannel.Sms,
        "PUSH" => Models.DeliveryChannel.Push,
        _ => throw new ArgumentException($"Unknown channel: {DeliveryChannel}")
    };
}

/// <summary>
/// Result from provider send attempt.
/// </summary>
public sealed record SendResult
{
    public required bool Success { get; init; }
    public string? ProviderMessageId { get; init; }
    public string? ProviderStatus { get; init; }
    public string? ErrorCode { get; init; }
    public string? ErrorMessage { get; init; }
    public bool IsRetryable { get; init; } = true;
    public TimeSpan? RetryAfter { get; init; }

    public static SendResult Ok(string messageId, string status = "SENT") => new()
    {
        Success = true,
        ProviderMessageId = messageId,
        ProviderStatus = status
    };

    public static SendResult TransientError(string errorCode, string? message = null, TimeSpan? retryAfter = null) => new()
    {
        Success = false,
        ErrorCode = errorCode,
        ErrorMessage = message,
        IsRetryable = true,
        RetryAfter = retryAfter
    };

    public static SendResult PermanentError(string errorCode, string? message = null) => new()
    {
        Success = false,
        ErrorCode = errorCode,
        ErrorMessage = message,
        IsRetryable = false
    };
}

/// <summary>
/// Driver contact info (transient, from masterdata, never persisted in notify).
/// </summary>
public sealed record DriverContact
{
    public required string DriverId { get; init; }
    public string? PhoneNumber { get; init; }
    public string? Email { get; init; }
    public bool WhatsAppOptedIn { get; init; }
    public bool EmailOptedIn { get; init; }
    public bool SmsOptedIn { get; init; }
    public TimeOnly? QuietHoursStart { get; init; }
    public TimeOnly? QuietHoursEnd { get; init; }
    public string Timezone { get; init; } = "Europe/Vienna";
}

/// <summary>
/// Webhook event from provider.
/// </summary>
public sealed record WebhookEvent
{
    public required string Provider { get; init; }
    public required string ProviderEventId { get; init; }
    public required string EventType { get; init; }
    public required DateTimeOffset EventTimestamp { get; init; }
    public string? ProviderMessageId { get; init; }
    public string? PayloadHash { get; init; }
}

/// <summary>
/// Rate limit check result.
/// </summary>
public sealed record RateLimitResult
{
    public required bool Allowed { get; init; }
    public required int TokensRemaining { get; init; }
    public int RetryAfterSeconds { get; init; }
}

/// <summary>
/// Worker health metrics.
/// </summary>
public sealed record WorkerHealthMetrics
{
    public int PendingCount { get; init; }
    public int SendingCount { get; init; }
    public int DeadCount { get; init; }
    public TimeSpan? OldestPendingAge { get; init; }
    public int StuckCount { get; init; }
    public DateTimeOffset LastPollTime { get; init; }
    public int BatchesProcessed { get; init; }
    public int MessagesSent { get; init; }
    public int MessagesFailed { get; init; }
}
