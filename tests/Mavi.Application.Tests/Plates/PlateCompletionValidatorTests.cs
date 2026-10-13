using System.Text;
using System.Text.Json;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Completion;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Contracts.Worker.Plates;
using Mavi.Domain.Plates;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// Phase A's plate rules and the artefact cross-check, on the checked-in examples (which the .NET digest
/// vector and the Python encoder both pin) and on single-rule mutations of them.
/// </summary>
public sealed class PlateCompletionValidatorTests
{
    private static readonly JsonSerializerOptions Web = new(JsonSerializerDefaults.Web);

    internal static string Root => CompletionDigestGoldenTests.FindRepositoryRoot();

    internal static byte[] Bytes(string relative) => File.ReadAllBytes(Path.Combine(Root, relative));

    internal static PlateLeaseContract Lease() =>
        JsonSerializer.Deserialize<PlateLeaseContract>(Bytes("contracts/examples/plate-lease-v1.example.json"), Web)!;

    internal static PlateCompleteRequest Request() =>
        JsonSerializer.Deserialize<PlateCompleteRequest>(Bytes("contracts/examples/plate-complete-v1.example.json"), Web)!;

    internal static PlateParameters Parameters() => PlateReleaseParser.ParseParameters(Bytes("tests/fixtures/plates/fixture-parameters-v1.json"));

    internal static IReadOnlyList<PlateCompletionTrackScope> Scope() => Lease().Tracks
        .Select(track => new PlateCompletionTrackScope(track.TrackId,
            track.Observations.Select(item => new PlateScopeObservation(item.ObservationId, item.Role, item.EvidenceRank)).ToList()))
        .ToList();

    internal static PlateIdentityFields Identity()
    {
        var identity = Lease().Identity;
        var capabilities = PlateReleaseParser.CanonicalCapabilities(
            identity.Capabilities.Select(item => new PlateCapabilityIdentity(item.CapabilityId, item.ModelPackId)).ToList());
        return new PlateIdentityFields(identity.Fingerprint, identity.PipelineId, identity.PipelineVersion, identity.PredictionsSchemaVersion,
            identity.Normalisation.Id, identity.Normalisation.Sha256, identity.SummaryPolicy.Id, identity.SummaryPolicy.Version,
            identity.SummaryPolicy.Sha256, capabilities, identity.ParametersSha256);
    }

    private static PlateCompletionValidation Validate(PlateCompleteRequest request, PlateParameters? parameters = null) =>
        PlateCompletionValidator.Validate(Lease().AnalysisId, request, Identity(), parameters ?? Parameters(), Scope());

    [Fact]
    public void TheExampleCompletionIsValidAndNormalisedByThePlatform()
    {
        var validation = Validate(Request());

        Assert.True(validation.IsValid, validation.ErrorCode);
        var completion = validation.Completion!;
        Assert.Equal(3, completion.TracksAnalysed);
        Assert.Equal(1, completion.TracksUnavailable);
        Assert.Equal(4, completion.PlateObservationsRead);
        Assert.Equal(1, completion.PlateObservationsUnreadable);
        var first = completion.Tracks[0];
        Assert.Equal(["KA01AB1234", "KA01AB1284"], first.Texts.Select(text => text.NormalisedText));
        var reading = first.Observations[0].Readings[0];
        Assert.Equal("KA 01 AB 1234", reading.RawText);
        Assert.Equal("KA01AB1234", reading.NormalisedText);
        Assert.Equal("in-standard", reading.FormatClass);
        var twoLine = completion.Tracks[2].Observations[0].Readings[0];
        Assert.Equal(2, twoLine.RawLineCount);
        Assert.Equal("MH12DE4321", twoLine.NormalisedText);
        // The digest is the pinned one.
        using var vector = JsonDocument.Parse(Bytes("contracts/test-vectors/plate-completion-v1-digest.json"));
        Assert.Equal(vector.RootElement.GetProperty("digest").GetString(), completion.CompletionDigest);
    }

