using Mavi.Application.Modules.Intelligence;
using Mavi.Application.Modules.Plates;
using Mavi.Application.Modules.Plates.Release;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// The plate path of the search service (plan §5.4): validation, the implied Vehicle class, what is pinned
/// into the v4 cursor, and that a continuation never re-resolves the release.
/// </summary>
public sealed class TrackSearchServicePlateTests
{
    private static readonly DateTimeOffset FixedNow = new(2026, 10, 13, 12, 0, 0, TimeSpan.Zero);
    private static readonly TimeProvider FixedClock = new FixedTimeProvider(FixedNow);
    private static readonly TrackCursorSigningKey Key =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray());
    private static readonly Guid Camera = Guid.Parse("0199a1f0-0000-7000-8000-00000000c001");
    private static readonly Guid Revision = Guid.Parse("0199a1f0-0000-7000-8000-00000000b001");
    private static readonly Guid Zone = Guid.Parse("0199a1f0-0000-7000-8000-00000000d001");

    private static readonly PlateReleaseDefinition DefinitionA = Definition("mavi-model-v2-" + new string('3', 64));
    private static readonly PlateReleaseDefinition DefinitionB = Definition("mavi-model-v2-" + new string('5', 64));

    private static TrackSearchQuery Query(int limit = 50, ObjectClass? objectClass = null, string text = "KA01") =>
        new(null, null, null, objectClass, null, null, null, null, null, limit, Plate: new TrackPlateQuery(text, TrackPlateMatch.Contains));

    private static TrackSearchService Service(FakePlateRepository plates, PlateReleaseDefinition? definition) =>
        new(new UnusedRepository(), FixedClock, Key, plates, new FixedRelease(definition));

    [Fact]
    public async Task APlateQueryImpliesVehicleAndPinsThePreferredIdentityIntoAV4Cursor()
    {
        var plates = new FakePlateRepository(Rows(3));
        var service = Service(plates, DefinitionA);

        var result = await service.SearchAsync(Query(limit: 2), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Equal(ObjectClass.Vehicle, plates.LastQuery!.ObjectClass);
        Assert.Equal(DefinitionA.Identity.Fingerprint, plates.LastPreferred);
        Assert.Equal(3, plates.LastTake);
        Assert.Equal(2, result.Page!.Items.Count);
        Assert.NotNull(result.Page.PlateCoverage);
        Assert.NotNull(result.Page.ItemPlates);
        Assert.Null(result.Page.Coverage);

        Assert.False(TrackCursorCodec.TryDecode(result.Page.NextCursor, out _));
        Assert.False(TrackCursorCodec.TryDecodeAnalytic(result.Page.NextCursor, Key, out _));
        Assert.True(TrackCursorCodec.TryDecodePlate(result.Page.NextCursor, Key, out var cursor));
        Assert.Equal(DefinitionA.Identity.Fingerprint, cursor!.PlateIdentityFingerprint);
        Assert.Equal(plates.Rows[1].Id, cursor.Position.TrackId);
        Assert.Equal(
            TrackCursorCodec.ComputePlateFilterFingerprint(Query(limit: 2).Canonical, DefinitionA.Identity.Fingerprint, null, Key),
            cursor.Position.FilterFingerprint);
    }

    [Fact]
    public async Task AContinuationKeepsThePinnedIdentityAfterTheReleaseChanged()
    {
        var plates = new FakePlateRepository(Rows(3));
        var first = await Service(plates, DefinitionA).SearchAsync(Query(limit: 2), CancellationToken.None);

        // The platform restarted with another plate binding: the open result set keeps its meaning.
        var next = await Service(plates, DefinitionB).SearchAsync(
            Query(limit: 2) with { Cursor = first.Page!.NextCursor }, CancellationToken.None);

        Assert.True(next.IsSuccess);
        Assert.NotNull(plates.LastCursor);
        Assert.Equal(DefinitionA.Identity.Fingerprint, plates.LastPreferred);
        Assert.Equal(DefinitionA.Identity.Fingerprint, plates.LastCursor!.PlateIdentityFingerprint);
    }

    [Fact]
    public async Task ACursorReplayedWithAnotherTextMatchOrKindIsRefused()
    {
        var plates = new FakePlateRepository(Rows(3));
        var service = Service(plates, DefinitionA);
        var cursor = (await service.SearchAsync(Query(limit: 2), CancellationToken.None)).Page!.NextCursor;

        var otherText = await service.SearchAsync(Query(limit: 2, text: "KA02") with { Cursor = cursor }, CancellationToken.None);
        var otherMatch = await service.SearchAsync(
            Query(limit: 2) with { Cursor = cursor, Plate = new TrackPlateQuery("KA01", TrackPlateMatch.Exact) }, CancellationToken.None);
        var nowAnalytic = await service.SearchAsync(
            Query(limit: 2) with { Cursor = cursor, CameraId = Camera, Analytics = TrackAnalyticsQuery.Empty with { ZoneId = Zone } },
            CancellationToken.None);
        var noPlate = await service.SearchAsync(Query(limit: 2) with { Cursor = cursor, Plate = null }, CancellationToken.None);

        Assert.All([otherText, otherMatch, nowAnalytic], result => Assert.Equal("track_search_invalid", result.ErrorCode));
        // Without the plate predicate the v4 cursor reaches the v2 decoder, which refuses it.
        Assert.Equal("track_search_invalid", noPlate.ErrorCode);
    }

    [Fact]
    public async Task AnExpiredCursorIsRefused()
    {
        var position = new TrackPlateCursorPosition(
            new TrackCursorPosition(FixedNow.AddHours(-2), 42, FixedNow.AddHours(-3), Guid.CreateVersion7(),
                TrackCursorCodec.ComputePlateFilterFingerprint(Query().Canonical, DefinitionA.Identity.Fingerprint, null, Key)),
            DefinitionA.Identity.Fingerprint,
            new TrackPlateCoverage(DefinitionA.Identity.Fingerprint, 1, 1, 0, 0, 0, 0));
        var result = await Service(new FakePlateRepository(Rows(1)), DefinitionA)
            .SearchAsync(Query() with { Cursor = TrackCursorCodec.EncodePlate(position, Key) }, CancellationToken.None);

        Assert.Equal("track_search_invalid", result.ErrorCode);
    }

    [Theory]
    [InlineData(ObjectClass.Person)]
    public async Task APersonClassWithAPlateTextIsRefused(ObjectClass objectClass)
    {
        var plates = new FakePlateRepository(Rows(1));
        var result = await Service(plates, DefinitionA).SearchAsync(Query(objectClass: objectClass), CancellationToken.None);

        Assert.Equal("track_search_invalid", result.ErrorCode);
        Assert.Null(plates.LastQuery);
    }

    [Theory]
    [InlineData("KA")]
    [InlineData("ka01")]
    [InlineData("KA 01")]
    [InlineData("ABCDEFGHIJ123456")]
    public async Task AnUnnormalisedOrOutOfBoundsTextIsRefusedAtTheService(string text)
    {
        var plates = new FakePlateRepository(Rows(1));
        var result = await Service(plates, DefinitionA).SearchAsync(Query(text: text), CancellationToken.None);

        Assert.Equal("track_search_invalid", result.ErrorCode);
        Assert.Null(plates.LastQuery);
    }

    [Fact]
    public async Task WithoutAConfiguredReleaseTheRepositoryIsAskedWithNoIdentity()
    {
        var plates = new FakePlateRepository([]);
        var result = await Service(plates, definition: null).SearchAsync(Query(), CancellationToken.None);

        Assert.True(result.IsSuccess);
        Assert.Null(plates.LastPreferred);
        Assert.Null(result.Page!.NextCursor);
        Assert.Null(result.Page.PlateCoverage!.IdentityFingerprint);
    }

    [Fact]
    public async Task AHostWithoutThePlatePlaneRefusesToGuess()
    {
        var service = new TrackSearchService(new UnusedRepository(), FixedClock, Key);
        await Assert.ThrowsAsync<InvalidOperationException>(() => service.SearchAsync(Query(), CancellationToken.None));
    }

    [Fact]
    public async Task ACombinedSearchDemandingCompleteAnalyticsCoverageIsRefusedWithItsCoverage()
    {
        var incomplete = new TrackAnalyticsCoverage(Revision, "scene-analytics-v1", 1, 1, 0, 0, 0, 0, 3, 0);
        var plates = new FakePlateRepository(Rows(1))
        {
            AnalyticsIdentity = new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1"),
            AnalyticsCoverage = incomplete,
        };
        var query = Query() with
        {
            CameraId = Camera,
            Analytics = TrackAnalyticsQuery.Empty with { ZoneId = Zone, RequireCompleteCoverage = true },
        };

        var result = await Service(plates, DefinitionA).SearchAsync(query, CancellationToken.None);

        Assert.False(result.IsSuccess);
        Assert.Equal(incomplete, result.Coverage);
    }

    [Fact]
    public async Task ACombinedCursorPinsBothIdentities()
    {
        var identity = new TrackAnalyticsPinnedIdentity(Camera, Revision, "scene-analytics-v1");
        var coverage = new TrackAnalyticsCoverage(Revision, "scene-analytics-v1", 2, 0, 0, 0, 0, 0, 3, 0);
        var plates = new FakePlateRepository(Rows(3)) { AnalyticsIdentity = identity, AnalyticsCoverage = coverage };
        var query = Query(limit: 2) with { CameraId = Camera, Analytics = TrackAnalyticsQuery.Empty with { ZoneId = Zone } };

        var result = await Service(plates, DefinitionA).SearchAsync(query, CancellationToken.None);

        Assert.True(TrackCursorCodec.TryDecodePlate(result.Page!.NextCursor, Key, out var cursor));
        Assert.Equal(identity, cursor!.AnalyticsIdentity);
        Assert.Equal(coverage, cursor.AnalyticsCoverage);
        Assert.Equal(coverage, result.Page.Coverage);
    }

    // --- Fixtures -------------------------------------------------------------------------------

    private static PlateReleaseDefinition Definition(string ocrPack)
    {
        var sha = new string('a', 64);
        var identity = PlateIdentity.Create("plates-fixture", "1.0.0", "plate-track-text-rank0", "1.0.0", sha,
            [new PlateCapabilityIdentity("ocr", ocrPack), new PlateCapabilityIdentity("plate-detector", "mavi-model-v2-" + new string('4', 64))],
            sha);
        return new PlateReleaseDefinition(
            identity,
            new PlateParameters(2, 1, 3, 0.5, 0.5, new HashSet<string>(), null),
            new PlateSummaryPolicy("plate-track-text-rank0", "1.0.0", sha, PlateReleaseParser.SummaryMethod),
            DevelopmentOnly: true,
            "plates",
            sha,
            sha,
            "{}",
            "{}");
    }

    private static TrackSearchRow[] Rows(int count) => Enumerable.Range(1, count)
        .Select(index => new TrackSearchRow(
            Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(), Camera, "CAM-01", "Gate", ObjectClass.Vehicle,
            FixedNow.AddMinutes(-index), FixedNow.AddMinutes(-index).AddSeconds(1), 0, 1000, 1000, 5, 0.8, 0.9,
            ReviewStatus.Unreviewed, null))
        .ToArray();

    private sealed class FixedTimeProvider(DateTimeOffset now) : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => now;
    }

    private sealed class FixedRelease(PlateReleaseDefinition? definition) : IPlateRelease
    {
        public PlateReleaseResolution Resolution { get; } = definition is null
            ? PlateReleaseResolution.NotConfigured("plate_role_not_bound")
            : PlateReleaseResolution.Configured(definition);
    }

    private sealed class FakePlateRepository(TrackSearchRow[] rows) : ITrackPlateSearchRepository
    {
        public TrackSearchRow[] Rows { get; } = rows;
        public TrackSearchQuery? LastQuery { get; private set; }
        public string? LastPreferred { get; private set; }
        public TrackPlateCursorPosition? LastCursor { get; private set; }
        public int LastTake { get; private set; }
        public TrackAnalyticsPinnedIdentity? AnalyticsIdentity { get; init; }
        public TrackAnalyticsCoverage? AnalyticsCoverage { get; init; }

        public Task<TrackPlateSearchRepositoryResult> SearchPlatesAsync(
            TrackSearchQuery query, string? preferredFingerprint, TrackPlateCursorPosition? cursor, int take, CancellationToken cancellationToken)
        {
            LastQuery = query;
            LastPreferred = preferredFingerprint;
            LastCursor = cursor;
            LastTake = take;
            var coverage = cursor?.PlateCoverage ?? new TrackPlateCoverage(preferredFingerprint, Rows.Length, preferredFingerprint is null ? 0 : Rows.Length, 0, 0, 0,
                preferredFingerprint is null ? Rows.Length : 0);
            var explained = Rows.ToDictionary(
                row => row.Id,
                row => new TrackItemPlate("KA01AB1234", TrackPlateMatch.Contains, 1, 1, 1, 0.9, Guid.CreateVersion7()));
            return Task.FromResult(new TrackPlateSearchRepositoryResult(new TrackPlateSearchRepositoryPage(
                Rows, cursor?.Position.SnapshotUtc ?? FixedNow, cursor?.Position.SnapshotVisibilitySequence ?? 101, coverage, explained,
                cursor?.AnalyticsIdentity ?? AnalyticsIdentity, cursor?.AnalyticsCoverage ?? AnalyticsCoverage,
                AnalyticsIdentity is null ? null : new Dictionary<Guid, TrackItemAnalytics>())));
        }

        public Task<TrackPlateFacts?> GetTrackPlateFactsAsync(Guid trackId, Guid analysisId, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");
    }

    private sealed class UnusedRepository : ITrackSearchRepository
    {
        public Task<TrackSearchRepositoryPage> SearchAsync(TrackSearchQuery query, TrackCursorPosition? cursor, int take, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("A plate query must not take the ordinary path.");

        public Task<TrackAnalyticsSearchRepositoryResult> SearchAnalyticsAsync(
            TrackSearchQuery query, TrackAnalyticsCursorPosition? cursor, int take, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("A plate query must not take the analytic path.");

        public Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");

        public Task<IReadOnlyList<TrackEvidenceObservationRow>> GetEvidenceSetAsync(Guid trackId, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");

        public Task<TrackDetailAnalyticsResult?> GetDetailAnalyticsAsync(
            Guid trackId, TrackAnalyticsDetailRequest request, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not part of these scenarios.");
    }
}
