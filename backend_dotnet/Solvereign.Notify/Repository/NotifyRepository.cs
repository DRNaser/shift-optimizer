// =============================================================================
// SOLVEREIGN V4.1 - Notification Repository Implementation
// =============================================================================

using System.Text.Json;
using Dapper;
using Npgsql;
using Solvereign.Notify.Models;

namespace Solvereign.Notify.Repository;

/// <summary>
/// Dapper-based repository for notification operations.
/// Uses PostgreSQL-specific features (SKIP LOCKED, RETURNING, etc.).
/// </summary>
public sealed class NotifyRepository : INotifyRepository
{
    private readonly string _connectionString;
    private readonly ILogger<NotifyRepository> _logger;

    public NotifyRepository(string connectionString, ILogger<NotifyRepository> logger)
    {
        _connectionString = connectionString ?? throw new ArgumentNullException(nameof(connectionString));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    private async Task<NpgsqlConnection> OpenConnectionAsync(CancellationToken ct)
    {
        var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync(ct);
        return conn;
    }

    /// <inheritdoc />
    public async Task<IReadOnlyList<ClaimedOutboxMessage>> ClaimBatchAsync(
        int batchSize,
        string workerId,
        int lockDurationSeconds,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        // Use PostgreSQL function for atomic claiming
        var messages = await conn.QueryAsync<ClaimedOutboxMessageDto>(
            "SELECT * FROM notify.claim_outbox_batch(@batch_size, @worker_id, @lock_duration)",
            new { batch_size = batchSize, worker_id = workerId, lock_duration = lockDurationSeconds });

        var result = messages.Select(m => new ClaimedOutboxMessage
        {
            OutboxId = m.outbox_id,
            TenantId = m.tenant_id,
            DriverId = m.driver_id,
            DriverName = m.driver_name,
            DeliveryChannel = m.delivery_channel,
            MessageTemplate = m.message_template,
            MessageParams = m.message_params != null
                ? JsonSerializer.Deserialize<Dictionary<string, object>>(m.message_params)
                : null,
            PortalUrl = m.portal_url,
            AttemptCount = m.attempt_count,
            SnapshotId = m.snapshot_id,
            JobId = m.job_id
        }).ToList();

        if (result.Count > 0)
        {
            _logger.LogInformation(
                "Claimed {Count} messages for processing. WorkerId: {WorkerId}",
                result.Count, workerId);
        }

        return result;
    }

    /// <inheritdoc />
    public async Task MarkSentAsync(
        Guid outboxId,
        string providerMessageId,
        string? providerStatus = null,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        await conn.ExecuteAsync(
            "SELECT notify.mark_outbox_sent(@outbox_id, @provider_message_id, @provider_status)",
            new
            {
                outbox_id = outboxId,
                provider_message_id = providerMessageId,
                provider_status = providerStatus ?? "SENT"
            });

        _logger.LogDebug(
            "Marked message {OutboxId} as SENT. ProviderMessageId: {ProviderMessageId}",
            outboxId, providerMessageId);
    }

    /// <inheritdoc />
    public async Task<bool> MarkRetryAsync(
        Guid outboxId,
        string errorCode,
        int baseBackoffSeconds = 60,
        int maxAttempts = 5,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        var willRetry = await conn.ExecuteScalarAsync<bool>(
            "SELECT notify.mark_outbox_retry(@outbox_id, @error_code, @base_backoff, @max_attempts)",
            new
            {
                outbox_id = outboxId,
                error_code = errorCode,
                base_backoff = baseBackoffSeconds,
                max_attempts = maxAttempts
            });

        _logger.LogDebug(
            "Marked message {OutboxId} for retry. ErrorCode: {ErrorCode}, WillRetry: {WillRetry}",
            outboxId, errorCode, willRetry);

        return willRetry;
    }

    /// <inheritdoc />
    public async Task MarkDeadAsync(
        Guid outboxId,
        string errorCode,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        await conn.ExecuteAsync(
            "SELECT notify.mark_outbox_dead(@outbox_id, @error_code)",
            new { outbox_id = outboxId, error_code = errorCode });

        _logger.LogWarning(
            "Marked message {OutboxId} as DEAD. ErrorCode: {ErrorCode}",
            outboxId, errorCode);
    }

    /// <inheritdoc />
    public async Task MarkSkippedAsync(
        Guid outboxId,
        string skipReason,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        await conn.ExecuteAsync(
            "SELECT notify.mark_outbox_skipped(@outbox_id, @skip_reason)",
            new { outbox_id = outboxId, skip_reason = skipReason });

        _logger.LogInformation(
            "Marked message {OutboxId} as SKIPPED. Reason: {Reason}",
            outboxId, skipReason);
    }

    /// <inheritdoc />
    public async Task<int> ReleaseStuckMessagesAsync(TimeSpan maxAge, CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        var released = await conn.ExecuteScalarAsync<int>(
            "SELECT notify.release_stuck_sending(@max_age)",
            new { max_age = $"{maxAge.TotalMinutes} minutes" });

        if (released > 0)
        {
            _logger.LogWarning("Released {Count} stuck messages back to RETRYING", released);
        }

        return released;
    }

    /// <inheritdoc />
    public async Task<bool> RequeueDeadMessageAsync(
        Guid outboxId,
        bool resetAttempts = false,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        var success = await conn.ExecuteScalarAsync<bool>(
            "SELECT notify.requeue_dead_message(@outbox_id, @reset_attempts)",
            new { outbox_id = outboxId, reset_attempts = resetAttempts });

        if (success)
        {
            _logger.LogInformation(
                "Requeued dead message {OutboxId}. ResetAttempts: {ResetAttempts}",
                outboxId, resetAttempts);
        }

        return success;
    }

    /// <inheritdoc />
    public async Task<bool> ProcessWebhookEventAsync(
        WebhookEvent webhookEvent,
        int tenantId,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        var isNew = await conn.ExecuteScalarAsync<bool>(
            @"SELECT notify.process_webhook_event(
                @tenant_id, @provider, @provider_event_id, @event_type,
                @event_timestamp, @provider_message_id, @payload_hash)",
            new
            {
                tenant_id = tenantId,
                provider = webhookEvent.Provider,
                provider_event_id = webhookEvent.ProviderEventId,
                event_type = webhookEvent.EventType,
                event_timestamp = webhookEvent.EventTimestamp,
                provider_message_id = webhookEvent.ProviderMessageId,
                payload_hash = webhookEvent.PayloadHash
            });

        _logger.LogDebug(
            "Processed webhook event. Provider: {Provider}, EventId: {EventId}, IsNew: {IsNew}",
            webhookEvent.Provider, webhookEvent.ProviderEventId, isNew);

        return isNew;
    }

