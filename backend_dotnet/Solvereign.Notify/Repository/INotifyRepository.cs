// =============================================================================
// SOLVEREIGN V4.1 - Notification Repository Interface
// =============================================================================

using Solvereign.Notify.Models;

namespace Solvereign.Notify.Repository;

/// <summary>
/// Repository interface for notification outbox operations.
/// All methods are atomic and concurrency-safe.
/// </summary>
public interface INotifyRepository
{
    /// <summary>
    /// Atomically claim a batch of messages for processing.
    /// Uses SELECT FOR UPDATE SKIP LOCKED for concurrency safety.
    /// </summary>
    Task<IReadOnlyList<ClaimedOutboxMessage>> ClaimBatchAsync(
        int batchSize,
        string workerId,
        int lockDurationSeconds,
        CancellationToken ct = default);

    /// <summary>
    /// Mark message as successfully sent.
    /// </summary>
    Task MarkSentAsync(
        Guid outboxId,
        string providerMessageId,
        string? providerStatus = null,
        CancellationToken ct = default);

    /// <summary>
    /// Mark message for retry with backoff.
    /// Returns false if moved to DEAD (max attempts exceeded).
    /// </summary>
    Task<bool> MarkRetryAsync(
        Guid outboxId,
        string errorCode,
        int baseBackoffSeconds = 60,
        int maxAttempts = 5,
        CancellationToken ct = default);

    /// <summary>
    /// Mark message as permanently dead.
    /// </summary>
    Task MarkDeadAsync(
        Guid outboxId,
        string errorCode,
        CancellationToken ct = default);

    /// <summary>
    /// Mark message as skipped (opt-out, quiet hours, etc.).
    /// </summary>
    Task MarkSkippedAsync(
        Guid outboxId,
        string skipReason,
        CancellationToken ct = default);

    /// <summary>
    /// Release stuck SENDING messages back to RETRYING.
    /// Returns count of released messages.
    /// </summary>
    Task<int> ReleaseStuckMessagesAsync(
        TimeSpan maxAge,
        CancellationToken ct = default);

    /// <summary>
    /// Requeue a DEAD message for retry.
    /// </summary>
    Task<bool> RequeueDeadMessageAsync(
        Guid outboxId,
        bool resetAttempts = false,
        CancellationToken ct = default);

    /// <summary>
    /// Process webhook event idempotently.
    /// Returns true if new event, false if duplicate.
    /// </summary>
    Task<bool> ProcessWebhookEventAsync(
        WebhookEvent webhookEvent,
        int tenantId,
        CancellationToken ct = default);

    /// <summary>
    /// Check rate limit for tenant/provider.
    /// Consumes token if allowed.
    /// </summary>
    Task<RateLimitResult> CheckRateLimitAsync(
        int tenantId,
        string provider,
        int tokensNeeded = 1,
        CancellationToken ct = default);

    /// <summary>
    /// Get worker health metrics.
    /// </summary>
    Task<WorkerHealthMetrics> GetHealthMetricsAsync(CancellationToken ct = default);

    /// <summary>
    /// Get driver contact info from masterdata (transient, not persisted in notify).
    /// </summary>
    Task<DriverContact?> GetDriverContactAsync(
        int tenantId,
        string driverId,
        CancellationToken ct = default);
}
