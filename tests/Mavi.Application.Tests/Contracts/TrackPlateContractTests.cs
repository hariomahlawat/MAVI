using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Api.Tracks;

namespace Mavi.Application.Tests.Contracts;

/// <summary>
/// The Stage-4 plate additions to the Track wire contracts (plan §5.4). Every member list is pinned
/// exactly, in order: PR-5 builds the operator UI against these shapes.
/// </summary>
public sealed class TrackPlateContractTests
{
    private static readonly JsonSerializerOptions ApiJson = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        NumberHandling = JsonNumberHandling.Strict,
    };

    private static readonly DateTimeOffset At = new(2026, 10, 13, 6, 30, 0, TimeSpan.Zero);
    private static readonly Guid PlateObservationId = Guid.Parse("0199a1f0-0000-7000-8000-00000000f001");
    private const string Fingerprint = "521d596506f98622a5d4e49e8b8a6f7d51c0ec7d8199f257ef097e4db723eb25";

    private static readonly string[] OrdinaryItemMembers =
    [
        "id", "processingRunId", "videoAssetId", "cameraId", "cameraCode", "cameraName", "objectClass",
        "startTimestampUtc", "endTimestampUtc", "startOffsetMs", "endOffsetMs", "durationMs", "detectionCount",
        "meanConfidence", "maxConfidence", "reviewStatus", "thumbnailArtifactId", "thumbnailContentUrl", "videoContentUrl",
    ];

    private static TrackSearchItemResponse Item(TrackItemPlateResponse? plate = null) => new(
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a01"),
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a02"),
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a03"),
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a04"),
        "CAM-01", "North Gate", "Vehicle",
        At, At.AddSeconds(8), 60_000, 68_000, 8_000, 40, 0.91, 0.98, "Unreviewed",
        null, null, "/api/videos/0199a1f0-0000-7000-8000-000000000a03/content",
        Plate: plate);

    private static JsonElement Serialize<T>(T value)
    {
        using var document = JsonDocument.Parse(JsonSerializer.Serialize(value, ApiJson));
        return document.RootElement.Clone();
    }

    private static string[] Members(JsonElement element) => element.EnumerateObject().Select(member => member.Name).ToArray();

    [Fact]
    public void AnOrdinarySearchCarriesNoPlateMember()
    {
        var root = Serialize(new TrackSearchResponse([Item()], null));

        Assert.Equal(["items", "nextCursor"], Members(root));
        Assert.Equal(OrdinaryItemMembers, Members(root.GetProperty("items")[0]));
    }

    [Fact]
    public void APlateSearchCarriesTheCoverageBlockAndTheItemExplanation()
    {
        var plate = new TrackItemPlateResponse("KA01AB1234", "contains", 3, 4, 2, 0.92, PlateObservationId);
        var coverage = new PlateCoverageResponse(Fingerprint, 840, 812, 28, 0, 0, 0);
        var root = Serialize(new TrackSearchResponse([Item(plate)], "cursor", null, coverage));

        Assert.Equal(["items", "nextCursor", "plateCoverage"], Members(root));
        Assert.Equal(
            ["identityFingerprint", "vehicleTracksInScope", "ready", "pending", "failed", "stale", "notConfigured"],
            Members(root.GetProperty("plateCoverage")));
        Assert.Equal([.. OrdinaryItemMembers, "plate"], Members(root.GetProperty("items")[0]));
        var item = root.GetProperty("items")[0].GetProperty("plate");
        Assert.Equal(
            ["matchedText", "matchKind", "supportCount", "plateObservationCount", "distinctTextCount", "maxConfidence", "bestPlateObservationId"],
            Members(item));
        Assert.Equal("KA01AB1234", item.GetProperty("matchedText").GetString());
        Assert.Equal(0.92, item.GetProperty("maxConfidence").GetDouble());
    }

    [Fact]
    public void ANotConfiguredCoverageKeepsItsMemberListWithANullFingerprint()
    {
        var root = Serialize(new TrackSearchResponse([], null, null, new PlateCoverageResponse(null, 12, 0, 0, 0, 0, 12)));
        var block = root.GetProperty("plateCoverage");

        Assert.Equal(7, Members(block).Length);
        Assert.Equal(JsonValueKind.Null, block.GetProperty("identityFingerprint").ValueKind);
        Assert.Equal(12, block.GetProperty("notConfigured").GetInt32());
    }

    [Fact]
    public void ACombinedSearchCarriesBothCoverageBlocks()
    {
        var analytics = new Mavi.Contracts.Api.Analytics.AnalyticsCoverageResponse(Guid.NewGuid(), "scene-analytics-v1", 3, 0, 0, 0, 0, 0, 10, 0);
        var root = Serialize(new TrackSearchResponse([], null, analytics, new PlateCoverageResponse(Fingerprint, 1, 1, 0, 0, 0, 0)));

        Assert.Equal(["items", "nextCursor", "analyticsCoverage", "plateCoverage"], Members(root));
    }

    [Fact]
    public void AReadyVehicleDetailCarriesEveryPlateMember()
    {
        var plates = new TrackPlatesResponse(
            "Ready",
            "Analysed",
            null,
            "conflicting",
            [new TrackPlateTextResponse("KA01AB1234", 2, 0.97, PlateObservationId)],
            [
                new TrackPlateObservationResponse(
                    PlateObservationId, Guid.NewGuid(), "NearView", 1_200, 30, At, new TrackPlateBoxResponse(150, 240, 118, 30, 412, 330),
                    0.95, "Read",
                    [
                        new TrackPlateReadingResponse(0, "KA 01 AB 1234", 1, "KA01AB1234", "ok", 0.97, "in-standard"),
                        new TrackPlateReadingResponse(1, "KA01AB12З4", 1, null, "rejected", 0.6, null),
                    ]),
                new TrackPlateObservationResponse(
                    Guid.NewGuid(), Guid.NewGuid(), "Representative", 0, 0, At, new TrackPlateBoxResponse(1, 2, 3, 4, 100, 80),
                    0.4, "Unreadable", []),
            ],
            new TrackPlateProvenanceResponse(
                Guid.NewGuid(), "mavi-model-v2-" + new string('4', 64), "mavi-model-v2-" + new string('3', 64),
                new TrackPlateNormalisationResponse("mavi-plate-normalisation-v1", new string('6', 64)),
                new TrackPlateSummaryPolicyResponse("plate-track-text-rank0", "1.0.0", new string('1', 64)),
                At));

        var root = Serialize(plates);

        Assert.Equal(["readiness", "trackOutcome", "agreement", "texts", "observations", "provenance"], Members(root));
        Assert.Equal(["normalisedText", "supportCount", "maxConfidence", "bestPlateObservationId"], Members(root.GetProperty("texts")[0]));
        var observation = root.GetProperty("observations")[0];
        Assert.Equal(
            ["plateObservationId", "sourceObservationId", "role", "offsetMs", "sourceFrameNumber", "timestampUtc", "box",
             "detectorConfidence", "outcome", "readings"],
            Members(observation));
        Assert.Equal(["x", "y", "width", "height", "cropWidth", "cropHeight"], Members(observation.GetProperty("box")));
        Assert.Equal(
            ["rank", "rawText", "rawLineCount", "normalisedText", "normalisationOutcome", "confidence", "formatClass"],
            Members(observation.GetProperty("readings")[0]));
        // A rejected reading has neither a normalised text nor a format class: never searchable.
        Assert.Equal(["rank", "rawText", "rawLineCount", "normalisationOutcome", "confidence"], Members(observation.GetProperty("readings")[1]));
        Assert.Empty(root.GetProperty("observations")[1].GetProperty("readings").EnumerateArray());
        Assert.Equal(
            ["analysisId", "plateDetectorModelPackId", "ocrModelPackId", "normalisation", "summaryPolicy", "completedAtUtc"],
            Members(root.GetProperty("provenance")));
        Assert.Equal(["id", "sha256"], Members(root.GetProperty("provenance").GetProperty("normalisation")));
        Assert.Equal(["id", "version", "sha256"], Members(root.GetProperty("provenance").GetProperty("summaryPolicy")));
    }

    [Fact]
    public void AnUnavailableTrackStatesItsReasonAndNoAgreement()
    {
        var root = Serialize(new TrackPlatesResponse("Ready", "Unavailable", "evidence_missing", null, [], [], null));

        Assert.Equal(["readiness", "trackOutcome", "unavailableReason", "texts", "observations"], Members(root));
    }

    [Theory]
    [InlineData("Pending")]
    [InlineData("NotConfigured")]
    [InlineData("Failed")]
    [InlineData("Stale")]
    public void ANotReadyTrackCarriesOnlyItsReadiness(string readiness)
    {
        var root = Serialize(new TrackPlatesResponse(readiness, null, null, null, [], [], null));

        Assert.Equal(["readiness", "texts", "observations"], Members(root));
        Assert.Contains(readiness, TrackSearchContractRules.PlateReadinessValues);
    }

    [Fact]
    public void APersonDetailOmitsThePlatesBlock()
    {
        var detail = new TrackDetailResponse(
            Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid(),
            new TrackCameraResponse(Guid.NewGuid(), "CAM-01", "North Gate"),
            "Person", 1, 0, 8_000, At, At.AddSeconds(8), 8_000, 40, 0.9, 0.95, "Unreviewed",
            new TrackProcessingResponse("phase1-v1", null, null, null, null, At),
            new TrackVideoResponse(At, At.AddMinutes(1), 60_000, 1920, 1080, 25, 1, "/api/videos/x/content"),
            null, [], null, null);

        Assert.False(Serialize(detail).TryGetProperty("plates", out _));
        var withPlates = Serialize(detail with { ObjectClass = "Vehicle", Plates = new TrackPlatesResponse("Pending", null, null, null, [], [], null) });
        Assert.Equal("plates", Members(withPlates)[^1]);
    }

    [Fact]
    public void TheGrammarAndVocabulariesArePinned()
    {
        Assert.Equal("plateText", TrackSearchContractRules.PlateTextKey);
        Assert.Equal("plateMatch", TrackSearchContractRules.PlateMatchKey);
        Assert.Equal(["contains", "prefix", "exact"], TrackSearchContractRules.PlateMatchValues);
        Assert.Equal("contains", TrackSearchContractRules.DefaultPlateMatch);
        Assert.Equal(3, TrackSearchContractRules.MinimumPlateTextLength);
        Assert.Equal(15, TrackSearchContractRules.MaximumPlateTextLength);
        Assert.Equal(["NotConfigured", "Pending", "Ready", "Failed", "Stale"], TrackSearchContractRules.PlateReadinessValues);
        Assert.Equal(["none", "single", "consistent", "conflicting"], TrackSearchContractRules.PlateAgreementValues);
        Assert.Equal(["Analysed", "Unavailable"], TrackSearchContractRules.PlateTrackOutcomeValues);
        // The plate keys are ordinary, cross-camera filters: none makes a query analytics-dependent.
        Assert.DoesNotContain(TrackSearchContractRules.PlateTextKey, TrackSearchContractRules.AnalyticsQueryKeys);
        Assert.DoesNotContain(TrackSearchContractRules.PlateMatchKey, TrackSearchContractRules.AnalyticsQueryKeys);
    }
}