    /// <inheritdoc />
    public async Task<RateLimitResult> CheckRateLimitAsync(
        int tenantId,
        string provider,
        int tokensNeeded = 1,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        var result = await conn.QuerySingleAsync<RateLimitDto>(
            "SELECT * FROM notify.check_rate_limit(@tenant_id, @provider, @tokens_needed)",
            new { tenant_id = tenantId, provider = provider, tokens_needed = tokensNeeded });

        return new RateLimitResult
        {
            Allowed = result.allowed,
            TokensRemaining = result.tokens_remaining,
            RetryAfterSeconds = result.retry_after_seconds
        };
    }

    /// <inheritdoc />
    public async Task<WorkerHealthMetrics> GetHealthMetricsAsync(CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        var counts = await conn.QuerySingleAsync<HealthCountsDto>(@"
            SELECT
                COUNT(*) FILTER (WHERE status IN ('PENDING', 'RETRYING')) as pending_count,
                COUNT(*) FILTER (WHERE status = 'SENDING') as sending_count,
                COUNT(*) FILTER (WHERE status = 'DEAD') as dead_count,
                COUNT(*) FILTER (WHERE status = 'SENDING' AND lock_expires_at < NOW()) as stuck_count,
                MIN(created_at) FILTER (WHERE status IN ('PENDING', 'RETRYING')) as oldest_pending
            FROM notify.notification_outbox");

        return new WorkerHealthMetrics
        {
            PendingCount = counts.pending_count,
            SendingCount = counts.sending_count,
            DeadCount = counts.dead_count,
            StuckCount = counts.stuck_count,
            OldestPendingAge = counts.oldest_pending.HasValue
                ? DateTimeOffset.UtcNow - counts.oldest_pending.Value
                : null
        };
    }

    /// <inheritdoc />
    public async Task<DriverContact?> GetDriverContactAsync(
        int tenantId,
        string driverId,
        CancellationToken ct = default)
    {
        await using var conn = await OpenConnectionAsync(ct);

        // IMPORTANT: Contact info is fetched from masterdata/preferences, NOT stored in notify
        // This query joins driver_preferences (notify) with any masterdata contact table
        // For now, using preferences table which should have opt-in status
        var result = await conn.QuerySingleOrDefaultAsync<DriverContactDto>(@"
            SELECT
                driver_id,
                whatsapp_opted_in,
                email_opted_in,
                sms_opted_in,
                quiet_hours_start,
                quiet_hours_end,
                timezone
            FROM notify.driver_preferences
            WHERE tenant_id = @tenant_id AND driver_id = @driver_id",
            new { tenant_id = tenantId, driver_id = driverId });

        if (result == null) return null;

        // NOTE: Actual phone/email comes from external contact vault or masterdata
        // We do NOT store raw contacts in notify schema
        return new DriverContact
        {
            DriverId = result.driver_id,
            PhoneNumber = null,  // Must be fetched from secure contact vault
            Email = null,        // Must be fetched from secure contact vault
            WhatsAppOptedIn = result.whatsapp_opted_in,
            EmailOptedIn = result.email_opted_in,
            SmsOptedIn = result.sms_opted_in,
            QuietHoursStart = result.quiet_hours_start,
            QuietHoursEnd = result.quiet_hours_end,
            Timezone = result.timezone ?? "Europe/Vienna"
        };
    }

    // =========================================================================
    // DTO classes for Dapper mapping
    // =========================================================================

    private sealed class ClaimedOutboxMessageDto
    {
        public Guid outbox_id { get; set; }
        public int tenant_id { get; set; }
        public string driver_id { get; set; } = "";
        public string? driver_name { get; set; }
        public string delivery_channel { get; set; } = "";
        public string message_template { get; set; } = "";
        public string? message_params { get; set; }
        public string? portal_url { get; set; }
        public int attempt_count { get; set; }
        public Guid? snapshot_id { get; set; }
        public Guid? job_id { get; set; }
    }

    private sealed class RateLimitDto
    {
        public bool allowed { get; set; }
        public int tokens_remaining { get; set; }
        public int retry_after_seconds { get; set; }
    }

    private sealed class HealthCountsDto
    {
        public int pending_count { get; set; }
        public int sending_count { get; set; }
        public int dead_count { get; set; }
        public int stuck_count { get; set; }
        public DateTimeOffset? oldest_pending { get; set; }
    }

    private sealed class DriverContactDto
    {
        public string driver_id { get; set; } = "";
        public bool whatsapp_opted_in { get; set; }
        public bool email_opted_in { get; set; }
        public bool sms_opted_in { get; set; }
        public TimeOnly? quiet_hours_start { get; set; }
        public TimeOnly? quiet_hours_end { get; set; }
        public string? timezone { get; set; }
    }
}
