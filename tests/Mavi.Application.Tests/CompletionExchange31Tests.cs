using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Processing;
using Mavi.Contracts.Worker;
using Mavi.Domain.Processing;

namespace Mavi.Application.Tests;

/// <summary>
/// Completion exchange 3.1 (S1.4 B3 asynchronous finalization plan §5): a wire version of the
/// 3.0 body under the asynchronous acknowledgement, normalized to <see cref="CompletionSchema.V3"/>
/// with the 3.0 digest domain. Slice F1 defines the version; F2 accepts it at the endpoint.
/// </summary>
public sealed class CompletionExchange31Tests
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private static readonly Guid JobId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd761");
    private static readonly Guid RunId = Guid.Parse("018fa7b6-2b31-7f42-9f33-9fd9f6fdd762");
    private static readonly DateTimeOffset Accepted = new(2026, 9, 25, 2, 0, 0, TimeSpan.Zero);

    [Fact]
    public void A31BodyNormalizesToV3AndKeepsTheV3Digest()
    {
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        using var pinned = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "contracts/test-vectors/vision-job-complete-v3-digest.json")));
        var duration = pinned.RootElement.GetProperty("videoDurationMs").GetInt64();
        var v3Text = File.ReadAllText(Path.Combine(root, pinned.RootElement.GetProperty("example").GetString()!));
        var v31Text = File.ReadAllText(Path.Combine(root, "contracts/examples/vision-job-complete-v3.1.example.json"));
        Assert.Equal(v3Text.Replace("\"schemaVersion\": \"3.0\"", "\"schemaVersion\": \"3.1\""), v31Text);

        var v3 = JsonSerializer.Deserialize<VisionJobCompleteRequest>(v3Text, Json)!;
        var v31 = JsonSerializer.Deserialize<VisionJobCompleteRequest>(v31Text, Json)!;
        Assert.Equal("3.0", v3.SchemaVersion);
        Assert.Equal("3.1", v31.SchemaVersion);

        var validator = new VisionResultValidator();
        var v3Result = validator.Validate(v3.JobId!.Value, v3, duration);
        var v31Result = validator.Validate(v31.JobId!.Value, v31, duration);

        Assert.Equal(CompletionSchema.V3, v31Result.Schema);
        Assert.Equal(pinned.RootElement.GetProperty("completionDigest").GetString(), v3Result.CompletionDigest);
        Assert.Equal(v3Result.CompletionDigest, v31Result.CompletionDigest);
        Assert.Equal(v3Result.Tracks.Count, v31Result.Tracks.Count);
    }

    [Fact]
    public void TheRawSchemaVersionIsNotInTheDigestButTheContentIs()
    {
        // Same content, different wire version: same digest. Different content: different digest.
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        var node = JsonNode.Parse(File.ReadAllText(Path.Combine(root, "contracts/examples/vision-job-complete-v3.1.example.json")))!;
        var request = node.Deserialize<VisionJobCompleteRequest>(Json)!;
        var validator = new VisionResultValidator();
        var baseline = validator.Validate(request.JobId!.Value, request, 3_600_000).CompletionDigest;

        var changed = request with { FramesProcessed = request.FramesProcessed + 1 };

        Assert.NotEqual(baseline, validator.Validate(changed.JobId!.Value, changed, 3_600_000).CompletionDigest);
        Assert.Equal(baseline, validator.Validate(request.JobId!.Value, request with { SchemaVersion = "3.0" }, 3_600_000).CompletionDigest);
    }

    [Fact]
    public void Every30InvalidVectorIsStillRejectedAs31()
    {
        using var vectors = JsonDocument.Parse(File.ReadAllText(Path.Combine(
            CompletionDigestGoldenTests.FindRepositoryRoot(), "contracts/test-vectors/control-plane-v3-invalid.json")));
        var count = 0;
        foreach (var vector in vectors.RootElement.EnumerateArray())
        {
            var name = vector.GetProperty("name").GetString()!;
            var node = JsonNode.Parse(vector.GetProperty("payload").GetRawText())!.AsObject();
            if (node["schemaVersion"]?.GetValue<string>() != "3.0") continue; // the version vectors are 3.0-specific
            node["schemaVersion"] = "3.1";
            count++;
            var rejected = false;
            try
            {
                var request = node.Deserialize<VisionJobCompleteRequest>(Json)!;
                new VisionResultValidator().Validate(request.JobId!.Value, request, 3_600_000);
            }
            catch (JsonException) { rejected = true; }
            catch (VisionResultValidationException) { rejected = true; }

            Assert.True(rejected, $"Invalid vector '{name}' was accepted as completion 3.1.");
        }

        Assert.True(count > 0);
    }

    [Fact]
    public void UnknownVersionsAreStillRejectedByTheValidator()
    {
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(
            File.ReadAllText(Path.Combine(root, "contracts/examples/vision-job-complete-v3.example.json")), Json)!;

        foreach (var version in new[] { "3.2", "3", "3.10", " 3.1", "3.1 " })
        {
            var error = Assert.Throws<VisionResultValidationException>(() =>
                new VisionResultValidator().Validate(request.JobId!.Value, request with { SchemaVersion = version }, 3_600_000));
            Assert.Equal("schema_version_invalid", error.ReasonCode);
        }
    }

    [Fact]
    public void AcceptanceListsFollowTheActivationGate()
    {
        // Not activated (F2 alone): 2.0 and 3.0 synchronous, 3.1 refused.
        Assert.Equal(["2.0", "3.0"], WorkerContractRules.CompletionSchemaVersions(false));
        Assert.Equal(["2.0", "3.0"], WorkerContractRules.SynchronousCompletionSchemaVersions);
        Assert.True(WorkerContractRules.IsAcceptedCompletionSchemaVersion("2.0", false));
        Assert.True(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.0", false));
        Assert.False(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.1", false));

        // Activated with F3 (plan §15.2): 2.0 unchanged, 3.0 retired, 3.1 accepted and advertised.
        Assert.Equal(["2.0", "3.1"], WorkerContractRules.CompletionSchemaVersions(true));
        Assert.True(WorkerContractRules.IsAcceptedCompletionSchemaVersion("2.0", true));
        Assert.False(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.0", true));
        Assert.True(WorkerContractRules.IsAcceptedCompletionSchemaVersion("3.1", true));
        Assert.False(WorkerContractRules.IsAcceptedCompletionSchemaVersion(null, true));
        Assert.False(WorkerContractRules.IsAcceptedCompletionSchemaVersion(null, false));

        // Advertisement and acceptance are one decision: in both states exactly the advertised
        // versions are accepted, over every version the platform knows.
        foreach (var activated in new[] { false, true })
            foreach (var version in new[] { "2.0", "3.0", "3.1" })
                Assert.Equal(
                    WorkerContractRules.CompletionSchemaVersions(activated).Contains(version),
                    WorkerContractRules.IsAcceptedCompletionSchemaVersion(version, activated));

        Assert.Equal(["2.0", "3.1"], WorkerContractRules.AsynchronousCompletionSchemaVersions);
        Assert.Equal("3.1", WorkerContractRules.CompletionSchemaVersionV31);
        Assert.True(WorkerContractRules.IsKnownCompletionSchemaVersion("2.0"));
        Assert.True(WorkerContractRules.IsKnownCompletionSchemaVersion("3.0"));
        Assert.True(WorkerContractRules.IsKnownCompletionSchemaVersion("3.1"));
        Assert.False(WorkerContractRules.IsKnownCompletionSchemaVersion("3.2"));
        Assert.False(WorkerContractRules.IsKnownCompletionSchemaVersion(null));
        Assert.True(WorkerContractRules.IsAsynchronousCompletionSchemaVersion("3.1"));
        Assert.False(WorkerContractRules.IsAsynchronousCompletionSchemaVersion("3.0"));
        Assert.False(WorkerContractRules.IsAsynchronousCompletionSchemaVersion("2.0"));

        Assert.True(WorkerContractRules.IsFinalizationState("finalizing"));
        Assert.True(WorkerContractRules.IsFinalizationState("completed"));
        Assert.False(WorkerContractRules.IsFinalizationState("Finalizing"));
        Assert.False(WorkerContractRules.IsFinalizationState("failed"));
    }


    [Fact]
    public void RetainedFinalizationPayloadExcludesAuthenticationEnvelopeAndRevalidatesIdentically()
    {
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(
            File.ReadAllText(Path.Combine(root, "contracts/examples/vision-job-complete-v3.1.example.json")), Json)!;
        const string recognizableToken = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
        var authenticated = request with { WorkerId = "worker-secret-probe", LeaseToken = recognizableToken };

        var validator = new VisionResultValidator();
        var original = validator.Validate(authenticated.JobId!.Value, authenticated, 3_600_000);
        var bytes = VisionFinalizationPayloadCodec.Encode(authenticated);
        var retainedText = System.Text.Encoding.UTF8.GetString(bytes);

        Assert.DoesNotContain("leaseToken", retainedText, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("workerId", retainedText, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain(recognizableToken, retainedText, StringComparison.Ordinal);
        Assert.DoesNotContain("worker-secret-probe", retainedText, StringComparison.Ordinal);

        var reconstructed = VisionFinalizationPayloadCodec.Decode(bytes);
        Assert.Null(reconstructed.WorkerId);
        Assert.Null(reconstructed.LeaseToken);
        var replay = validator.Validate(reconstructed.JobId!.Value, reconstructed, 3_600_000);

        Assert.Equal(CompletionSchema.V3, replay.Schema);
        Assert.Equal(original.CompletionDigest, replay.CompletionDigest);
        Assert.Equal(original.AttemptCount, replay.AttemptCount);
        Assert.Equal(original.FramesProcessed, replay.FramesProcessed);
        Assert.Equal(original.ProcessingDurationMs, replay.ProcessingDurationMs);
        Assert.Equal(original.Tracks.Count, replay.Tracks.Count);
    }

    [Fact]
    public void FinalizationPayloadCodecRejectsNon31AndMalformedPayloads()
    {
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        var request = JsonSerializer.Deserialize<VisionJobCompleteRequest>(
            File.ReadAllText(Path.Combine(root, "contracts/examples/vision-job-complete-v3.1.example.json")), Json)!;

        var wrongVersion = Assert.Throws<VisionResultValidationException>(() =>
            VisionFinalizationPayloadCodec.Encode(request with { SchemaVersion = "3.0" }));
        Assert.Equal("finalization_payload_source_invalid", wrongVersion.ReasonCode);

        var malformed = Assert.Throws<VisionResultValidationException>(() =>
            VisionFinalizationPayloadCodec.Decode("{\"schemaVersion\":\"3.1\",\"unknown\":1}"u8));
        Assert.Equal("finalization_payload_invalid", malformed.ReasonCode);
    }

    [Fact]
    public void FinalizingResponseOmitsCompletedAtAndCompletedResponseCarriesIt()
    {
        var finalizing = VisionJobFinalizationResponse.Finalizing(JobId, RunId, Accepted, 3);
        var completed = VisionJobFinalizationResponse.Completed(JobId, RunId, Accepted, 3, Accepted.AddSeconds(90));

        var finalizingJson = JsonSerializer.Serialize(finalizing, Json);
        var completedJson = JsonSerializer.Serialize(completed, Json);

        Assert.True(JsonElement.DeepEquals(
            JsonDocument.Parse($$"""
                {"schemaVersion":"3.1","jobId":"{{JobId}}","processingRunId":"{{RunId}}","state":"finalizing",
                 "acceptedAtUtc":"2026-09-25T02:00:00Z","tracksSubmitted":3}
                """).RootElement,
            JsonDocument.Parse(finalizingJson).RootElement), finalizingJson);
        Assert.True(JsonElement.DeepEquals(
            JsonDocument.Parse($$"""
                {"schemaVersion":"3.1","jobId":"{{JobId}}","processingRunId":"{{RunId}}","state":"completed",
                 "acceptedAtUtc":"2026-09-25T02:00:00Z","tracksSubmitted":3,"completedAtUtc":"2026-09-25T02:01:30Z"}
                """).RootElement,
            JsonDocument.Parse(completedJson).RootElement), completedJson);
        Assert.DoesNotContain("tracksAccepted", finalizingJson, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("completedAtUtc", finalizingJson, StringComparison.Ordinal);

        // Round trip and strictness: an unknown member is refused like every worker contract.
        Assert.Equal(finalizing, JsonSerializer.Deserialize<VisionJobFinalizationResponse>(finalizingJson, Json));
        Assert.Equal(completed, JsonSerializer.Deserialize<VisionJobFinalizationResponse>(completedJson, Json));
        Assert.Throws<JsonException>(() => JsonSerializer.Deserialize<VisionJobFinalizationResponse>(
            finalizingJson.Replace("\"tracksSubmitted\"", "\"tracksAccepted\""), Json));
    }

    [Fact]
    public void ResponseExamplesValidateAgainstTheirSchemaShape()
    {
        var root = CompletionDigestGoldenTests.FindRepositoryRoot();
        var example = JsonSerializer.Deserialize<VisionJobFinalizationResponse>(
            File.ReadAllText(Path.Combine(root, "contracts/examples/vision-job-finalization-response-v3.1.example.json")), Json)!;

        Assert.Equal("3.1", example.SchemaVersion);
        Assert.Equal("finalizing", example.State);
        Assert.Null(example.CompletedAtUtc);
        Assert.Equal(VisionJobFinalizationResponse.Finalizing(example.JobId, example.ProcessingRunId, example.AcceptedAtUtc, example.TracksSubmitted), example);
    }

    [Theory]
    [InlineData(VisionJobStatus.Queued, "queued")]
    [InlineData(VisionJobStatus.Leased, "processing")]
    [InlineData(VisionJobStatus.Finalizing, "finalizing")]
    [InlineData(VisionJobStatus.Completed, "completed")]
    [InlineData(VisionJobStatus.Failed, "failed")]
    [InlineData(VisionJobStatus.Cancelled, "failed")]
    public void ProcessingPhaseFollowsTheJobStatus(VisionJobStatus status, string phase)
    {
        Assert.Equal(phase, ProcessingPhaseRule.FromJobStatus(status));
        Assert.Contains(phase, ProcessingPhases.Values);
    }

    [Fact]
    public void EveryJobStatusHasAPhaseAndThePhaseSetIsClosed()
    {
        foreach (var status in Enum.GetValues<VisionJobStatus>())
            Assert.Contains(ProcessingPhaseRule.FromJobStatus(status), ProcessingPhases.Values);
        Assert.Equal(["queued", "processing", "finalizing", "completed", "failed"], ProcessingPhases.Values);
        Assert.Throws<ArgumentOutOfRangeException>(() => ProcessingPhaseRule.FromJobStatus((VisionJobStatus)99));
    }
}
