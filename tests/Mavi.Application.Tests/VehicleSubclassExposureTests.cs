using System.Security.Cryptography;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests;

/// <summary>
/// Stage 3 X2: the one exposure policy, the subclass search predicate's validation and
/// canonical form, and its part in the cursor fingerprint.
/// </summary>
public sealed class VehicleSubclassExposureTests
{
    private const string A2Source =
        "detector-native:b4c6a6cf8c68382f3af266b884801dbb77fb908cbaca7ed41336d4834463e62e";

    private static readonly DateTimeOffset FixedNow = new(2026, 9, 13, 11, 0, 0, TimeSpan.Zero);

    private static readonly TrackCursorSigningKey SigningKey =
        TrackCursorSigningKey.FromBytes(Enumerable.Range(0, 32).Select(x => (byte)x).ToArray());

    // --- The policy -----------------------------------------------------------

    [Fact]
    public void ThePolicyIsTheX1AllowlistAndTheReleaseProfileSource()
    {
        Assert.Equal(["car"], VehicleSubclassExposurePolicy.ExposedSubclasses);
        Assert.Equal(
            "detector-native:afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf",
            VehicleSubclassExposurePolicy.ApprovedSource);
        Assert.True(VehicleSubclass.IsDetectorNativeSource(VehicleSubclassExposurePolicy.ApprovedSource));
        Assert.All(VehicleSubclassExposurePolicy.ExposedSubclasses, value => Assert.Contains(value, VehicleSubclass.ValuesV1));
    }

    [Theory]
    [InlineData(ObjectClass.Vehicle, "car", VehicleSubclassExposurePolicy.ApprovedSource, "car")]
    [InlineData(ObjectClass.Vehicle, "truck", VehicleSubclassExposurePolicy.ApprovedSource, null)]
    [InlineData(ObjectClass.Vehicle, "bus", VehicleSubclassExposurePolicy.ApprovedSource, null)]
    [InlineData(ObjectClass.Vehicle, "motorcycle", VehicleSubclassExposurePolicy.ApprovedSource, null)]
    [InlineData(ObjectClass.Vehicle, "car", A2Source, null)]
    [InlineData(ObjectClass.Vehicle, "car", null, null)]
    [InlineData(ObjectClass.Vehicle, null, VehicleSubclassExposurePolicy.ApprovedSource, null)]
    [InlineData(ObjectClass.Vehicle, null, null, null)]
    [InlineData(ObjectClass.Vehicle, "Car", VehicleSubclassExposurePolicy.ApprovedSource, null)]
    [InlineData(ObjectClass.Vehicle, "car", "DETECTOR-NATIVE:AFB03B6C4DA61FBF6021EF855307F80C5B7206996E7E21C8D297394B091A18BF", null)]
    [InlineData(ObjectClass.Person, "car", VehicleSubclassExposurePolicy.ApprovedSource, null)]
    public void OnlyAReleaseProfileCarIsExposed(ObjectClass objectClass, string? subclass, string? source, string? expected)
    {
        Assert.Equal(expected, VehicleSubclassExposurePolicy.Expose(objectClass, subclass, source));
    }

    [Theory]
    [InlineData("car", true)]
    [InlineData("truck", false)]
    [InlineData("bus", false)]
    [InlineData("motorcycle", false)]
    [InlineData("Car", false)]
    [InlineData(" car", false)]
    [InlineData("", false)]
    [InlineData(null, false)]
    public void OnlyCarIsSearchable(string? value, bool expected) =>
        Assert.Equal(expected, VehicleSubclassExposurePolicy.IsExposable(value));

    [Fact]
    public void RowsExposeOnlyThroughThePolicy()
    {
        var hidden = Row() with { PersistedObjectSubclass = "truck", PersistedObjectSubclassSource = VehicleSubclassExposurePolicy.ApprovedSource };
        var a2 = Row() with { PersistedObjectSubclass = "car", PersistedObjectSubclassSource = A2Source };
        var exposed = Row() with { PersistedObjectSubclass = "car", PersistedObjectSubclassSource = VehicleSubclassExposurePolicy.ApprovedSource };

        Assert.Null(hidden.ExposedObjectSubclass);
        Assert.Null(a2.ExposedObjectSubclass);
        Assert.Null(Row().ExposedObjectSubclass);
        Assert.Equal("car", exposed.ExposedObjectSubclass);
    }

    // --- Validation and canonical form ---------------------------------------

    [Theory]
    [InlineData("truck", null)]
    [InlineData("bus", ObjectClass.Vehicle)]
    [InlineData("motorcycle", null)]
    [InlineData("Car", null)]
    [InlineData("car", ObjectClass.Person)]
    public async Task AHiddenValueOrAPersonClassIsInvalidBeforeTheRepository(string subclass, ObjectClass? objectClass)
    {
        var repository = new RecordingRepository();
        var service = new TrackSearchService(repository, new FixedClock(), SigningKey);

        var result = await service.SearchAsync(Query() with { ObjectClass = objectClass, ObjectSubclass = subclass }, default);

        Assert.False(result.IsSuccess);
        Assert.Equal("track_search_invalid", result.ErrorCode);
        Assert.Null(repository.LastQuery);
    }

    [Fact]
    public async Task ACarSearchReachesTheRepositoryAsAVehicleSearch()
    {
        var repository = new RecordingRepository();
        var service = new TrackSearchService(repository, new FixedClock(), SigningKey);

        var result = await service.SearchAsync(Query() with { ObjectSubclass = "car" }, default);

        Assert.True(result.IsSuccess);
        Assert.Equal(ObjectClass.Vehicle, repository.LastQuery!.ObjectClass);
        Assert.Equal("car", repository.LastQuery.ObjectSubclass);
    }

