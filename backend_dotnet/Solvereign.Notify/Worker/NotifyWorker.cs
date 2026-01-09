// =============================================================================
// SOLVEREIGN V4.1 - Notification Worker (HostedService)
// =============================================================================

using System.Diagnostics;
using Microsoft.Extensions.Options;
using Solvereign.Notify.Models;
using Solvereign.Notify.Providers;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Worker;

/// <summary>
/// Background worker for processing notification outbox.
/// Uses transactional outbox pattern with atomic claiming.
/// </summary>
public sealed class NotifyWorker : BackgroundService
{
    private readonly INotifyRepository _repository;
    private readonly IServiceProvider _serviceProvider;
    private readonly NotifyWorkerConfig _config;
    private readonly ILogger<NotifyWorker> _logger;

    private int _batchesProcessed;
    private int _messagesSent;
    private int _messagesFailed;
    private DateTimeOffset _lastPollTime;
    private DateTimeOffset _lastReaperRun;

    public NotifyWorker(
        INotifyRepository repository,
        IServiceProvider serviceProvider,
        IOptions<NotifyWorkerConfig> config,
        ILogger<NotifyWorker> logger)
    {
        _repository = repository ?? throw new ArgumentNullException(nameof(repository));
        _serviceProvider = serviceProvider ?? throw new ArgumentNullException(nameof(serviceProvider));
        _config = config?.Value ?? throw new ArgumentNullException(nameof(config));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation(
            "NotifyWorker starting. WorkerId: {WorkerId}, BatchSize: {BatchSize}, PollInterval: {PollInterval}s",
            _config.WorkerId, _config.BatchSize, _config.PollIntervalSeconds);

        _lastReaperRun = DateTimeOffset.UtcNow;

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await ProcessBatchAsync(stoppingToken);

                // Run reaper periodically
                if ((DateTimeOffset.UtcNow - _lastReaperRun).TotalSeconds >= _config.ReaperIntervalSeconds)
                {
                    await RunReaperAsync(stoppingToken);
                    _lastReaperRun = DateTimeOffset.UtcNow;
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                _logger.LogInformation("NotifyWorker received shutdown signal");
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "NotifyWorker error during batch processing");
            }

            // Wait for next poll
            try
            {
                await Task.Delay(TimeSpan.FromSeconds(_config.PollIntervalSeconds), stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
        }

        _logger.LogInformation(
            "NotifyWorker stopped. BatchesProcessed: {Batches}, MessagesSent: {Sent}, MessagesFailed: {Failed}",
            _batchesProcessed, _messagesSent, _messagesFailed);
    }

    private async Task ProcessBatchAsync(CancellationToken ct)
    {
        _lastPollTime = DateTimeOffset.UtcNow;

        // Claim batch atomically
        var messages = await _repository.ClaimBatchAsync(
            _config.BatchSize,
            _config.WorkerId,
            _config.LockDurationSeconds,
            ct);

        if (messages.Count == 0)
            return;

        _batchesProcessed++;

        _logger.LogDebug(
            "Processing batch of {Count} messages. WorkerId: {WorkerId}",
            messages.Count, _config.WorkerId);

        // Process with parallel limit
        using var semaphore = new SemaphoreSlim(_config.MaxParallelSends);
        var tasks = messages.Select(msg => ProcessMessageWithSemaphoreAsync(msg, semaphore, ct));

        await Task.WhenAll(tasks);
    }

    private async Task ProcessMessageWithSemaphoreAsync(
        ClaimedOutboxMessage message,
        SemaphoreSlim semaphore,
        CancellationToken ct)
    {
        await semaphore.WaitAsync(ct);
        try
        {
            await ProcessMessageAsync(message, ct);
        }
        finally
        {
            semaphore.Release();
        }
    }