    [Fact]
    public async Task TheExampleArtefactAgreesWithTheExampleCompletion()
    {
        var completion = Validate(Request()).Completion!;
        await using var stream = new MemoryStream(Bytes("contracts/examples/plate-predictions-v1.example.json"));

        var result = await PlatePredictionsValidator.ValidateAsync(stream,
            new PlatePredictionsValidator.Expectation(Lease().AnalysisId, Identity(), Parameters(), Scope(), completion), CancellationToken.None);

        Assert.Null(result.Error);
        // Track B's near-view was missing and Track D's only crop failed its integrity check: operator incidents.
        Assert.Equal([Lease().Tracks[1].Observations[1].ObservationId, Lease().Tracks[3].Observations[0].ObservationId],
            result.IntegrityIncidents);
    }

    public static TheoryData<string, string> Mutations() => new()
    {
        { "track order", "plate_track_coverage_invalid" },
        { "missing track", "plate_track_coverage_invalid" },
        { "unavailable without reason", "plate_track_outcome_invalid" },
        { "no accepted evidence with evidence", "plate_track_outcome_invalid" },
        { "box outside crop", "plate_observation_invalid" },
        { "second plate in a crop", "plate_observation_invalid" },
        { "detector below floor", "plate_observation_invalid" },
        { "reading below floor kept", "plate_reading_invalid" },
        { "reading rank gap", "plate_reading_invalid" },
        { "reading confidence rises", "plate_reading_invalid" },
        { "line count lies", "plate_reading_invalid" },
        { "raw text with NUL", "plate_reading_invalid" },
        { "unreadable with readings", "plate_reading_invalid" },
        { "read without readings", "plate_reading_invalid" },
        { "plate from an unleased crop", "plate_observation_invalid" },
        { "plates out of order", "plate_observation_order_invalid" },
        { "texts disagree", "plate_track_texts_invalid" },
        { "texts missing", "plate_track_texts_invalid" },
        { "provenance another pack", "plate_provenance_identity_mismatch" },
        { "provenance unverified pack claims verified", "plate_provenance_invalid" },
        { "descriptor media type", "plate_prediction_descriptor_invalid" },
        { "contract version", "worker_contract_version_unsupported" },
    };

    [Theory]
    [MemberData(nameof(Mutations))]
    public void EachRuleRefusesAloneWithItsCode(string mutation, string code)
    {
        var request = Mutate(Request(), mutation);
        var validation = Validate(request);
        Assert.False(validation.IsValid);
        Assert.Equal(code, validation.ErrorCode);
    }

    [Fact]
    public void AnExcludedRoleMakesATrackWithOnlyThatRoleHaveNoAcceptedEvidence()
    {
        var parameters = Parameters() with { ExcludedRoles = new HashSet<string>(StringComparer.Ordinal) { "near-view" } };
        // Track D's only crop is a near-view: excluded, it has nothing the profile reads.
        var request = Request();
        var tracks = request.Payload!.Tracks!.ToList();
        tracks[3] = tracks[3] with { Reason = "no_accepted_evidence" };
        // Track A's near-view plate cannot be reported any more.
        var validation = Validate(request with { Payload = request.Payload with { Tracks = tracks } }, parameters);
        Assert.Equal("plate_observation_invalid", validation.ErrorCode);
    }

    [Fact]
    public void TheDigestMovesWithEveryFactButNotWithTheWorker()
    {
        var baseline = Validate(Request()).Completion!.CompletionDigest;
        var otherWorker = Validate(Request() with { WorkerId = "plates-02" }).Completion!.CompletionDigest;
        Assert.Equal(baseline, otherWorker);
        var request = Request();
        var tracks = request.Payload!.Tracks!.ToList();
        var observations = tracks[0].PlateObservations!.ToList();
        observations[0] = observations[0] with { DetectorConfidence = 0.9 };
        tracks[0] = tracks[0] with { PlateObservations = observations };
        Assert.NotEqual(baseline, Validate(request with { Payload = request.Payload with { Tracks = tracks } }).Completion!.CompletionDigest);
    }