    [Fact]
    public async Task AnAbsentSubclassLeavesTheQueryAsItWas()
    {
        var repository = new RecordingRepository();
        var service = new TrackSearchService(repository, new FixedClock(), SigningKey);
        var query = Query() with { ObjectClass = null };

        await service.SearchAsync(query, default);

        Assert.Equal(query, repository.LastQuery);
        Assert.Same(query, query.Canonical);
    }

    // --- Fingerprint ----------------------------------------------------------

    [Fact]
    public void ASearchWithoutASubclassFingerprintsByteForByteAsBeforeX2()
    {
        // The pre-X2 filter payload, member for member, in declaration order.
        var query = Query() with { ObjectClass = ObjectClass.Vehicle, MinimumConfidence = 0.5 };
        var preX2 = JsonSerializer.SerializeToUtf8Bytes(new
        {
            query.CameraId,
            query.VideoAssetId,
            query.ProcessingRunId,
            query.ObjectClass,
            FromUtc = query.FromUtc,
            ToUtc = query.ToUtc,
            query.MinimumDurationMs,
            query.MinimumConfidence,
        });

        Assert.Equal(
            Convert.ToHexString(SHA256.HashData(preX2)).ToLowerInvariant(),
            TrackCursorCodec.ComputeFilterFingerprint(query));
    }

    [Fact]
    public void TheSubclassIsPartOfTheFingerprintAndItsCanonicalFormsAgree()
    {
        var vehicle = Query() with { ObjectClass = ObjectClass.Vehicle };
        var carImplied = (Query() with { ObjectSubclass = "car" }).Canonical;
        var carExplicit = (Query() with { ObjectClass = ObjectClass.Vehicle, ObjectSubclass = "car" }).Canonical;

        var vehicleFingerprint = TrackCursorCodec.ComputeFilterFingerprint(vehicle);
        var impliedFingerprint = TrackCursorCodec.ComputeFilterFingerprint(carImplied);

        Assert.NotEqual(vehicleFingerprint, impliedFingerprint);
        Assert.Equal(impliedFingerprint, TrackCursorCodec.ComputeFilterFingerprint(carExplicit));
    }

    [Fact]
    public async Task ACursorIsRefusedWhenTheSubclassPredicateChanges()
    {
        var repository = new RecordingRepository();
        var service = new TrackSearchService(repository, new FixedClock(), SigningKey);
        var vehicle = Query() with { ObjectClass = ObjectClass.Vehicle, Limit = 1 };
        var car = Query() with { ObjectSubclass = "car", Limit = 1 };

        var carCursor = (await service.SearchAsync(car, default)).Page!.NextCursor!;
        var vehicleCursor = (await service.SearchAsync(vehicle, default)).Page!.NextCursor!;

        Assert.False((await service.SearchAsync(vehicle with { Cursor = carCursor }, default)).IsSuccess);
        Assert.False((await service.SearchAsync(car with { Cursor = vehicleCursor }, default)).IsSuccess);
        Assert.True((await service.SearchAsync(car with { ObjectClass = ObjectClass.Vehicle, Cursor = carCursor }, default)).IsSuccess);
        Assert.True((await service.SearchAsync(vehicle with { Cursor = vehicleCursor }, default)).IsSuccess);
    }

    // --- fixtures -------------------------------------------------------------

    private static TrackSearchQuery Query() => new(
        CameraId: null,
        VideoAssetId: null,
        ProcessingRunId: null,
        ObjectClass: null,
        FromUtc: null,
        ToUtc: null,
        MinimumDurationMs: null,
        MinimumConfidence: null,
        Cursor: null,
        Limit: 50);

    private static TrackSearchRow Row(DateTimeOffset? timestamp = null)
    {
        var at = timestamp ?? FixedNow.AddMinutes(-5);
        return new TrackSearchRow(
            Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(), Guid.CreateVersion7(),
            "CAM-01", "Gate", ObjectClass.Vehicle, at, at.AddSeconds(1), 0, 1000, 1000, 5, 0.8, 0.9,
            ReviewStatus.Unreviewed, null);
    }

    private sealed class FixedClock : TimeProvider
    {
        public override DateTimeOffset GetUtcNow() => FixedNow;
    }

    private sealed class RecordingRepository : ITrackSearchRepository
    {
        public TrackSearchQuery? LastQuery { get; private set; }

        public Task<TrackSearchRepositoryPage> SearchAsync(
            TrackSearchQuery query, TrackCursorPosition? cursor, int take, CancellationToken cancellationToken)
        {
            LastQuery = query;
            IReadOnlyList<TrackSearchRow> rows =
            [
                Row(FixedNow.AddMinutes(-3)),
                Row(FixedNow.AddMinutes(-4)),
            ];
            return Task.FromResult(new TrackSearchRepositoryPage(rows, cursor?.SnapshotUtc ?? FixedNow, 101));
        }

        public Task<TrackDetailRow?> GetDetailAsync(Guid trackId, CancellationToken cancellationToken) =>
            Task.FromResult<TrackDetailRow?>(null);

        public Task<IReadOnlyList<TrackEvidenceObservationRow>> GetEvidenceSetAsync(Guid trackId, CancellationToken cancellationToken) =>
            Task.FromResult<IReadOnlyList<TrackEvidenceObservationRow>>([]);

        public Task<TrackAnalyticsSearchRepositoryResult> SearchAnalyticsAsync(
            TrackSearchQuery query, TrackAnalyticsCursorPosition? cursor, int take, CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Not an analytic test.");

        public Task<TrackDetailAnalyticsResult?> GetDetailAnalyticsAsync(
            Guid trackId, TrackAnalyticsDetailRequest request, CancellationToken cancellationToken) =>
            Task.FromResult<TrackDetailAnalyticsResult?>(null);
    }
}
