using Mavi.Domain.Intelligence;

namespace Mavi.Domain.Tests;

public sealed class TrackTests
{
    [Fact]
    public void CreateDerivesDurationAndUtcTimestamps()
    {
        var recordingStart = new DateTimeOffset(2026, 9, 8, 10, 0, 0, TimeSpan.Zero);
        var track = Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 17, ObjectClass.Person,
            4_120, 21_880, recordingStart, 280, 0.88, 0.96);

        Assert.Equal(17_760, track.DurationMs);
        Assert.Equal(recordingStart.AddMilliseconds(4_120), track.StartTimestampUtc);
        Assert.Equal(recordingStart.AddMilliseconds(21_880), track.EndTimestampUtc);
        Assert.Null(track.EntityId);
    }

    [Fact]
    public void CreateRejectsEndBeforeStart()
    {
        Assert.ThrowsAny<Exception>(() => Track.Create(
            Guid.CreateVersion7(), Guid.CreateVersion7(), 1, ObjectClass.Vehicle,
            10_000, 9_000, DateTimeOffset.UtcNow, 5, 0.8, 0.9));
    }
}
