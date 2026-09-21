using Mavi.Application.Modules.Intelligence;

namespace Mavi.Application.Tests;

public sealed class TrackCursorSigningKeyTests
{
    private const string WellFormed = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=";

    [Fact]
    public void AConfiguredKeyIsExactly32Base64Bytes()
    {
        var key = TrackCursorSigningKey.FromOptions(new TrackSearchOptions { CursorSigningKey = WellFormed });

        Assert.False(key.IsEphemeral);
        Assert.True(TrackCursorSigningKey.IsWellFormed(WellFormed));
        Assert.True(TrackCursorSigningKey.IsWellFormed(" " + WellFormed + " "));
    }

    [Theory]
    [InlineData("not-base64")]
    [InlineData("AAEC")]
    [InlineData("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8fIA==")]
    public void AMalformedConfiguredKeyIsRefusedEvenWhenEphemeralIsAllowed(string value)
    {
        Assert.False(TrackCursorSigningKey.IsWellFormed(value));
        Assert.Throws<InvalidOperationException>(() =>
            TrackCursorSigningKey.FromOptions(new TrackSearchOptions
            {
                CursorSigningKey = value,
                AllowEphemeralCursorSigningKey = true,
            }));
    }

    [Fact]
    public void NoKeyIsAnErrorUnlessEphemeralIsAllowed()
    {
        Assert.Throws<InvalidOperationException>(() =>
            TrackCursorSigningKey.FromOptions(new TrackSearchOptions()));

        var ephemeral = TrackCursorSigningKey.FromOptions(new TrackSearchOptions { AllowEphemeralCursorSigningKey = true });
        Assert.True(ephemeral.IsEphemeral);
    }

    [Fact]
    public void TwoEphemeralKeysNeverVerifyEachOther()
    {
        var first = TrackCursorSigningKey.CreateEphemeral();
        var second = TrackCursorSigningKey.CreateEphemeral();
        var position = new TrackAnalyticsCursorPosition(
            new TrackCursorPosition(
                new DateTimeOffset(2026, 9, 21, 11, 0, 0, TimeSpan.Zero), 1,
                new DateTimeOffset(2026, 9, 21, 10, 0, 0, TimeSpan.Zero), Guid.CreateVersion7(), new string('a', 64)),
            new TrackAnalyticsPinnedIdentity(Guid.CreateVersion7(), Guid.CreateVersion7(), "scene-analytics-v1"),
            new TrackAnalyticsCoverage(null, "scene-analytics-v1", 1, 0, 0, 0, 0, 0, 1, 0));

        var encoded = TrackCursorCodec.EncodeAnalytic(position, first);

        Assert.True(TrackCursorCodec.TryDecodeAnalytic(encoded, first, out _));
        Assert.False(TrackCursorCodec.TryDecodeAnalytic(encoded, second, out _));
    }

    [Fact]
    public void TheKeyNeverAppearsInItsStringForm()
    {
        var key = TrackCursorSigningKey.FromOptions(new TrackSearchOptions { CursorSigningKey = WellFormed });

        Assert.DoesNotContain(WellFormed, key.ToString(), StringComparison.Ordinal);
        Assert.DoesNotContain("AAEC", key.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public void FromBytesRefusesTheWrongLength() =>
        Assert.Throws<ArgumentException>(() => TrackCursorSigningKey.FromBytes(new byte[31]));
}
