using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
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

    [Fact]
    public void V3ExampleMatchesItsPinnedFileHashAndDigest()
    {
        var root = FindRepositoryRoot();
        using var pinned = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "contracts/test-vectors/vision-job-complete-v3-digest.json")));
        var examplePath = Path.Combine(root, pinned.RootElement.GetProperty("example").GetString()!);
        var bytes = File.ReadAllBytes(examplePath);
        var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(bytes, Json)!;

        var result = new VisionResultValidator().Validate(
            request.JobId!.Value, request, pinned.RootElement.GetProperty("videoDurationMs").GetInt64());

        Assert.Equal(pinned.RootElement.GetProperty("exampleSha256").GetString(), Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant());
        Assert.Equal(CompletionSchema.V3, result.Schema);
        Assert.Equal(pinned.RootElement.GetProperty("completionDigest").GetString(), result.CompletionDigest);
    }

    [Fact]
    public void EveryV3InvalidVectorIsRejectedByBindingOrValidation()
    {
        using var vectors = JsonDocument.Parse(File.ReadAllText(Path.Combine(FindRepositoryRoot(), "contracts/test-vectors/control-plane-v3-invalid.json")));
        foreach (var vector in vectors.RootElement.EnumerateArray())
        {
            var name = vector.GetProperty("name").GetString()!;
            var payload = vector.GetProperty("payload").GetRawText();
            var rejected = false;
            try
            {
                var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(payload, Json)!;
                new VisionResultValidator().Validate(request.JobId!.Value, request, 3_600_000);
            }
            catch (JsonException)
            {
                rejected = true;
            }
            catch (VisionResultValidationException)
            {
                rejected = true;
            }

            Assert.True(rejected, $"Invalid completion 3.0 vector '{name}' was accepted by .NET.");
        }
    }

    [Fact]
    public void V3IntegerConformanceCorpusMatchesDotNetBinding()
    {
        var root = FindRepositoryRoot();
        var example = File.ReadAllText(Path.Combine(root, "contracts/examples/vision-job-complete-v3.example.json"));
        using var vectors = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "contracts/test-vectors/vision-job-complete-v3-conformance.json")));
        foreach (var vector in vectors.RootElement.GetProperty("integerCases").EnumerateArray())
        {
            var raw = WithToken(example, vector.GetProperty("path").GetString()!, vector.GetProperty("token").GetString()!);
            var accepted = true;
            try
            {
                JsonSerializer.Deserialize<VisionJobCompleteRequest>(raw, Json);
            }
            catch (JsonException)
            {
                accepted = false;
            }

            Assert.True(accepted == vector.GetProperty("accepted").GetBoolean(),
                $"Conformance vector '{vector.GetProperty("name").GetString()}' expected accepted={vector.GetProperty("accepted").GetBoolean()}.");
        }
    }

    /// <summary>Replaces the value at a JSON pointer with a literal number token, byte for byte.</summary>
    internal static string WithToken(string json, string pointer, string token)
    {
        const string placeholder = "__mavi_conformance_token__";
        var document = JsonNode.Parse(json)!;
        var parts = pointer.Trim('/').Split('/');
        var parent = document;
        foreach (var part in parts[..^1])
            parent = parent is JsonArray array ? array[int.Parse(part, System.Globalization.CultureInfo.InvariantCulture)]! : parent[part]!;
        if (parent is JsonArray target)
            target[int.Parse(parts[^1], System.Globalization.CultureInfo.InvariantCulture)] = placeholder;
        else
            parent[parts[^1]] = placeholder;
        return document.ToJsonString().Replace($"\"{placeholder}\"", token, StringComparison.Ordinal);
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln"))) directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("Repository root was not found.");
    }
}
