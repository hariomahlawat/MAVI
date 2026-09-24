using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Tracks;

namespace Mavi.Application.Tests.Contracts;

/// <summary>
/// The Slice 4 additions to the Track contracts (plan §S "Response contracts"): an
/// ordinary search response is unchanged on the wire, an analytic one carries the §H
/// coverage block with Track accounting, and the detail block mirrors the persisted
/// fact families.
/// </summary>
public sealed class TrackAnalyticsContractTests
{
    private static readonly JsonSerializerOptions ApiJson = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        NumberHandling = JsonNumberHandling.Strict,
    };

    private static readonly Guid RevisionId = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid ZoneId = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");
    private static readonly Guid LineId = Guid.Parse("0199a1f0-0000-7000-8000-00000000e001");
    private static readonly DateTimeOffset At = new(2026, 9, 21, 6, 30, 0, TimeSpan.Zero);

    private static TrackSearchItemResponse Item(TrackItemAnalyticsResponse? analytics = null) => new(
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a01"),
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a02"),
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a03"),
        Guid.Parse("0199a1f0-0000-7000-8000-000000000a04"),
        "CAM-01", "North Gate", "Person",
        At, At.AddSeconds(8), 60_000, 68_000, 8_000, 40, 0.91, 0.98, "Unreviewed",
        null, null, "/api/videos/0199a1f0-0000-7000-8000-000000000a03/content",
        analytics);

    [Fact]
    public void AnOrdinarySearchResponseHasNoAnalyticsMembersOnTheWire()
    {
        var json = JsonSerializer.Serialize(new TrackSearchResponse([Item()], null), ApiJson);
        using var document = JsonDocument.Parse(json);

        Assert.False(document.RootElement.TryGetProperty("analyticsCoverage", out _));
        Assert.False(document.RootElement.GetProperty("items")[0].TryGetProperty("analytics", out _));
        Assert.Equal(["items", "nextCursor"], document.RootElement.EnumerateObject().Select(x => x.Name));
    }

    [Fact]
    public void AnAnalyticSearchResponseCarriesCoverageWithTrackAccounting()
    {
        var coverage = new AnalyticsCoverageResponse(RevisionId, "scene-analytics-v1", 3, 1, 0, 0, 1, 0, 27, 2);
        var analytics = new TrackItemAnalyticsResponse(
            RevisionId,
            "scene-analytics-v1",
            [new TrackItemZoneAnalyticsResponse(ZoneId, 2, 14_000, true)],
            [new TrackItemLineAnalyticsResponse(LineId, 1, "aToB", At.AddSeconds(2))],
            new TrackItemMotionAnalyticsResponse("NE", 5_000));

        var json = JsonSerializer.Serialize(new TrackSearchResponse([Item(analytics)], "cursor", coverage), ApiJson);
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        var block = root.GetProperty("analyticsCoverage");
        Assert.Equal(RevisionId, block.GetProperty("sceneRevisionId").GetGuid());
        Assert.Equal(27, block.GetProperty("analysedTracks").GetInt32());
        Assert.Equal(2, block.GetProperty("unavailableTracks").GetInt32());
        Assert.False(block.GetProperty("complete").GetBoolean());

        var item = root.GetProperty("items")[0].GetProperty("analytics");
        Assert.Equal("aToB", item.GetProperty("lines")[0].GetProperty("matchedDirection").GetString());
        Assert.Equal("NE", item.GetProperty("motion").GetProperty("heading").GetString());
        // Bounded by construction: a row never carries visit or crossing histories.
        Assert.False(item.TryGetProperty("zoneVisits", out _));
        Assert.False(item.TryGetProperty("lineCrossings", out _));
    }

    [Fact]
    public void UnavailableTracksDoNotMakeCoverageIncomplete()
    {
        var coverage = new AnalyticsCoverageResponse(RevisionId, "scene-analytics-v1", 3, 0, 0, 0, 0, 0, 20, 5);

        Assert.True(coverage.Complete);
        Assert.Equal(5, coverage.UnavailableTracks);
    }

    [Fact]
    public void TheDetailAnalyticsBlockIsOmittedUntilResolvedAndTypedWhenPresent()
    {
        var withoutAnalytics = JsonSerializer.Serialize(
            new TrackDetailResponse(
                Guid.NewGuid(), Guid.NewGuid(), Guid.NewGuid(),
                new TrackCameraResponse(Guid.NewGuid(), "CAM-01", "North Gate"),
                "Person", 1, 0, 8_000, At, At.AddSeconds(8), 8_000, 40, 0.9, 0.95, "Unreviewed",
                new TrackProcessingResponse("phase1-v1", null, null, null, null, At),
                new TrackVideoResponse(At, At.AddMinutes(1), 60_000, 1920, 1080, 25, 1, "/api/videos/x/content"),
                null, [], null, null),
            ApiJson);
        using (var document = JsonDocument.Parse(withoutAnalytics))
        {
            Assert.False(document.RootElement.TryGetProperty("analytics", out _));
        }

        var analytics = new TrackDetailAnalyticsResponse(
            RevisionId, 4, "scene-analytics-v1", "Analysed", null, "bbox-centre", 120, 1, 400,
            [new TrackDetailZoneSummaryResponse(ZoneId, 1, 4_000, At, At.AddSeconds(4), true, 45, 4_000)],
            [new TrackDetailZoneVisitResponse(ZoneId, 0, 1_000, 5_000, At, At.AddSeconds(4), 4_000, false, false, false, "NE", "SW")],
            [new TrackDetailLineCrossingResponse(LineId, 0, 2_000, At.AddSeconds(2), "aToB", 0.25, 0.5)],
            new TrackDetailMotionSummaryResponse("NE", 0.42, 0.01, 2_500, 2_500, [new TrackStationaryIntervalResponse(1_000, 3_500)], [ZoneId]),
            [new TrackAnalyticsIdentitySummaryResponse(Guid.NewGuid(), 3, "scene-analytics-v1", "Superseded", "Analysed")]);

        var json = JsonSerializer.Serialize(analytics, ApiJson);
        using var parsed = JsonDocument.Parse(json);
        var root = parsed.RootElement;
        Assert.Equal("Analysed", root.GetProperty("status").GetString());
        Assert.Equal(4, root.GetProperty("sceneRevisionNumber").GetInt32());
        Assert.Equal("aToB", root.GetProperty("lineCrossings")[0].GetProperty("direction").GetString());
        Assert.Equal(1_000, root.GetProperty("motion").GetProperty("stationaryIntervals")[0].GetProperty("startOffsetMs").GetInt64());
        Assert.Equal("Superseded", root.GetProperty("otherIdentities")[0].GetProperty("unitStatus").GetString());
        // Internal analysis ids are not operator-facing and have no member here.
        Assert.DoesNotContain("analysisId", json, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void TrackAnalyticsStatusReusesExistingVocabulariesOnly()
    {
        // The two per-Track outcome kinds plus the five non-ready readiness words: no
        // fourth state vocabulary arrives with Slice 4 (UI/UX specification §29).
        Assert.Equal(
            ["Analysed", "Unavailable", "Pending", "Failed", "Stale", "NotConfigured", "Disabled"],
            TrackSearchContractRules.TrackAnalyticsStatusValues);
        foreach (var readiness in SceneAnalyticsContractRules.ReadinessValues.Where(x => x != "Ready"))
        {
            Assert.True(TrackSearchContractRules.IsTrackAnalyticsStatus(readiness));
        }
    }
}
