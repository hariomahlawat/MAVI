using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Api.Analytics;
using Mavi.Contracts.Api.Scene;

namespace Mavi.Application.Tests.Contracts;

/// <summary>
/// Slice 0 of Spatial &amp; Temporal Track Analytics freezes contract shapes only
/// (ADR-011). These tests pin the wire shape, the closed vocabularies, the
/// coverage-completeness rule and the absence of ownership secrets. They are the
/// canonical examples: the repository's <c>contracts/</c> directory is the worker
/// control-plane boundary and deliberately carries no API schemas.
/// </summary>
public sealed class SceneAnalyticsContractTests
{
    /// <summary>Mirrors the API's canonical JSON policy from <c>Program.cs</c>.</summary>
    private static readonly JsonSerializerOptions ApiJson = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        NumberHandling = JsonNumberHandling.Strict,
    };

    private static readonly Guid CameraId = Guid.Parse("0199a1f0-0000-7000-8000-00000000c001");
    private static readonly Guid RevisionId = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid ZoneId = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");
    private static readonly Guid LineId = Guid.Parse("0199a1f0-0000-7000-8000-00000000e001");
    private static readonly DateTimeOffset CreatedAt = new(2026, 9, 20, 6, 30, 0, TimeSpan.Zero);

    private static SceneRevisionResponse ConfiguredRevision() => new(
        RevisionId,
        4,
        CameraId,
        CreatedAt,
        SceneContractRules.UnattributedDevelopmentActor,
        "Gate and forecourt",
        null,
        null,
        Zones:
        [
            new SceneZoneResponse(
                ZoneId,
                "Forecourt",
                "Restricted",
                Enabled: true,
                Vertices:
                [
                    new ScenePointResponse(0.1, 0.5),
                    new ScenePointResponse(0.4, 0.5),
                    new ScenePointResponse(0.4, 0.9),
                    new ScenePointResponse(0.1, 0.9),
                ],
                LoiteringThresholdSeconds: 120),
        ],
        TripLines:
        [
            new SceneTripLineResponse(
                LineId,
                "Gate A",
                Enabled: true,
                new ScenePointResponse(0.6, 0.4),
                new ScenePointResponse(0.9, 0.4),
                Directed: true,
                "inbound",
                "outbound"),
        ]);

    // --- Example 1: a configured scene with one zone and one directed trip line.

    [Fact]
    public void ConfiguredSceneSerializesToTheCanonicalShape()
    {
        var scene = new CameraSceneResponse(
            CameraId,
            Configured: true,
            ConfiguredRevision(),
            History:
            [
                new SceneRevisionSummaryResponse(
                    RevisionId,
                    4,
                    CreatedAt,
                    SceneContractRules.UnattributedDevelopmentActor,
                    "Gate and forecourt",
                    AnalyticsEnabled: true,
                    ZoneCount: 1,
                    TripLineCount: 1),
            ]);

        var json = JsonSerializer.Serialize(scene, ApiJson);
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        Assert.True(root.GetProperty("configured").GetBoolean());
        var active = root.GetProperty("activeRevision");
        Assert.Equal(4, active.GetProperty("revisionNumber").GetInt32());
        Assert.True(active.GetProperty("analyticsEnabled").GetBoolean());
        Assert.Equal(
            SceneContractRules.UnattributedDevelopmentActor,
            active.GetProperty("createdBy").GetString());

        var zone = active.GetProperty("zones")[0];
        Assert.Equal("Restricted", zone.GetProperty("kind").GetString());
        Assert.Equal(4, zone.GetProperty("vertices").GetArrayLength());
        Assert.Equal(0.1, zone.GetProperty("vertices")[0].GetProperty("x").GetDouble(), 6);
        Assert.Equal(120, zone.GetProperty("loiteringThresholdSeconds").GetInt32());

        var line = active.GetProperty("tripLines")[0];
        Assert.True(line.GetProperty("directed").GetBoolean());
        Assert.Equal("inbound", line.GetProperty("aToBLabel").GetString());
        Assert.Equal("outbound", line.GetProperty("bToALabel").GetString());
    }

    [Fact]
    public void AnUnconfiguredCameraReportsNoActiveRevisionRatherThanAnEmptyOne()
    {
        var scene = new CameraSceneResponse(CameraId, Configured: false, null, []);

        var json = JsonSerializer.Serialize(scene, ApiJson);
        using var document = JsonDocument.Parse(json);

        Assert.False(document.RootElement.GetProperty("configured").GetBoolean());
        Assert.Equal(JsonValueKind.Null, document.RootElement.GetProperty("activeRevision").ValueKind);
    }

    [Fact]
    public void AnEmptyActiveRevisionReportsAnalyticsDisabled()
    {
        // ADR-011: an empty active revision is how an operator switches analytics
        // off. It is a real revision, not an absent configuration. The flag is
        // computed from the geometry, so it cannot be set to contradict it.
        var revision = ConfiguredRevision() with { Zones = [], TripLines = [] };
        var scene = new CameraSceneResponse(CameraId, Configured: true, revision, []);

        var json = JsonSerializer.Serialize(scene, ApiJson);
        using var document = JsonDocument.Parse(json);
        var active = document.RootElement.GetProperty("activeRevision");

        Assert.True(document.RootElement.GetProperty("configured").GetBoolean());
        Assert.False(active.GetProperty("analyticsEnabled").GetBoolean());
        Assert.Equal(0, active.GetProperty("zones").GetArrayLength());
    }

    [Fact]
    public void ARevisionWhoseGeometryIsAllDisabledIsAlsoDisabled()
    {
        // Geometry can be present but switched off; that is still "no analytics".
        var revision = ConfiguredRevision();
        var disabled = revision with
        {
            Zones = [revision.Zones[0] with { Enabled = false }],
            TripLines = [revision.TripLines[0] with { Enabled = false }],
        };

        Assert.True(revision.AnalyticsEnabled);
        Assert.False(disabled.AnalyticsEnabled);
    }

    // --- Requests: the server owns attribution and revision identity.

    [Fact]
    public void SaveSceneRequestRejectsACallerSuppliedActor()
    {
        const string payload = """
            {"note":"Gate and forecourt","createdBy":"a.operator"}
            """;

        var error = Assert.Throws<JsonException>(
            () => JsonSerializer.Deserialize<SaveSceneRequest>(payload, ApiJson));

        Assert.Contains("createdBy", error.Message, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData("""{"revisionId":"0199a1f0-0000-7000-8000-00000000b001"}""")]
    [InlineData("""{"revisionNumber":5}""")]
    [InlineData("""{"analyticsEnabled":true}""")]
    public void SaveSceneRequestRejectsServerOwnedMembers(string payload)
    {
        Assert.Throws<JsonException>(
            () => JsonSerializer.Deserialize<SaveSceneRequest>(payload, ApiJson));
    }

    [Fact]
    public void SaveSceneRequestAcceptsTheMembersACallerOwns()
    {
        const string payload = """
            {
              "expectedRevisionNumber": 3,
              "note": "Gate and forecourt",
              "zones": [
                {
                  "zoneId": "0199a1f0-0000-7000-8000-00000000d001",
                  "name": "Forecourt",
                  "kind": "Restricted",
                  "enabled": true,
                  "vertices": [{"x":0.1,"y":0.5},{"x":0.4,"y":0.5},{"x":0.4,"y":0.9}],
                  "loiteringThresholdSeconds": 120
                }
              ],
              "tripLines": []
            }
            """;

        var request = JsonSerializer.Deserialize<SaveSceneRequest>(payload, ApiJson);

        Assert.NotNull(request);
        Assert.Equal(3, request.ExpectedRevisionNumber);
        Assert.Equal(ZoneId, request.Zones![0].ZoneId);
        Assert.Equal(0.1, request.Zones[0].Vertices![0].X!.Value, 6);
        Assert.Empty(request.TripLines!);
    }

    [Fact]
    public void CoordinatesMustBeJsonNumbers()
    {
        // The API's canonical policy is NumberHandling.Strict; a quoted number is
        // a different value and must not be silently accepted.
        const string payload = """
            {"zones":[{"vertices":[{"x":"0.1","y":0.5}]}]}
            """;

        Assert.Throws<JsonException>(
            () => JsonSerializer.Deserialize<SaveSceneRequest>(payload, ApiJson));
    }

    [Fact]
    public void ReanalysisRequestRejectsUnknownMembers()
    {
        Assert.Throws<JsonException>(
            () => JsonSerializer.Deserialize<SceneReanalysisRequest>(
                """{"scope":"allRuns","requestedBy":"a.operator"}""",
                ApiJson));
    }

    // --- Analytics status and readiness.

    [Fact]
    public void RunAnalyticsSerializesReadinessAndUnitState()
    {
        var response = new ProcessingRunAnalyticsResponse(
            Guid.Parse("0199a1f0-0000-7000-8000-00000000a001"),
            "Ready",
            RevisionId,
            "scene-analytics-v1",
            [
                new SceneAnalysisStatusResponse(
                    Guid.Parse("0199a1f0-0000-7000-8000-00000000f001"),
                    Guid.Parse("0199a1f0-0000-7000-8000-00000000a001"),
                    RevisionId,
                    4,
                    "scene-analytics-v1",
                    "Completed",
                    AttemptCount: 1,
                    CreatedAt,
                    CreatedAt.AddSeconds(2),
                    CreatedAt.AddSeconds(5),
                    LeaseExpiresAtUtc: null,
                    AnalysedTrackCount: 212,
                    UnavailableTrackCount: 3,
                    FailureCode: null),
            ]);

        var json = JsonSerializer.Serialize(response, ApiJson);
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        Assert.Equal("Ready", root.GetProperty("readiness").GetString());
        var unit = root.GetProperty("analyses")[0];
        Assert.Equal("Completed", unit.GetProperty("status").GetString());
        Assert.Equal(1, unit.GetProperty("attemptCount").GetInt32());
        Assert.Equal(212, unit.GetProperty("analysedTrackCount").GetInt32());
        Assert.Equal(3, unit.GetProperty("unavailableTrackCount").GetInt32());
        Assert.Equal(JsonValueKind.Null, unit.GetProperty("failureCode").ValueKind);
    }

    [Fact]
    public void StatusAndReadinessVocabulariesAreClosed()
    {
        Assert.All(
            SceneAnalyticsContractRules.StatusValues,
            value => Assert.True(SceneAnalyticsContractRules.IsStatus(value)));
        Assert.All(
            SceneAnalyticsContractRules.ReadinessValues,
            value => Assert.True(SceneAnalyticsContractRules.IsReadiness(value)));

        Assert.False(SceneAnalyticsContractRules.IsStatus("Cancelled"));
        Assert.False(SceneAnalyticsContractRules.IsStatus("completed"));
        Assert.False(SceneAnalyticsContractRules.IsReadiness("Unknown"));
        Assert.False(SceneAnalyticsContractRules.IsReadiness(null));

        // The two absence readiness values are distinct on purpose: never
        // configured is not the same as deliberately disabled.
        Assert.Contains("NotConfigured", SceneAnalyticsContractRules.ReadinessValues);
        Assert.Contains("Disabled", SceneAnalyticsContractRules.ReadinessValues);

        Assert.True(SceneAnalyticsContractRules.IsReanalysisScope(
            SceneAnalyticsContractRules.DefaultReanalysisScope));
        Assert.False(SceneAnalyticsContractRules.IsReanalysisScope("everything"));
    }

    [Fact]
    public void ZoneKindVocabularyIsClosed()
    {
        Assert.All(SceneContractRules.ZoneKindValues, value => Assert.True(SceneContractRules.IsZoneKind(value)));
        Assert.True(SceneContractRules.IsZoneKind(SceneContractRules.DefaultZoneKind));
        Assert.False(SceneContractRules.IsZoneKind("restricted"));
        Assert.False(SceneContractRules.IsZoneKind(null));
    }

    // --- Coverage completeness (ADR-011 decision 5).

    [Fact]
    public void CoverageIsCompleteOnlyWhenEveryRunInScopeWasEvaluated()
    {
        var complete = new AnalyticsCoverageResponse(RevisionId, "scene-analytics-v1", 12, 0, 0, 0, 0, 0, 40, 0);

        Assert.True(complete.Complete);
    }

    [Theory]
    [InlineData(1, 0, 0, 0, 0)]
    [InlineData(0, 1, 0, 0, 0)]
    [InlineData(0, 0, 1, 0, 0)]
    [InlineData(0, 0, 0, 1, 0)]
    [InlineData(0, 0, 0, 0, 1)]
    public void AnyUnevaluatedRunMakesCoverageIncomplete(
        int pending,
        int failed,
        int notConfigured,
        int disabled,
        int stale)
    {
        var coverage = new AnalyticsCoverageResponse(
            RevisionId,
            "scene-analytics-v1",
            EvaluatedRuns: 12,
            PendingRuns: pending,
            FailedRuns: failed,
            NotConfiguredRuns: notConfigured,
            DisabledRuns: disabled,
            StaleRuns: stale,
            AnalysedTracks: 12,
            UnavailableTracks: 0);

        Assert.False(coverage.Complete);
    }

    [Fact]
    public void DisabledAndUnconfiguredCamerasAreCountedApartAndNeverComplete()
    {
        // A never-configured camera and a deliberately disabled one are different
        // facts an operator is owed, so they occupy different buckets. Neither was
        // evaluated, so neither may read as "zero matches".
        var coverage = new AnalyticsCoverageResponse(
            SceneRevisionId: null,
            "scene-analytics-v1",
            EvaluatedRuns: 0,
            PendingRuns: 0,
            FailedRuns: 0,
            NotConfiguredRuns: 4,
            DisabledRuns: 2,
            StaleRuns: 0,
            AnalysedTracks: 0,
            UnavailableTracks: 0);

        Assert.False(coverage.Complete);

        var json = JsonSerializer.Serialize(coverage, ApiJson);
        using var document = JsonDocument.Parse(json);
        Assert.Equal(JsonValueKind.Null, document.RootElement.GetProperty("sceneRevisionId").ValueKind);
        Assert.Equal(4, document.RootElement.GetProperty("notConfiguredRuns").GetInt32());
        Assert.Equal(2, document.RootElement.GetProperty("disabledRuns").GetInt32());
        Assert.False(document.RootElement.GetProperty("complete").GetBoolean());
    }

    [Fact]
    public void CoverageSerializesCompletenessRatherThanTrustingACaller()
    {
        var coverage = new AnalyticsCoverageResponse(RevisionId, "scene-analytics-v1", 9, 2, 0, 0, 0, 1, 31, 2);

        var json = JsonSerializer.Serialize(coverage, ApiJson);
        using var document = JsonDocument.Parse(json);

        Assert.False(document.RootElement.GetProperty("complete").GetBoolean());
        Assert.Equal("scene-analytics-v1", document.RootElement.GetProperty("algorithmVersion").GetString());

        // "complete" has no setter, so a hostile payload asserting it is ignored
        // and the value is recomputed from the buckets on the way back in.
        var tampered = json.Replace("\"complete\":false", "\"complete\":true", StringComparison.Ordinal);
        var parsed = JsonSerializer.Deserialize<AnalyticsCoverageResponse>(tampered, ApiJson);
        Assert.NotNull(parsed);
        Assert.False(parsed.Complete);
    }

    // --- Ownership secrets never reach a contract.

    [Fact]
    public void SceneAndAnalyticsContractsNeverExposeAttemptOwnershipSecrets()
    {
        string[] forbidden = ["claimtoken", "token", "tokenhash", "secret"];

        var contractTypes = typeof(AnalyticsCoverageResponse).Assembly
            .GetTypes()
            .Where(type => type.IsPublic && type.Namespace is
                "Mavi.Contracts.Api.Analytics" or "Mavi.Contracts.Api.Scene")
            .ToArray();

        Assert.NotEmpty(contractTypes);

        foreach (var type in contractTypes)
        {
            foreach (var member in type.GetProperties(BindingFlags.Public | BindingFlags.Instance)
                         .Select(property => property.Name)
                         .Concat(type.GetFields(BindingFlags.Public | BindingFlags.Static)
                             .Select(field => field.Name)))
            {
                var normalized = member.ToLowerInvariant();
                Assert.DoesNotContain(forbidden, candidate => normalized.Contains(candidate, StringComparison.Ordinal));
            }
        }
    }

    [Fact]
    public void TheStaleAttemptCodeIsStable()
    {
        Assert.Equal("analytics_attempt_stale", SceneAnalyticsContractRules.StaleAttemptCode);
        Assert.Equal("track_analytics_incomplete", SceneAnalyticsContractRules.IncompleteCoverageCode);
    }
}
