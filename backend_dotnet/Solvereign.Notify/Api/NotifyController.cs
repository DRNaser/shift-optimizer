// =============================================================================
// SOLVEREIGN V4.1 - Notification API Controller
// =============================================================================

using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Solvereign.Notify.Models;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Api;

/// <summary>
/// Notification management API.
/// RBAC: Dispatcher role required for all endpoints.
/// </summary>
[ApiController]
[Route("api/v1/notifications")]
[Authorize(Roles = "Dispatcher,Approver,Admin")]
public class NotifyController : ControllerBase
{
    private readonly INotifyRepository _repository;
    private readonly ILogger<NotifyController> _logger;

    public NotifyController(
        INotifyRepository repository,
        ILogger<NotifyController> logger)
    {
        _repository = repository;
        _logger = logger;
    }

    /// <summary>
    /// Get worker health metrics.
    /// </summary>
    [HttpGet("health")]
    [AllowAnonymous]
    public async Task<ActionResult<WorkerHealthMetrics>> GetHealth(CancellationToken ct)
    {
        var metrics = await _repository.GetHealthMetricsAsync(ct);
        return Ok(metrics);
    }

    /// <summary>
    /// Requeue a dead message for retry.
    /// Requires Approver role.
    /// </summary>
    [HttpPost("outbox/{outboxId:guid}/requeue")]
    [Authorize(Roles = "Approver,Admin")]
    public async Task<IActionResult> RequeueDeadMessage(
        Guid outboxId,
        [FromQuery] bool resetAttempts = false,
        CancellationToken ct = default)
    {
        var success = await _repository.RequeueDeadMessageAsync(outboxId, resetAttempts, ct);

        if (!success)
        {
            return NotFound(new { error = "not_found", message = $"Outbox {outboxId} not found or not in DEAD state" });
        }

        _logger.LogInformation(
            "Message {OutboxId} requeued by {User}. ResetAttempts: {Reset}",
            outboxId, User.Identity?.Name, resetAttempts);

        return Ok(new { success = true, outbox_id = outboxId, reset_attempts = resetAttempts });
    }

    /// <summary>
    /// Force release stuck messages (reaper trigger).
    /// Requires Admin role.
    /// </summary>
    [HttpPost("reaper/run")]
    [Authorize(Roles = "Admin")]
    public async Task<IActionResult> RunReaper(
        [FromQuery] int maxAgeMinutes = 10,
        CancellationToken ct = default)
    {
        var released = await _repository.ReleaseStuckMessagesAsync(
            TimeSpan.FromMinutes(maxAgeMinutes), ct);

        _logger.LogInformation(
            "Reaper triggered by {User}. Released: {Count}",
            User.Identity?.Name, released);

        return Ok(new { released_count = released });
    }
}

// =============================================================================
// REQUEST/RESPONSE MODELS
// =============================================================================

/// <summary>
/// Request to create a notification job.
/// </summary>
public sealed record CreateNotificationJobRequest
{
    /// <summary>Snapshot UUID to notify drivers about.</summary>
    public required Guid SnapshotId { get; init; }

    /// <summary>List of driver IDs to notify.</summary>
    public required List<string> DriverIds { get; init; }

    /// <summary>Map of driver_id to portal URL.</summary>
    public required Dictionary<string, string> PortalUrls { get; init; }

    /// <summary>Delivery channel: WHATSAPP, EMAIL, SMS.</summary>
    public string DeliveryChannel { get; init; } = "WHATSAPP";

    /// <summary>Template key.</summary>
    public string TemplateKey { get; init; } = "PORTAL_INVITE";

    /// <summary>Additional template parameters.</summary>
    public Dictionary<string, object>? TemplateParams { get; init; }

    /// <summary>Priority (1=highest, 10=lowest).</summary>
    public int Priority { get; init; } = 5;
}

/// <summary>
/// Response from job creation.
/// </summary>
public sealed record CreateNotificationJobResponse
{
    public required Guid JobId { get; init; }
    public required int TotalCount { get; init; }
    public required string Status { get; init; }
}

/// <summary>
/// Job status response.
/// </summary>
public sealed record NotificationJobStatus
{
    public required Guid JobId { get; init; }
    public required string Status { get; init; }
    public required string JobType { get; init; }
    public required string DeliveryChannel { get; init; }
    public required int TotalCount { get; init; }
    public required int SentCount { get; init; }
    public required int DeliveredCount { get; init; }
    public required int FailedCount { get; init; }
    public required int PendingCount { get; init; }
    public required double CompletionRate { get; init; }
    public required string InitiatedBy { get; init; }
    public required DateTimeOffset InitiatedAt { get; init; }
    public DateTimeOffset? CompletedAt { get; init; }
}
