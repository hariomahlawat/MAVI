using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Tests;

/// <summary>Pins the server-side completion digest of the golden contract examples.</summary>
public sealed class CompletionDigestGoldenTests
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    /// <summary>
    /// Digest of <c>vision-job-complete-v2.example.json</c> computed by the platform before
    /// completion 3.0 existed (main 3b82c0e). A v2 body must keep exactly this digest, so
    /// completed v2 jobs remain replay-idempotent across the upgrade.
    /// </summary>
    private const string V2ExampleDigest = "23b5b986bb38ca15c3c8e27d09d0edfa0694e1a831dde1aff6b925fbce565c06";

    [Fact]
    public void V2ExampleDigestIsUnchangedByCompletion3()
    {
        var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(
            File.ReadAllText(Path.Combine(FindRepositoryRoot(), "contracts/examples/vision-job-complete-v2.example.json")), Json)!;

        var result = new VisionResultValidator().Validate(request.JobId!.Value, request, 3_600_000);

        Assert.Equal(CompletionSchema.V2, result.Schema);
        Assert.Equal(V2ExampleDigest, result.CompletionDigest);
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln"))) directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("Repository root was not found.");
    }
}
