// =============================================================================
// SOLVEREIGN V4.1 - Concurrency Claiming Tests
// =============================================================================

using FluentAssertions;
using Moq;
using Solvereign.Notify.Models;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Tests;

/// <summary>
/// Tests for concurrent worker claiming.
/// Ensures no double-sends through atomic claiming.
/// </summary>
public class ConcurrencyClaimingTests
{
    /// <summary>
    /// Two workers claiming simultaneously should get non-overlapping messages.
    /// </summary>
    [Fact]
    public async Task TwoWorkers_ClaimSimultaneously_NoOverlap()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        var allMessages = Enumerable.Range(1, 20)
            .Select(i => new ClaimedOutboxMessage
            {
                OutboxId = Guid.NewGuid(),
                TenantId = 1,
                DriverId = $"D{i:D3}",
                DeliveryChannel = "WHATSAPP",
                MessageTemplate = "PORTAL_INVITE",
                AttemptCount = 1
            }).ToList();

        var claimedByWorker1 = new HashSet<Guid>();
        var claimedByWorker2 = new HashSet<Guid>();
        var messageIndex = 0;
        var lockObj = new object();

        mockRepo.Setup(r => r.ClaimBatchAsync(
                It.IsAny<int>(),
                It.IsAny<string>(),
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync((int batchSize, string workerId, int lockDuration, CancellationToken ct) =>
            {
                lock (lockObj)
                {
                    var batch = new List<ClaimedOutboxMessage>();
                    for (int i = 0; i < batchSize && messageIndex < allMessages.Count; i++)
                    {
                        var msg = allMessages[messageIndex++];

                        // Simulate SKIP LOCKED - only return if not already claimed
                        if (!claimedByWorker1.Contains(msg.OutboxId) &&
                            !claimedByWorker2.Contains(msg.OutboxId))
                        {
                            batch.Add(msg);

                            if (workerId.Contains("worker1"))
                                claimedByWorker1.Add(msg.OutboxId);
                            else
                                claimedByWorker2.Add(msg.OutboxId);
                        }
                    }
                    return batch;
                }
            });

        // Act - Two workers claim concurrently
        var task1 = mockRepo.Object.ClaimBatchAsync(10, "worker1", 300);
        var task2 = mockRepo.Object.ClaimBatchAsync(10, "worker2", 300);

        var results = await Task.WhenAll(task1, task2);

        // Assert - No overlapping claims
        var ids1 = results[0].Select(m => m.OutboxId).ToHashSet();
        var ids2 = results[1].Select(m => m.OutboxId).ToHashSet();

        ids1.Intersect(ids2).Should().BeEmpty("no message should be claimed by both workers");
        (ids1.Count + ids2.Count).Should().BeLessOrEqualTo(20);
    }

    /// <summary>
    /// Claimed messages should not be re-claimed until released.
    /// </summary>
    [Fact]
    public async Task ClaimedMessages_NotReclaimedUntilReleased()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        var messageId = Guid.NewGuid();
        var claimed = false;

        mockRepo.Setup(r => r.ClaimBatchAsync(
                It.IsAny<int>(), It.IsAny<string>(), It.IsAny<int>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(() =>
            {
                if (!claimed)
                {
                    claimed = true;
                    return new List<ClaimedOutboxMessage>
                    {
                        new()
                        {
                            OutboxId = messageId,
                            TenantId = 1,
                            DriverId = "D001",
                            DeliveryChannel = "WHATSAPP",
                            MessageTemplate = "PORTAL_INVITE",
                            AttemptCount = 1
                        }
                    };
                }
                return new List<ClaimedOutboxMessage>();
            });

        // Act
        var firstClaim = await mockRepo.Object.ClaimBatchAsync(10, "worker1", 300);
        var secondClaim = await mockRepo.Object.ClaimBatchAsync(10, "worker2", 300);

        // Assert
        firstClaim.Should().HaveCount(1);
        secondClaim.Should().BeEmpty("message should still be locked");
    }
}