    public static TheoryData<string> ArtefactMutations() =>
    [
        "\"identityFingerprint\":\"5",
        "\"status\":\"scored\"",
        "\"score\":0.95",
        "\"rawText\":\"KA01AB1234\"",
        "\"outcome\":\"unreadable\"",
        "\"supportCount\":2",
        "\"role\":\"late-diverse\"",
    ];

    [Theory]
    [MemberData(nameof(ArtefactMutations))]
    public async Task AnArtefactThatDisagreesWithTheCompletionIsRefused(string anchor)
    {
        var completion = Validate(Request()).Completion!;
        var text = Encoding.UTF8.GetString(Bytes("contracts/examples/plate-predictions-v1.example.json"));
        Assert.Contains(anchor, text, StringComparison.Ordinal);
        var replacement = anchor switch
        {
            "\"identityFingerprint\":\"5" => "\"identityFingerprint\":\"6",
            "\"status\":\"scored\"" => "\"status\":\"abstained\"",
            "\"score\":0.95" => "\"score\":0.96",
            "\"rawText\":\"KA01AB1234\"" => "\"rawText\":\"KA01AB1235\"",
            "\"outcome\":\"unreadable\"" => "\"outcome\":\"read\"",
            "\"supportCount\":2" => "\"supportCount\":3",
            "\"role\":\"late-diverse\"" => "\"role\":\"near-view\"",
            _ => throw new InvalidOperationException(),
        };
        var index = text.IndexOf(anchor, StringComparison.Ordinal);
        var mutated = string.Concat(text.AsSpan(0, index), replacement, text.AsSpan(index + anchor.Length));
        await using var stream = new MemoryStream(Encoding.UTF8.GetBytes(mutated));

        var result = await PlatePredictionsValidator.ValidateAsync(stream,
            new PlatePredictionsValidator.Expectation(Lease().AnalysisId, Identity(), Parameters(), Scope(), completion), CancellationToken.None);

        Assert.Equal(PlatePredictionsValidator.InvalidCode, result.Error);
    }

    [Fact]
    public async Task AnArtefactBeyondTheBoundedProfileIsRefused()
    {
        var completion = Validate(Request()).Completion!;
        var text = Encoding.UTF8.GetString(Bytes("contracts/examples/plate-predictions-v1.example.json"));
        // A third detector proposal in a crop that already records two.
        const string anchor = "{\"box\":[8,10,30,9],\"plate\":null,\"score\":0.18}";
        Assert.Contains(anchor, text, StringComparison.Ordinal);
        var mutated = text.Replace(anchor, anchor + ",{\"box\":[1,1,2,2],\"plate\":null,\"score\":0.1}", StringComparison.Ordinal);
        await using var stream = new MemoryStream(Encoding.UTF8.GetBytes(mutated));

        var result = await PlatePredictionsValidator.ValidateAsync(stream,
            new PlatePredictionsValidator.Expectation(Lease().AnalysisId, Identity(), Parameters(), Scope(), completion), CancellationToken.None);

        Assert.Equal(PlatePredictionsValidator.InvalidCode, result.Error);
    }

    // --- Mutations ---------------------------------------------------------------------------

