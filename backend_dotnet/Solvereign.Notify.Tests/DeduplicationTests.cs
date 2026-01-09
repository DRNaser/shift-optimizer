// =============================================================================
// SOLVEREIGN V4.1 - Deduplication Tests
// =============================================================================

using System.Security.Cryptography;
using System.Text;
using FluentAssertions;

namespace Solvereign.Notify.Tests;

/// <summary>
/// Tests for message deduplication.
/// Ensures semantic dedup key prevents duplicate outbox entries.
/// </summary>
public class DeduplicationTests
{
    /// <summary>
    /// Dedup key should be deterministic for same inputs.
    /// </summary>
    [Fact]
    public void DedupKey_SameInputs_SameKey()
    {
        // Arrange
        var tenantId = 1;
        var siteId = Guid.Parse("11111111-1111-1111-1111-111111111111");
        var snapshotId = Guid.Parse("22222222-2222-2222-2222-222222222222");
        var driverId = "D001";
        var channel = "WHATSAPP";
        var template = "PORTAL_INVITE";
        var version = "v1";

        // Act
        var key1 = ComputeDedupKey(tenantId, siteId, snapshotId, driverId, channel, template, version);
        var key2 = ComputeDedupKey(tenantId, siteId, snapshotId, driverId, channel, template, version);

        // Assert
        key1.Should().Be(key2);
    }

    /// <summary>
    /// Dedup key should differ for different drivers.
    /// </summary>
    [Fact]
    public void DedupKey_DifferentDriver_DifferentKey()
    {
        // Arrange
        var tenantId = 1;
        var siteId = Guid.Parse("11111111-1111-1111-1111-111111111111");
        var snapshotId = Guid.Parse("22222222-2222-2222-2222-222222222222");
        var channel = "WHATSAPP";
        var template = "PORTAL_INVITE";
        var version = "v1";

        // Act
        var key1 = ComputeDedupKey(tenantId, siteId, snapshotId, "D001", channel, template, version);
        var key2 = ComputeDedupKey(tenantId, siteId, snapshotId, "D002", channel, template, version);

        // Assert
        key1.Should().NotBe(key2);
    }

    /// <summary>
    /// Dedup key should differ for different channels.
    /// </summary>
    [Fact]
    public void DedupKey_DifferentChannel_DifferentKey()
    {
        // Arrange
        var tenantId = 1;
        var siteId = Guid.Parse("11111111-1111-1111-1111-111111111111");
        var snapshotId = Guid.Parse("22222222-2222-2222-2222-222222222222");
        var driverId = "D001";
        var template = "PORTAL_INVITE";
        var version = "v1";

        // Act
        var keyWhatsApp = ComputeDedupKey(tenantId, siteId, snapshotId, driverId, "WHATSAPP", template, version);
        var keyEmail = ComputeDedupKey(tenantId, siteId, snapshotId, driverId, "EMAIL", template, version);

        // Assert
        keyWhatsApp.Should().NotBe(keyEmail);
    }

    /// <summary>
    /// Dedup key should include snapshot to allow resends for different snapshots.
    /// </summary>
    [Fact]
    public void DedupKey_DifferentSnapshot_DifferentKey()
    {
        // Arrange
        var tenantId = 1;
        var siteId = Guid.Parse("11111111-1111-1111-1111-111111111111");
        var driverId = "D001";
        var channel = "WHATSAPP";
        var template = "PORTAL_INVITE";
        var version = "v1";

        // Act
        var key1 = ComputeDedupKey(tenantId, siteId,
            Guid.Parse("22222222-2222-2222-2222-222222222222"), driverId, channel, template, version);
        var key2 = ComputeDedupKey(tenantId, siteId,
            Guid.Parse("33333333-3333-3333-3333-333333333333"), driverId, channel, template, version);

        // Assert
        key1.Should().NotBe(key2, "resending for new snapshot should create new outbox entry");
    }

    /// <summary>
    /// Dedup key should be 64 chars (SHA256 hex).
    /// </summary>
    [Fact]
    public void DedupKey_Length_64Characters()
    {
        // Act
        var key = ComputeDedupKey(1, Guid.NewGuid(), Guid.NewGuid(), "D001", "WHATSAPP", "PORTAL_INVITE", "v1");

        // Assert
        key.Should().HaveLength(64);
        key.Should().MatchRegex("^[a-f0-9]+$");
    }

    /// <summary>
    /// Compute dedup key (mirror of SQL function).
    /// </summary>
    private static string ComputeDedupKey(
        int tenantId,
        Guid? siteId,
        Guid? snapshotId,
        string driverId,
        string channel,
        string template,
        string templateVersion)
    {
        var input = string.Join("|",
            tenantId.ToString(),
            siteId?.ToString() ?? "",
            snapshotId?.ToString() ?? "",
            driverId ?? "",
            channel ?? "",
            template ?? "",
            templateVersion ?? "");

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(input));
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
