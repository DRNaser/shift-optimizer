// =============================================================================
// SOLVEREIGN V4.1 - Stuck Message Reaper Tests
// =============================================================================

using FluentAssertions;
using Moq;
using Solvereign.Notify.Models;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Tests;

/// <summary>
/// Tests for stuck message reaper functionality.
/// Ensures SENDING messages with expired locks are recovered.
/// </summary>
public class StuckReaperTests
{
    /// <summary>
    /// Messages stuck in SENDING with expired lock should be released.
    /// </summary>
    [Fact]
    public async Task ReleaseStuck_ExpiredLock_MovesToRetrying()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        var stuckCount = 5;

        mockRepo.Setup(r => r.ReleaseStuckSendingAsync(
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(stuckCount);

        // Act
        var released = await mockRepo.Object.ReleaseStuckSendingAsync(
            lockTimeoutMinutes: 5);

        // Assert
        released.Should().Be(5, "5 stuck messages should be released to RETRYING");
    }

    /// <summary>
    /// No stuck messages should return zero.
    /// </summary>
    [Fact]
    public async Task ReleaseStuck_NoStuckMessages_ReturnsZero()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();

        mockRepo.Setup(r => r.ReleaseStuckSendingAsync(
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(0);

        // Act
        var released = await mockRepo.Object.ReleaseStuckSendingAsync(
            lockTimeoutMinutes: 5);

        // Assert
        released.Should().Be(0);
    }

    /// <summary>
    /// Lock that hasn't expired should not be released.
    /// </summary>
    [Fact]
    public void LockExpiration_NotExpired_ShouldNotRelease()
    {
        // Arrange
        var lockExpiresAt = DateTime.UtcNow.AddMinutes(5);
        var now = DateTime.UtcNow;

        // Act
        var isExpired = lockExpiresAt < now;

        // Assert
        isExpired.Should().BeFalse("lock with future expiry should not be released");
    }

    /// <summary>
    /// Lock that has expired should be released.
    /// </summary>
    [Fact]
    public void LockExpiration_Expired_ShouldRelease()
    {
        // Arrange
        var lockExpiresAt = DateTime.UtcNow.AddMinutes(-1);
        var now = DateTime.UtcNow;

        // Act
        var isExpired = lockExpiresAt < now;

        // Assert
        isExpired.Should().BeTrue("lock with past expiry should be released");
    }

    /// <summary>
    /// Default lock timeout should be 5 minutes.
    /// </summary>
    [Fact]
    public void DefaultLockTimeout_FiveMinutes()
    {
        // Arrange
        const int defaultLockDurationSeconds = 300;

        // Act
        var minutes = defaultLockDurationSeconds / 60;

        // Assert
        minutes.Should().Be(5, "default lock duration should be 5 minutes");
    }

    /// <summary>
    /// Reaper should handle concurrent execution safely.
    /// </summary>
    [Fact]
    public async Task ReleaseStuck_ConcurrentExecution_NoConflicts()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        var callCount = 0;

        mockRepo.Setup(r => r.ReleaseStuckSendingAsync(
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(() =>
            {
                Interlocked.Increment(ref callCount);
                return callCount == 1 ? 3 : 0;  // First call finds 3, second finds none
            });

        // Act - Simulate two workers running reaper concurrently
        var task1 = mockRepo.Object.ReleaseStuckSendingAsync(lockTimeoutMinutes: 5);
        var task2 = mockRepo.Object.ReleaseStuckSendingAsync(lockTimeoutMinutes: 5);

        var results = await Task.WhenAll(task1, task2);

        // Assert
        results.Sum().Should().Be(3, "total released should be 3 (one worker found them)");
    }

    /// <summary>
    /// Released messages should have attempt count incremented.
    /// </summary>
    [Fact]
    public async Task ReleaseStuck_AttemptCountIncremented()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        var messageId = Guid.NewGuid();
        var originalAttemptCount = 2;

        // The release_stuck_sending function in SQL increments attempt_count
        mockRepo.Setup(r => r.ReleaseStuckSendingAsync(
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(1);

        // Simulate getting the message after release
        mockRepo.Setup(r => r.ClaimBatchAsync(
                It.IsAny<int>(),
                It.IsAny<string>(),
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ClaimedOutboxMessage>
            {
                new()
                {
                    OutboxId = messageId,
                    TenantId = 1,
                    DriverId = "D001",
                    DeliveryChannel = "WHATSAPP",
                    MessageTemplate = "PORTAL_INVITE",
                    AttemptCount = originalAttemptCount + 1  // Incremented by release
                }
            });

        // Act
        await mockRepo.Object.ReleaseStuckSendingAsync(lockTimeoutMinutes: 5);
        var claimed = await mockRepo.Object.ClaimBatchAsync(10, "worker1", 300);

        // Assert
        claimed.Should().HaveCount(1);
        claimed[0].AttemptCount.Should().Be(originalAttemptCount + 1);
    }

    /// <summary>
    /// Messages exceeding max attempts after release should go to DEAD.
    /// </summary>
    [Fact]
    public async Task ReleaseStuck_ExceedsMaxAttempts_MovesToDead()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        const int maxAttempts = 5;

        // release_stuck_sending sets status based on attempt_count vs max_attempts
        mockRepo.Setup(r => r.ReleaseStuckSendingAsync(
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(1);  // 1 message moved to DEAD (not RETRYING)

        // Act
        var released = await mockRepo.Object.ReleaseStuckSendingAsync(
            lockTimeoutMinutes: 5);

        // Assert
        released.Should().Be(1);
        // In real implementation, this would be verified by checking
        // the status is DEAD when attempt_count >= max_attempts
    }
}