    private static PlateCompleteRequest Mutate(PlateCompleteRequest request, string mutation)
    {
        var payload = request.Payload!;
        var tracks = payload.Tracks!.ToList();
        PlateCompleteRequest WithTracks() => request with { Payload = payload with { Tracks = tracks } };
        PlateTrackResultContract EditObservation(int track, int index, Func<PlateObservationResultContract, PlateObservationResultContract> edit)
        {
            var observations = tracks[track].PlateObservations!.ToList();
            observations[index] = edit(observations[index]);
            return tracks[track] with { PlateObservations = observations };
        }

        PlateObservationResultContract EditReading(PlateObservationResultContract observation, int index, Func<PlateReadingContract, PlateReadingContract> edit)
        {
            var readings = observation.Readings!.ToList();
            readings[index] = edit(readings[index]);
            return observation with { Readings = readings };
        }

        switch (mutation)
        {
            case "track order":
                (tracks[0], tracks[1]) = (tracks[1], tracks[0]);
                return WithTracks();
            case "missing track":
                tracks.RemoveAt(1);
                return WithTracks();
            case "unavailable without reason":
                tracks[3] = tracks[3] with { Reason = null };
                return WithTracks();
            case "no accepted evidence with evidence":
                tracks[3] = tracks[3] with { Reason = "no_accepted_evidence" };
                return WithTracks();
            case "box outside crop":
                tracks[0] = EditObservation(0, 0, item => item with { Box = item.Box! with { X = 200 } });
                return WithTracks();
            case "second plate in a crop":
                tracks[0] = EditObservation(0, 0, item => item with { PlateIndex = 1 });
                return WithTracks();
            case "detector below floor":
                tracks[0] = EditObservation(0, 0, item => item with { DetectorConfidence = 0.2 });
                return WithTracks();
            case "reading below floor kept":
                tracks[0] = EditObservation(0, 0, item => EditReading(item, 1, reading => reading with { Confidence = 0.49 }));
                return WithTracks();
            case "reading rank gap":
                tracks[0] = EditObservation(0, 0, item => EditReading(item, 1, reading => reading with { Rank = 2 }));
                return WithTracks();
            case "reading confidence rises":
                tracks[0] = EditObservation(0, 0, item => EditReading(item, 1, reading => reading with { Confidence = 0.9 }));
                return WithTracks();
            case "line count lies":
                tracks[0] = EditObservation(0, 0, item => EditReading(item, 0, reading => reading with { RawLineCount = 2 }));
                return WithTracks();
            case "raw text with NUL":
                tracks[0] = EditObservation(0, 0, item => EditReading(item, 0, reading => reading with { RawText = "KA\u000001" }));
                return WithTracks();
            case "unreadable with readings":
                tracks[0] = EditObservation(0, 3, item => item with
                {
                    Readings = [new PlateReadingContract(0, "KA0", 1, 0.31)],
                });
                return WithTracks();
            case "read without readings":
                tracks[0] = EditObservation(0, 0, item => item with { Readings = [] });
                return WithTracks();
            case "plate from an unleased crop":
                tracks[0] = EditObservation(0, 0, item => item with { SourceObservationId = Guid.NewGuid() });
                return WithTracks();
            case "plates out of order":
            {
                var observations = tracks[0].PlateObservations!.ToList();
                (observations[0], observations[1]) = (observations[1], observations[0]);
                tracks[0] = tracks[0] with { PlateObservations = observations };
                return WithTracks();
            }
            case "texts disagree":
            {
                var texts = tracks[0].Texts!.ToList();
                texts[0] = texts[0] with { SupportCount = 1 };
                tracks[0] = tracks[0] with { Texts = texts };
                return WithTracks();
            }
            case "texts missing":
                tracks[2] = tracks[2] with { Texts = [] };
                return WithTracks();
            case "provenance another pack":
            {
                var capabilities = request.Provenance!.Capabilities!.ToList();
                capabilities[0] = capabilities[0] with { ModelPackId = "mavi-model-v2-" + new string('9', 64) };
                return request with { Provenance = request.Provenance with { Capabilities = capabilities } };
            }
            case "provenance unverified pack claims verified":
            {
                var capabilities = request.Provenance!.Capabilities!.ToList();
                capabilities[0] = capabilities[0] with { VerificationStatus = "verified" };
                return request with { Provenance = request.Provenance with { Capabilities = capabilities } };
            }
            case "descriptor media type":
                return request with { Payload = payload with { PredictionArtifact = payload.PredictionArtifact! with { MediaType = "text/plain" } } };
            case "contract version":
                return request with { SchemaVersion = "mavi-plate-control-v0" };
            default:
                throw new InvalidOperationException(mutation);
        }
    }
}
