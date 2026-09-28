using Mavi.Domain.Common;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Domain.Tests;

/// <summary>
/// The one canonical SHA-256 rule the domain shares (S2b plan §6): exactly 64 lower-case
/// hexadecimal characters. The aggregates that used to carry private copies keep behaving
/// exactly as before the extraction.
/// </summary>
public sealed class CanonicalSha256Tests
{
    public static TheoryData<string?> NonCanonical => new()
    {
        null,
        "",
        new string('a', 63),
        new string('a', 65),
        new string('A', 64),
        "g" + new string('a', 63),
        " " + new string('a', 63),
        new string('a', 63) + "\n",
        // Regex "$" also matches before a final newline; the rule must not.
        new string('a', 64) + "\n",
        // A full-width digit is a Unicode digit but not an ASCII hexadecimal one.
        "\uFF10" + new string('a', 63),
    };

    [Fact]
    public void AcceptsLowerCaseHexOfExactlySixtyFourCharacters()
    {
        Assert.True(CanonicalSha256.IsCanonical("0123456789abcdef" + new string('f', 48)));
    }

    [Theory]
    [MemberData(nameof(NonCanonical))]
    public void RefusesEverythingElse(string? value)
    {
        Assert.False(CanonicalSha256.IsCanonical(value));
    }

    [Fact]
    public void FormatsBytesAsLowerCaseHex()
    {
        var bytes = Enumerable.Range(0, 32).Select(value => (byte)(value * 7)).ToArray();

        var hex = CanonicalSha256.ToHex(bytes);

        Assert.True(CanonicalSha256.IsCanonical(hex));
        Assert.Equal(Convert.ToHexString(bytes).ToLowerInvariant(), hex);
    }

    [Fact]
    public void RefusesToFormatAnythingButThirtyTwoBytes()
    {
        Assert.Throws<ArgumentException>(() => CanonicalSha256.ToHex(new byte[31]));
    }

    // Regression pins for the aggregates that now share the rule.

    [Theory]
    [MemberData(nameof(NonCanonical))]
    public void VisionJobCompletionDigestStillRefusesNonCanonicalValues(string? value)
    {
        var job = VisionJob.Create(Guid.CreateVersion7(), "phase1-detection-tracking", DateTimeOffset.UnixEpoch);
        var exception = Assert.Throws<DomainValidationException>(() =>
            job.Complete("worker-01", leaseTokenMatches: true, DateTimeOffset.UnixEpoch, value!));
        Assert.Equal("vision_job_completion_digest_invalid", exception.Code);
    }

    [Theory]
    [MemberData(nameof(NonCanonical))]
    public void SceneAnalysisStillRefusesNonCanonicalParameters(string? value)
    {
        Assert.Throws<DomainValidationException>(() => SceneAnalysis.Queue(
            Guid.CreateVersion7(), Guid.CreateVersion7(), "scene-analytics-v1", value!, null, DateTimeOffset.UnixEpoch));
    }

    [Theory]
    [MemberData(nameof(NonCanonical))]
    public void ArtifactStillRefusesNonCanonicalSha256(string? value)
    {
        var exception = Assert.Throws<DomainValidationException>(() =>
            Artifact.Create(ArtifactType.EvidenceCrop, "evidence/a.jpg", "image/jpeg", 1, value!));
        Assert.Equal("artifact_sha256_invalid", exception.Code);
    }
}
