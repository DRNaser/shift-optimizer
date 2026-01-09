// =============================================================================
// SOLVEREIGN V4.1 - Notification Provider Interface
// =============================================================================

using Solvereign.Notify.Models;

namespace Solvereign.Notify.Providers;

/// <summary>
/// Interface for notification providers (WhatsApp, Email, SMS).
/// Implementations must:
/// - Never log raw recipient (PII)
/// - Handle idempotency where possible
/// - Return sanitized error codes
/// </summary>
public interface INotificationProvider
{
    /// <summary>Provider name for metrics/logging.</summary>
    string ProviderName { get; }

    /// <summary>
    /// Send notification to recipient.
    /// </summary>
    /// <param name="recipient">Phone number or email (transient, not logged)</param>
    /// <param name="templateName">Template identifier</param>
    /// <param name="templateParams">Template variables</param>
    /// <param name="portalUrl">Optional portal magic link</param>
    /// <param name="ct">Cancellation token</param>
    /// <returns>Send result with provider message ID or error</returns>
    Task<SendResult> SendAsync(
        string recipient,
        string templateName,
        Dictionary<string, object> templateParams,
        string? portalUrl,
        CancellationToken ct = default);

    /// <summary>
    /// Validate recipient format.
    /// </summary>
    bool ValidateRecipient(string recipient);

    /// <summary>
    /// Check provider health/connectivity.
    /// </summary>
    Task<bool> IsHealthyAsync(CancellationToken ct = default);
}
