using Mavi.Application.Modules.Intelligence;
using System.Text.Json;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Tests;

public sealed class VisionResultValidatorCanonicalizationTests
{
    private static readonly Guid JobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");

    [Fact]
    public void NullAndLiteralNullOptionalProvenanceProduceDifferentDigests()
    {
        var validator = new VisionResultValidator();
        var withNull = validator.Validate(JobId, Request(Provenance()), 10_000);
        var withLiteral = validator.Validate(
            JobId,
            Request(Provenance() with { QualificationId = "<null>" }),
            10_000);

        Assert.NotEqual(withNull.CompletionDigest, withLiteral.CompletionDigest);
    }

    [Fact]
    public void ProvenanceEdgeConformanceCorpusMatchesDotNet()
    {
        var vectorsPath = Path.Combine(
            FindRepositoryRoot(),
            "contracts/test-vectors/vision-job-complete-v2-conformance.json");
        using var vectors = JsonDocument.Parse(File.ReadAllText(vectorsPath));
        var validator = new VisionResultValidator();

        foreach (var vector in vectors.RootElement.GetProperty("provenanceEdgeCases").EnumerateArray())
        {
            var name = vector.GetProperty("name").GetString()!;
            var value = vector.GetProperty("value").GetString()!;
            var accepted = vector.GetProperty("accepted").GetBoolean();

            var succeeded = true;
            try
            {
                validator.Validate(
                    JobId,
                    Request(Provenance() with { ModelId = value }),
                    10_000);
            }
            catch (VisionResultValidationException)
            {
                succeeded = false;
            }

            Assert.True(
                succeeded == accepted,
                $"Conformance vector '{name}' expected accepted={accepted} but .NET accepted={succeeded}.");
        }
    }

    [Fact]
    public void ProvenanceIdentityBoundsCountUnicodeScalars()
    {
        var validator = new VisionResultValidator();
        var exactly128Scalars = string.Concat(Enumerable.Repeat("😀", 128));
        var tooManyScalars = string.Concat(Enumerable.Repeat("😀", 129));

        var accepted = validator.Validate(
            JobId,
            Request(Provenance() with { ModelId = exactly128Scalars }),
            10_000);

        Assert.Equal(exactly128Scalars, accepted.DetectorName);
        Assert.Throws<VisionResultValidationException>(() =>
            validator.Validate(
                JobId,
                Request(Provenance() with { ModelId = tooManyScalars }),
                10_000));
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null &&
               !File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
            directory = directory.Parent;
        return directory?.FullName
            ?? throw new InvalidOperationException("Repository root was not found.");
    }

    private static VisionJobCompleteRequest Request(VisionRuntimeProvenanceContract provenance) =>
        new(
            "2.0",
            JobId,
            "gpu-sdd-01",
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            1,
            20,
            900,
            provenance,
            []);

    private static VisionRuntimeProvenanceContract Provenance() =>
        new(
            "rtmdet-m",
            "1",
            new string('1', 64),
            new string('2', 64),
            new string('3', 64),
            "phase1",
            "1",
            new string('4', 64),
            null,
            null,
            "unverified",
            "runtime-v1",
            new string('5', 64),
            "linux-x86_64-cpu",
            new string('6', 64),
            "mmdetection",
            new Dictionary<string, string>
            {
                ["python"] = "3.12.14",
                ["trackers"] = "2.6.0",
            },
            null,
            new VisionPlatformIdentityContract(
                "Linux",
                "6.8",
                "qualified",
                "x86_64",
                "x86_64",
                "3.12.14",
                "CPython",
                ["main", "Sep 2026"],
                "GCC"),
            "cpu",
            0,
            "cpu",
            null,
            "build-a",
            new string('a', 40),
            "every-frame",
            new VisionTrackerParametersContract(30, .25, .1, .2, 2, 1),
            "RGB");
}
