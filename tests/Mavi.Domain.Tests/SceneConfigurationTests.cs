using Mavi.Domain.Common;
using Mavi.Domain.Scene;

namespace Mavi.Domain.Tests;

public sealed class SceneConfigurationTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 20, 6, 0, 0, TimeSpan.Zero);

    // Revision numbering and activation
    [Fact]
    public void FirstSaveCreatesAndActivatesRevisionOne()
    {
        var configuration = NewConfiguration();

        var revision = Save(configuration, null, Draft(Zone("Gate")));

        Assert.Equal(1, revision.RevisionNumber);
        Assert.Equal(configuration.Id, revision.SceneConfigurationId);
        Assert.Equal(revision.Id, configuration.ActiveRevisionId);
        Assert.Equal(SceneRules.UnattributedDevelopmentActor, revision.CreatedBy);
    }

    [Fact]
    public void SubsequentSaveIncrementsTheRevisionNumber()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate")));

        var second = Save(configuration, first, Draft(Zone("Gate")), expected: 1);

        Assert.Equal(2, second.RevisionNumber);
        Assert.Equal(second.Id, configuration.ActiveRevisionId);
        Assert.NotEqual(first.Id, second.Id);
    }

    [Fact]
    public void SavingDoesNotAlterThePreviousRevision()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate")));
        var originalZoneId = first.Zones[0].ZoneId;
        var originalVertexCount = first.Zones[0].Vertices.Count;

        Save(configuration, first, Draft(Zone("Gate", enabled: false)), expected: 1);

        Assert.Equal(1, first.RevisionNumber);
        Assert.Equal(originalZoneId, first.Zones[0].ZoneId);
        Assert.Equal(originalVertexCount, first.Zones[0].Vertices.Count);
        Assert.True(first.Zones[0].Enabled);
    }

    // Optimistic concurrency
    [Fact]
    public void SaveBasedOnAnOlderRevisionIsAConflict()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate")));
        var second = Save(configuration, first, Draft(Zone("Gate")), expected: 1);

        var exception = Assert.Throws<SceneRevisionConflictException>(
            () => Save(configuration, second, Draft(Zone("Gate")), expected: 1));

        Assert.Equal(1, exception.ExpectedRevisionNumber);
        Assert.Equal(2, exception.ActualRevisionNumber);
        Assert.Equal(SceneErrorCodes.RevisionConflict, SceneRevisionConflictException.Code);
    }

    [Fact]
    public void FirstSaveAgainstAnExistingConfigurationIsAConflict()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate")));

        Assert.Throws<SceneRevisionConflictException>(
            () => Save(configuration, first, Draft(Zone("Gate")), expected: null));
    }

    [Fact]
    public void ActiveRevisionFromAnotherConfigurationIsRefused()
    {
        var first = NewConfiguration();
        var other = NewConfiguration();
        var foreign = Save(other, null, Draft(Zone("Gate")));

        var exception = Assert.Throws<DomainValidationException>(
            () => Save(first, foreign, Draft(Zone("Gate")), expected: 1));

        Assert.Equal(SceneErrorCodes.ConfigurationMismatch, exception.Code);
    }

    // Stable identities
    [Fact]
    public void KeepingAnIdentityCarriesTheZoneForward()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate")));
        var zoneId = first.Zones[0].ZoneId;

        var second = Save(
            configuration,
            first,
            Draft(Zone("Gate", zoneId: zoneId)),
            expected: 1);

        Assert.Equal(zoneId, second.Zones[0].ZoneId);
    }

    [Fact]
    public void OmittingAnIdentityRemovesTheZoneFromTheNewRevision()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate"), Zone("Yard", offset: 0.5)));

        var second = Save(
            configuration,
            first,
            Draft(Zone("Gate", zoneId: first.Zones[0].ZoneId)),
            expected: 1);

        Assert.Single(second.Zones);
        Assert.Equal(2, first.Zones.Count);
    }

    [Fact]
    public void NewZoneReceivesAServerIssuedVersionSevenIdentity()
    {
        var revision = Save(NewConfiguration(), null, Draft(Zone("Gate")));

        Assert.NotEqual(Guid.Empty, revision.Zones[0].ZoneId);
        Assert.Equal(7, revision.Zones[0].ZoneId.Version);
    }

    [Fact]
    public void UnknownIdentityIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(
            () => Save(NewConfiguration(), null, Draft(Zone("Gate", zoneId: Guid.CreateVersion7()))));

        Assert.Equal(SceneErrorCodes.IdentityUnknown, exception.Code);
    }

    [Fact]
    public void ZoneIdentityMayNotBeReusedAsALineIdentity()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate")));
        var zoneId = first.Zones[0].ZoneId;

        var exception = Assert.Throws<DomainValidationException>(() => Save(
            configuration,
            first,
            new SceneRevisionDraft(null, null, null, [], [Line("Kerb", lineId: zoneId)]),
            expected: 1));

        Assert.Equal(SceneErrorCodes.IdentityUnknown, exception.Code);
    }

    [Fact]
    public void RepeatingOneIdentityTwiceInARevisionIsRefused()
    {
        var configuration = NewConfiguration();
        var first = Save(configuration, null, Draft(Zone("Gate")));
        var zoneId = first.Zones[0].ZoneId;

        var exception = Assert.Throws<DomainValidationException>(() => Save(
            configuration,
            first,
            Draft(Zone("Gate", zoneId: zoneId), Zone("Yard", zoneId: zoneId, offset: 0.5)),
            expected: 1));

        Assert.Equal(SceneErrorCodes.IdentityDuplicate, exception.Code);
    }

    // Disable semantics
    [Fact]
    public void RevisionWithNoGeometryDisablesAnalytics()
    {
        var revision = Save(NewConfiguration(), null, new SceneRevisionDraft(null, null, null, [], []));

        Assert.False(revision.AnalyticsEnabled);
        Assert.Empty(revision.Zones);
    }

    [Fact]
    public void RevisionWhoseGeometryIsAllDisabledAlsoDisablesAnalytics()
    {
        var revision = Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, null, null, [Zone("Gate", enabled: false)], [Line("Kerb", enabled: false)]));

        Assert.False(revision.AnalyticsEnabled);
        Assert.Single(revision.Zones);
        Assert.Single(revision.TripLines);
    }

    [Fact]
    public void OneEnabledTripLineIsEnoughToEnableAnalytics()
    {
        var revision = Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, null, null, [Zone("Gate", enabled: false)], [Line("Kerb")]));

        Assert.True(revision.AnalyticsEnabled);
    }

    // Reference frame
    [Fact]
    public void ReferenceFrameMustBeWholeOrAbsent()
    {
        var videoId = Guid.CreateVersion7();
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, videoId, null, [Zone("Gate")], [])));

        Assert.Equal(SceneErrorCodes.ReferenceFrameIncomplete, exception.Code);
    }

    [Fact]
    public void NegativeReferenceFrameOffsetIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, Guid.CreateVersion7(), -1, [Zone("Gate")], [])));

        Assert.Equal(SceneErrorCodes.ReferenceFrameOffsetInvalid, exception.Code);
    }

    [Fact]
    public void CompleteReferenceFrameIsKept()
    {
        var videoId = Guid.CreateVersion7();
        var revision = Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, videoId, 4_500, [Zone("Gate")], []));

        Assert.Equal(videoId, revision.ReferenceFrameVideoAssetId);
        Assert.Equal(4_500, revision.ReferenceFrameOffsetMs);
    }

    // Geometry validation
    [Theory]
    [InlineData(2, SceneErrorCodes.ZoneVertexCount)]
    [InlineData(65, SceneErrorCodes.ZoneVertexCount)]
    public void ZoneVertexCountIsBounded(int vertexCount, string code)
    {
        var vertices = Enumerable.Range(0, vertexCount)
            .Select(index => new ScenePointDraft(
                0.5 + (0.3 * Math.Cos(2 * Math.PI * index / vertexCount)),
                0.5 + (0.3 * Math.Sin(2 * Math.PI * index / vertexCount))))
            .ToArray();

        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(new SceneZoneDraft(null, "Gate", null, true, vertices, null))));

        Assert.Equal(code, exception.Code);
    }

    [Fact]
    public void ZoneVertexOutsideTheFrameIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(new SceneZoneDraft(
                null,
                "Gate",
                null,
                true,
                [new ScenePointDraft(0.1, 0.1), new ScenePointDraft(1.5, 0.1), new ScenePointDraft(0.1, 0.4)],
                null))));

        Assert.Equal(SceneErrorCodes.ZoneVertexRange, exception.Code);
    }

    [Fact]
    public void SelfIntersectingZoneIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(new SceneZoneDraft(
                null,
                "Bow tie",
                null,
                true,
                [
                    new ScenePointDraft(0.1, 0.1),
                    new ScenePointDraft(0.9, 0.9),
                    new ScenePointDraft(0.9, 0.1),
                    new ScenePointDraft(0.1, 0.9),
                ],
                null))));

        Assert.Equal(SceneErrorCodes.ZoneSelfIntersecting, exception.Code);
    }

    [Fact]
    public void CollinearZoneIsDegenerate()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(new SceneZoneDraft(
                null,
                "Flat",
                null,
                true,
                [
                    new ScenePointDraft(0.1, 0.5),
                    new ScenePointDraft(0.4, 0.5),
                    new ScenePointDraft(0.9, 0.5),
                ],
                null))));

        Assert.Equal(SceneErrorCodes.ZoneDegenerate, exception.Code);
    }

    [Fact]
    public void RepeatedVertexIsDegenerate()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(new SceneZoneDraft(
                null,
                "Pinched",
                null,
                true,
                [
                    new ScenePointDraft(0.1, 0.1),
                    new ScenePointDraft(0.9, 0.1),
                    new ScenePointDraft(0.9, 0.1),
                    new ScenePointDraft(0.5, 0.9),
                ],
                null))));

        Assert.Equal(SceneErrorCodes.ZoneDegenerate, exception.Code);
    }

    [Fact]
    public void DuplicateZoneNamesAreRefusedIgnoringCase()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(Zone("Gate"), Zone("gate", offset: 0.5))));

        Assert.Equal(SceneErrorCodes.ZoneNameDuplicate, exception.Code);
    }

    [Fact]
    public void OperatorCapitalisationIsPreserved()
    {
        var revision = Save(NewConfiguration(), null, Draft(Zone("  Main GATE  ")));

        Assert.Equal("Main GATE", revision.Zones[0].Name);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void ZoneWithoutANameIsRefused(string? name)
    {
        var exception = Assert.Throws<DomainValidationException>(
            () => Save(NewConfiguration(), null, Draft(Zone(name!))));

        Assert.Equal(SceneErrorCodes.ZoneNameRequired, exception.Code);
    }

    [Fact]
    public void OverLongZoneNameIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(Zone(new string('z', SceneRules.MaximumNameLength + 1)))));

        Assert.Equal(SceneErrorCodes.ZoneNameTooLong, exception.Code);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    public void TripLineWithoutANameIsRefused(string? name)
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, null, null, [], [Line(name!)])));

        Assert.Equal(SceneErrorCodes.LineNameRequired, exception.Code);
    }

    [Fact]
    public void OverLongTripLineNameIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(
                null, null, null, [], [Line(new string('k', SceneRules.MaximumNameLength + 1))])));

        Assert.Equal(SceneErrorCodes.LineNameTooLong, exception.Code);
    }

    [Fact]
    public void TooManyTripLinesAreRefused()
    {
        var lines = Enumerable.Range(0, SceneRules.MaximumTripLinesPerRevision + 1)
            .Select(index => Line($"Line {index}"))
            .ToArray();

        var exception = Assert.Throws<DomainValidationException>(
            () => Save(NewConfiguration(), null, new SceneRevisionDraft(null, null, null, [], lines)));

        Assert.Equal(SceneErrorCodes.GeometryCount, exception.Code);
    }

    [Fact]
    public void UnknownZoneKindIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(Zone("Gate", kind: "Perimeter"))));

        Assert.Equal(SceneErrorCodes.ZoneKindInvalid, exception.Code);
    }

    [Fact]
    public void ZoneKindDefaultsToGeneral() =>
        Assert.Equal(SceneZoneKind.General, Save(NewConfiguration(), null, Draft(Zone("Gate"))).Zones[0].Kind);

    [Theory]
    [InlineData(0)]
    [InlineData(-5)]
    [InlineData(86_401)]
    public void LoiteringThresholdIsBounded(int threshold)
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            Draft(Zone("Gate", loiteringThresholdSeconds: threshold))));

        Assert.Equal(SceneErrorCodes.ZoneLoiteringThresholdInvalid, exception.Code);
    }

    [Fact]
    public void TripLineEndpointsTooCloseAreRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, null, null, [], [
                new TripLineDraft(
                    null,
                    "Kerb",
                    true,
                    new ScenePointDraft(0.5, 0.5),
                    new ScenePointDraft(0.502, 0.5),
                    false,
                    null,
                    null),
            ])));

        Assert.Equal(SceneErrorCodes.LineEndpointsIdentical, exception.Code);
    }

    [Fact]
    public void TripLineMissingAnEndpointIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, null, null, [], [
                new TripLineDraft(null, "Kerb", true, new ScenePointDraft(0.1, 0.1), null, false, null, null),
            ])));

        Assert.Equal(SceneErrorCodes.LineRange, exception.Code);
    }

    [Fact]
    public void DuplicateTripLineNamesAreRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, null, null, [], [Line("Kerb"), Line("KERB", offset: 0.2)])));

        Assert.Equal(SceneErrorCodes.LineNameDuplicate, exception.Code);
    }

    [Fact]
    public void TripLineLabelsDefaultWhenNotSupplied()
    {
        var revision = Save(NewConfiguration(), null, new SceneRevisionDraft(null, null, null, [], [Line("Kerb")]));

        Assert.Equal("A to B", revision.TripLines[0].AToBLabel);
        Assert.Equal("B to A", revision.TripLines[0].BToALabel);
    }

    [Fact]
    public void OverLongLabelIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(null, null, null, [], [
                new TripLineDraft(
                    null,
                    "Kerb",
                    true,
                    new ScenePointDraft(0.1, 0.1),
                    new ScenePointDraft(0.9, 0.9),
                    true,
                    new string('x', SceneRules.MaximumDirectionLabelLength + 1),
                    null),
            ])));

        Assert.Equal(SceneErrorCodes.LineLabelTooLong, exception.Code);
    }

    [Fact]
    public void TooManyZonesAreRefused()
    {
        var zones = Enumerable.Range(0, SceneRules.MaximumZonesPerRevision + 1)
            .Select(index => Zone($"Zone {index}", offset: 0))
            .ToArray();

        var exception = Assert.Throws<DomainValidationException>(
            () => Save(NewConfiguration(), null, new SceneRevisionDraft(null, null, null, zones, [])));

        Assert.Equal(SceneErrorCodes.GeometryCount, exception.Code);
    }

    [Fact]
    public void OverLongNoteIsRefused()
    {
        var exception = Assert.Throws<DomainValidationException>(() => Save(
            NewConfiguration(),
            null,
            new SceneRevisionDraft(
                new string('n', SceneRules.MaximumNoteLength + 1),
                null,
                null,
                [Zone("Gate")],
                [])));

        Assert.Equal(SceneErrorCodes.NoteTooLong, exception.Code);
    }

    [Fact]
    public void ConfigurationRequiresACamera()
    {
        var exception = Assert.Throws<DomainValidationException>(
            () => SceneConfiguration.Create(Guid.Empty, Now));

        Assert.Equal(SceneErrorCodes.ConfigurationMismatch, exception.Code);
    }

    [Fact]
    public void ConfigurationRecordsItsCameraAndTimestamps()
    {
        var cameraId = Guid.CreateVersion7();
        var configuration = SceneConfiguration.Create(cameraId, Now);

        Assert.Equal(cameraId, configuration.CameraId);
        Assert.Equal(Now, configuration.CreatedAtUtc);
        Assert.Equal(Now, configuration.UpdatedAtUtc);
        Assert.Null(configuration.ActiveRevisionId);
    }

    // Helpers
    private static SceneConfiguration NewConfiguration() =>
        SceneConfiguration.Create(Guid.CreateVersion7(), Now);

    private static SceneConfigurationRevision Save(
        SceneConfiguration configuration,
        SceneConfigurationRevision? active,
        SceneRevisionDraft draft,
        int? expected = null) =>
        configuration.SaveRevision(active, draft, expected, SceneRules.UnattributedDevelopmentActor, Now);

    private static SceneRevisionDraft Draft(params SceneZoneDraft[] zones) => new(null, null, null, zones, []);

    private static SceneZoneDraft Zone(
        string name,
        Guid? zoneId = null,
        bool enabled = true,
        string? kind = null,
        double offset = 0,
        int? loiteringThresholdSeconds = null) =>
        new(
            zoneId,
            name,
            kind,
            enabled,
            [
                new ScenePointDraft(0.1 + offset, 0.1),
                new ScenePointDraft(0.4 + offset, 0.1),
                new ScenePointDraft(0.4 + offset, 0.4),
                new ScenePointDraft(0.1 + offset, 0.4),
            ],
            loiteringThresholdSeconds);

    private static TripLineDraft Line(string name, Guid? lineId = null, bool enabled = true, double offset = 0) =>
        new(
            lineId,
            name,
            enabled,
            new ScenePointDraft(0.1 + offset, 0.5),
            new ScenePointDraft(0.9, 0.5 + offset),
            false,
            null,
            null);
}