    private async Task ProcessMessageAsync(ClaimedOutboxMessage message, CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();

        try
        {
            // 1. Get driver contact & preferences
            var contact = await _repository.GetDriverContactAsync(message.TenantId, message.DriverId, ct);

            // 2. Check opt-out
            if (contact != null && !IsOptedIn(contact, message.Channel))
            {
                await _repository.MarkSkippedAsync(message.OutboxId, SkipReason.OptOut, ct);
                _logger.LogInformation(
                    "Message {OutboxId} skipped: OPT_OUT. Driver: {DriverId}, Channel: {Channel}",
                    message.OutboxId, message.DriverId, message.Channel);
                return;
            }

            // 3. Check quiet hours (TODO: implement tenant-level quiet hours check)
            // For now, driver-level quiet hours
            if (contact != null && IsQuietHours(contact))
            {
                // Reschedule instead of skip
                await _repository.MarkRetryAsync(
                    message.OutboxId,
                    SkipReason.QuietHours,
                    baseBackoffSeconds: 3600,  // 1 hour
                    maxAttempts: _config.MaxAttempts,
                    ct);
                _logger.LogInformation(
                    "Message {OutboxId} delayed: QUIET_HOURS. Driver: {DriverId}",
                    message.OutboxId, message.DriverId);
                return;
            }

            // 4. Check rate limit
            var rateLimit = await _repository.CheckRateLimitAsync(
                message.TenantId,
                message.DeliveryChannel,
                tokensNeeded: 1,
                ct);

            if (!rateLimit.Allowed)
            {
                // Rate limited - schedule retry
                await _repository.MarkRetryAsync(
                    message.OutboxId,
                    ErrorCodes.Provider429,
                    baseBackoffSeconds: rateLimit.RetryAfterSeconds,
                    maxAttempts: _config.MaxAttempts,
                    ct);
                _logger.LogWarning(
                    "Message {OutboxId} rate limited. RetryAfter: {Seconds}s",
                    message.OutboxId, rateLimit.RetryAfterSeconds);
                return;
            }

            // 5. Resolve recipient (from secure contact vault, NOT notify schema)
            var recipient = await ResolveRecipientAsync(message, contact, ct);
            if (string.IsNullOrEmpty(recipient))
            {
                await _repository.MarkSkippedAsync(message.OutboxId, SkipReason.NoContact, ct);
                _logger.LogWarning(
                    "Message {OutboxId} skipped: NO_CONTACT. Driver: {DriverId}",
                    message.OutboxId, message.DriverId);
                return;
            }

            // 6. Get provider and send
            var provider = GetProvider(message.Channel);
            var result = await provider.SendAsync(
                recipient,
                message.MessageTemplate,
                message.MessageParams ?? new Dictionary<string, object>(),
                message.PortalUrl,
                ct);

            // 7. Handle result
            if (result.Success)
            {
                await _repository.MarkSentAsync(
                    message.OutboxId,
                    result.ProviderMessageId!,
                    result.ProviderStatus,
                    ct);
                Interlocked.Increment(ref _messagesSent);

                _logger.LogInformation(
                    "Message {OutboxId} sent successfully. Driver: {DriverId}, Provider: {Provider}, Duration: {Duration}ms",
                    message.OutboxId, message.DriverId, message.Channel, sw.ElapsedMilliseconds);
            }
            else if (result.IsRetryable)
            {
                var willRetry = await _repository.MarkRetryAsync(
                    message.OutboxId,
                    result.ErrorCode ?? ErrorCodes.Provider5xx,
                    _config.BaseBackoffSeconds,
                    _config.MaxAttempts,
                    ct);

                if (!willRetry)
                {
                    Interlocked.Increment(ref _messagesFailed);
                }

                _logger.LogWarning(
                    "Message {OutboxId} failed (retryable). ErrorCode: {ErrorCode}, WillRetry: {WillRetry}",
                    message.OutboxId, result.ErrorCode, willRetry);
            }
            else
            {
                await _repository.MarkDeadAsync(
                    message.OutboxId,
                    result.ErrorCode ?? ErrorCodes.ProviderInvalidRecipient,
                    ct);
                Interlocked.Increment(ref _messagesFailed);

                _logger.LogError(
                    "Message {OutboxId} failed permanently. ErrorCode: {ErrorCode}",
                    message.OutboxId, result.ErrorCode);
            }
        }
        catch (Exception ex)
        {
            // Unexpected error - mark for retry
            _logger.LogError(ex,
                "Unexpected error processing message {OutboxId}",
                message.OutboxId);

            await _repository.MarkRetryAsync(
                message.OutboxId,
                ErrorCodes.NetworkError,
                _config.BaseBackoffSeconds,
                _config.MaxAttempts,
                ct);
        }
    }

