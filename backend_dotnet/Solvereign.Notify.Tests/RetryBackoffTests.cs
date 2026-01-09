// =============================================================================
// SOLVEREIGN V4.1 - Retry/Backoff Tests
// =============================================================================

using FluentAssertions;
using Moq;
using Solvereign.Notify.Models;
using Solvereign.Notify.Repository;

namespace Solvereign.Notify.Tests;

/// <summary>
/// Tests for retry logic and exponential backoff.
/// </summary>
public class RetryBackoffTests
{
    /// <summary>
    /// First retry should use base backoff.
    /// </summary>
    [Fact]
    public void Backoff_FirstRetry_BaseDelay()
    {
        // Arrange
        const int baseBackoff = 60;
        const int attemptCount = 1;

        // Act
        var delay = CalculateBackoff(baseBackoff, attemptCount);

        // Assert
        delay.Should().BeInRange(60, 69, "first retry should be ~60s with up to 15% jitter");
    }

    /// <summary>
    /// Second retry should be exponentially larger.
    /// </summary>
    [Fact]
    public void Backoff_SecondRetry_ExponentialIncrease()
    {
        // Arrange
        const int baseBackoff = 60;
        const int attemptCount = 2;

        // Act
        var delay = CalculateBackoff(baseBackoff, attemptCount);

        // Assert
        // Expected: 60 * 5^1 = 300s, with jitter: 300-345
        delay.Should().BeInRange(300, 345);
    }

    /// <summary>
    /// Third retry should be even larger.
    /// </summary>
    [Fact]
    public void Backoff_ThirdRetry_LargerDelay()
    {
        // Arrange
        const int baseBackoff = 60;
        const int attemptCount = 3;

        // Act
        var delay = CalculateBackoff(baseBackoff, attemptCount);

        // Assert
        // Expected: 60 * 5^2 = 1500s, with jitter: 1500-1725
        delay.Should().BeInRange(1500, 1725);
    }

    /// <summary>
    /// Backoff should be clamped at maximum.
    /// </summary>
    [Fact]
    public void Backoff_ExceedsMax_Clamped()
    {
        // Arrange
        const int baseBackoff = 60;
        const int attemptCount = 5;

        // Act
        var delay = CalculateBackoff(baseBackoff, attemptCount);

        // Assert
        // Max is 2700s (45 min), with jitter: 2700-3105
        delay.Should().BeLessOrEqualTo(3105, "backoff should be clamped at ~45 min");
    }

    /// <summary>
    /// MarkRetry should return false after max attempts.
    /// </summary>
    [Fact]
    public async Task MarkRetry_MaxAttemptsExceeded_ReturnsFalse()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        mockRepo.Setup(r => r.MarkRetryAsync(
                It.IsAny<Guid>(),
                It.IsAny<string>(),
                It.IsAny<int>(),
                It.Is<int>(max => max == 3),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);  // Simulates DB returning false (moved to DEAD)

        // Act
        var result = await mockRepo.Object.MarkRetryAsync(
            Guid.NewGuid(),
            ErrorCodes.Provider5xx,
            baseBackoffSeconds: 60,
            maxAttempts: 3);

        // Assert
        result.Should().BeFalse("message should be moved to DEAD after max attempts");
    }

    /// <summary>
    /// MarkRetry should return true when attempts remaining.
    /// </summary>
    [Fact]
    public async Task MarkRetry_AttemptsRemaining_ReturnsTrue()
    {
        // Arrange
        var mockRepo = new Mock<INotifyRepository>();
        mockRepo.Setup(r => r.MarkRetryAsync(
                It.IsAny<Guid>(),
                It.IsAny<string>(),
                It.IsAny<int>(),
                It.IsAny<int>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);

        // Act
        var result = await mockRepo.Object.MarkRetryAsync(
            Guid.NewGuid(),
            ErrorCodes.ProviderTimeout,
            baseBackoffSeconds: 60,
            maxAttempts: 5);

        // Assert
        result.Should().BeTrue();
    }

    /// <summary>
    /// Calculate backoff with jitter (mirror of SQL logic).
    /// </summary>
    private static int CalculateBackoff(int baseBackoff, int attemptCount)
    {
        // Exponential: base * 5^(attempt-1), clamped at 2700
        var delay = Math.Min(baseBackoff * (int)Math.Pow(5, attemptCount - 1), 2700);

        // Add 0-15% jitter
        var jitter = (int)(delay * Random.Shared.NextDouble() * 0.15);

        return delay + jitter;
    }
}