    private async Task RunReaperAsync(CancellationToken ct)
    {
        try
        {
            var released = await _repository.ReleaseStuckMessagesAsync(
                TimeSpan.FromMinutes(_config.StuckMaxAgeMinutes),
                ct);

            if (released > 0)
            {
                _logger.LogWarning("Reaper released {Count} stuck messages", released);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Reaper failed");
        }
    }

    private INotificationProvider GetProvider(DeliveryChannel channel)
    {
        // Get provider from DI
        return channel switch
        {
            DeliveryChannel.WhatsApp => _serviceProvider.GetRequiredService<WhatsAppProvider>(),
            DeliveryChannel.Email => _serviceProvider.GetRequiredService<SendGridProvider>(),
            _ => throw new NotSupportedException($"Channel {channel} not supported")
        };
    }

    private static bool IsOptedIn(DriverContact contact, DeliveryChannel channel)
    {
        return channel switch
        {
            DeliveryChannel.WhatsApp => contact.WhatsAppOptedIn,
            DeliveryChannel.Email => contact.EmailOptedIn,
            DeliveryChannel.Sms => contact.SmsOptedIn,
            _ => false
        };
    }

    private static bool IsQuietHours(DriverContact contact)
    {
        if (!contact.QuietHoursStart.HasValue || !contact.QuietHoursEnd.HasValue)
            return false;

        try
        {
            var tz = TimeZoneInfo.FindSystemTimeZoneById(contact.Timezone);
            var localNow = TimeZoneInfo.ConvertTime(DateTimeOffset.UtcNow, tz);
            var localTime = TimeOnly.FromDateTime(localNow.DateTime);

            var start = contact.QuietHoursStart.Value;
            var end = contact.QuietHoursEnd.Value;

            // Handle overnight quiet hours
            if (start > end)
            {
                return localTime >= start || localTime <= end;
            }
            return localTime >= start && localTime <= end;
        }
        catch
        {
            return false;
        }
    }

    private async Task<string?> ResolveRecipientAsync(
        ClaimedOutboxMessage message,
        DriverContact? contact,
        CancellationToken ct)
    {
        // IMPORTANT: Recipient resolution must come from SECURE CONTACT VAULT
        // NOT from notify schema (GDPR compliance)

        // Option 1: Contact info passed in message_params (from portal token issuance)
        if (message.MessageParams != null)
        {
            var key = message.Channel switch
            {
                DeliveryChannel.WhatsApp => "phone",
                DeliveryChannel.Sms => "phone",
                DeliveryChannel.Email => "email",
                _ => null
            };

            if (key != null && message.MessageParams.TryGetValue(key, out var value))
            {
                return value?.ToString();
            }
        }

        // Option 2: Fetch from secure contact service
        // TODO: Implement IContactVaultService.GetContactAsync(tenantId, driverId, channel)
        // This service would fetch from encrypted contact storage (separate from notify)

        return null;
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("NotifyWorker stopping gracefully...");

        using var cts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        cts.CancelAfter(TimeSpan.FromSeconds(_config.ShutdownTimeoutSeconds));

        await base.StopAsync(cts.Token);
    }
}
