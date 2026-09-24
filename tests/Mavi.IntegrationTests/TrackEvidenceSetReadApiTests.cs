using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using static Mavi.IntegrationTests.Task14TestData;

namespace Mavi.IntegrationTests;

/// <summary>
/// S1.3a: <c>GET /api/tracks/{id}</c> reads the Track's Evidence Set as the one
/// authority for its evidence and its Representative (S1.3 plan D1, §4–§6, §12.1).
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackEvidenceSetReadApiTests
{
    private static readonly DateTimeOffset CompletedAt = new(2026, 9, 24, 8, 0, 0, TimeSpan.Zero);

    private static readonly (ObservationType, int)[] FullSet =
    [
        (ObservationType.Representative, 0),
        (ObservationType.NearView, 1),
        (ObservationType.EarlyDiverse, 2),
        (ObservationType.LateDiverse, 3),
    ];

    // --- valid shapes ---------------------------------------------------------------

    [Fact]
    public async Task AV3TrackCompletedThroughTheRealWritePathReadsBackAsItsFullEvidenceSet()
    {
        using var factory = new ApiTestFactory { Clock = new MutableTimeProvider(CompletedAt) };
        await factory.ResetAndMigrateAsync();
        var videoId = await VisionResultCompletionApiTests.SeedVideoAsync(factory);
        using var client = factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, "gpu-sdd-01");
        var request = await VisionResultCompletionV3ApiTests.BuildRequestAsync(
            factory, lease, ["representative", "near-view", "early-diverse", "late-diverse"]);
        (await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request)).EnsureSuccessStatusCode();

        List<Observation> persisted;
        Guid trackId;
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            trackId = (await db.Tracks.SingleAsync()).Id;
            persisted = await db.Observations.OrderBy(x => x.EvidenceRank).ToListAsync();
        }

        var detail = await client.GetFromJsonAsync<TrackDetailResponse>($"/api/tracks/{trackId:D}");

        Assert.NotNull(detail);
        Assert.Equal(["Representative", "NearView", "EarlyDiverse", "LateDiverse"], detail.Observations.Select(x => x.EvidenceRole));
        Assert.Equal([0, 1, 2, 3], detail.Observations.Select(x => x.EvidenceRank));
        foreach (var (read, stored) in detail.Observations.Zip(persisted))
        {
            Assert.Equal(stored.Id, read.ObservationId);
            Assert.Equal(stored.SourceFrameNumber, read.SourceFrameNumber);
            Assert.Equal(stored.VideoOffsetMs, read.VideoOffsetMs);
            Assert.Equal(stored.Confidence, read.Confidence);
            Assert.Equal(stored.QualityScore, read.QualityScore);
            Assert.Equal(stored.SelectionScore, read.SelectionScore);
            Assert.Equal(stored.ThumbnailArtifactId, read.EvidenceArtifactId);
            Assert.Equal($"/api/artifacts/{stored.ThumbnailArtifactId:D}/content", read.EvidenceContentUrl);
        }

        AssertRepresentativeIsRankZero(detail);
    }

    [Fact]
    public async Task ObservationsAreReturnedInRankOrderNotInOffsetOrScoreOrder()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        // Seeded in reverse, so insertion order, offset order and score order all run
        // against rank order: only a rank ordering yields 0..3.
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, [.. FullSet.Reverse()], new RepresentativePointer.RankZero());

        var detail = await GetDetailAsync(factory, seeded.TrackId);

        Assert.Equal([0, 1, 2, 3], detail.Observations.Select(x => x.EvidenceRank));
        Assert.Equal(["Representative", "NearView", "EarlyDiverse", "LateDiverse"], detail.Observations.Select(x => x.EvidenceRole));
        Assert.True(detail.Observations[0].VideoOffsetMs > detail.Observations[3].VideoOffsetMs);
        Assert.Equal(seeded.ObservationIds.Reverse(), detail.Observations.Select(x => x.ObservationId));
        AssertRepresentativeIsRankZero(detail);
    }

    [Fact]
    public async Task AnOmittedSupplementalRoleIsAValidPartialSet()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt,
            [(ObservationType.Representative, 0), (ObservationType.LateDiverse, 1)],
            new RepresentativePointer.RankZero());

        var detail = await GetDetailAsync(factory, seeded.TrackId);

        Assert.Equal(["Representative", "LateDiverse"], detail.Observations.Select(x => x.EvidenceRole));
        Assert.Equal([0, 1], detail.Observations.Select(x => x.EvidenceRank));
        AssertRepresentativeIsRankZero(detail);
    }

    [Fact]
    public async Task AHistoricalV2TrackReadsAsOneRepresentativeObservationWithItsThumbnail()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var track = await AddCompletedTrackAsync(factory, video, CompletedAt, 1_000);

        var detail = await GetDetailAsync(factory, track.TrackId);

        var only = Assert.Single(detail.Observations);
        Assert.Equal("Representative", only.EvidenceRole);
        Assert.Equal(0, only.EvidenceRank);
        // The historical crop is a Thumbnail artifact, not an EvidenceCrop, and is read as
        // it is: not reinterpreted, not rejected.
        Assert.Equal(track.ThumbnailArtifactId, only.EvidenceArtifactId);
        Assert.Equal(ArtifactType.Thumbnail, await ArtifactTypeAsync(factory, track.ThumbnailArtifactId));
        AssertRepresentativeIsRankZero(detail);

        using var client = factory.CreateClient();
        using var content = await client.GetAsync(only.EvidenceContentUrl);
        Assert.Equal(HttpStatusCode.OK, content.StatusCode);
        Assert.Equal("image/jpeg", content.Content.Headers.ContentType?.MediaType);
    }

    [Fact]
    public async Task ALegacyTrackWithNoRepresentativeRelationStaysReadableAndEmpty()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, [], new RepresentativePointer.None());

        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/tracks/{seeded.TrackId:D}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal(JsonValueKind.Null, json.RootElement.GetProperty("representative").ValueKind);
        // Present and empty, never absent or null: nothing is fabricated for the legacy
        // shape, and the contract still carries its array.
        Assert.Equal(JsonValueKind.Array, json.RootElement.GetProperty("observations").ValueKind);
        Assert.Equal(0, json.RootElement.GetProperty("observations").GetArrayLength());
    }

    // --- corrupt persisted sets fail closed ----------------------------------------

    [Fact]
    public async Task ARankGapFailsClosed()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt,
            [(ObservationType.Representative, 0), (ObservationType.NearView, 2)],
            new RepresentativePointer.RankZero());

        await AssertIntegrityFailureAsync(factory, seeded);
    }

    [Fact]
    public async Task RankOrderContradictingRoleOrderFailsClosed()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        // Contiguous, unique and Representative-first, so it satisfies every database
        // constraint. Only the canonical role order refuses it; sorting by role would
        // make it look valid.
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt,
            [(ObservationType.Representative, 0), (ObservationType.LateDiverse, 1), (ObservationType.NearView, 2)],
            new RepresentativePointer.RankZero());

        await AssertIntegrityFailureAsync(factory, seeded);
    }

    [Fact]
    public async Task APointerToANonRankZeroObservationOfThisTrackFailsClosed()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        // The removed pointer join would have answered 200 with this NearView as the
        // Representative. Rank 0 is the authority, so the contradiction is refused.
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, FullSet, new RepresentativePointer.Position(1));

        await AssertIntegrityFailureAsync(factory, seeded);
    }

    [Fact]
    public async Task APointerToAnotherTracksObservationFailsClosed()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var other = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt.AddMinutes(-5), FullSet, new RepresentativePointer.RankZero(), localTrackNumber: 1);
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, FullSet,
            new RepresentativePointer.External(other.ObservationIds[0]), localTrackNumber: 2);

        await AssertIntegrityFailureAsync(factory, seeded);
        // The Track the pointer was borrowed from is unaffected.
        AssertRepresentativeIsRankZero(await GetDetailAsync(factory, other.TrackId));
    }

    [Fact]
    public async Task APointerToAStaleObservationWhileThisTrackHasNoneFailsClosed()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var other = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt.AddMinutes(-5), FullSet, new RepresentativePointer.RankZero(), localTrackNumber: 1);
        // No Observations of its own, but a pointer: this is not the legacy empty shape,
        // and it must not be read as one.
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, [],
            new RepresentativePointer.External(other.ObservationIds[0]), localTrackNumber: 2);

        await AssertIntegrityFailureAsync(factory, seeded);
    }

    [Fact]
    public async Task ObservationsWithoutAnyRepresentativePointerFailClosed()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        // Distinguishes legitimate legacy absence (no pointer, no Observations) from a
        // modern set that has lost its pointer.
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, FullSet, new RepresentativePointer.None());

        await AssertIntegrityFailureAsync(factory, seeded);
    }

    [Fact]
    public async Task ADuplicateRankCannotBePersistedSoTheReadSeamOwnsOnlyTheShapesTheSchemaAdmits()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);

        // ux_observations_track_rank refuses it at write time. The read seam's duplicate
        // and negative-rank checks are therefore proved against direct inputs in
        // TrackEvidenceSetTests rather than against persisted rows.
        await Assert.ThrowsAsync<DbUpdateException>(() => AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt,
            [(ObservationType.Representative, 0), (ObservationType.NearView, 1), (ObservationType.EarlyDiverse, 1)],
            new RepresentativePointer.RankZero()));
    }

    [Fact]
    public async Task TheIntegrityFailureIsLoggedWithTheTrackAndTheViolatedRuleForTheOperator()
    {
        var logs = new CapturingLoggerProvider();
        using var factory = new ApiTestFactory
        {
            OverrideServices = services => services.AddSingleton<ILoggerProvider>(logs),
        };
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt,
            [(ObservationType.Representative, 0), (ObservationType.NearView, 2)],
            new RepresentativePointer.RankZero());

        await AssertIntegrityFailureAsync(factory, seeded);

        // The client got nothing specific. The detail goes to the log, where the
        // operator can find which Track and which rule.
        var entry = Assert.Single(logs.Entries, x => x.EventId.Id == 1420);
        Assert.Equal(LogLevel.Error, entry.Level);
        Assert.Equal("track_evidence_integrity_failure", entry.EventId.Name);
        Assert.Contains(seeded.TrackId.ToString(), entry.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("RankNotContiguous", entry.Message, StringComparison.Ordinal);
    }

    // --- evidence security and the wire shape --------------------------------------

    [Fact]
    public async Task EveryEvidenceUrlIsTheServerAuthoredContentRouteOfTheObservationsOwnCrop()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, FullSet, new RepresentativePointer.RankZero());

        var detail = await GetDetailAsync(factory, seeded.TrackId);
        using var client = factory.CreateClient();

        foreach (var (observation, cropId) in detail.Observations.Zip(seeded.CropArtifactIds))
        {
            Assert.Equal(cropId, observation.EvidenceArtifactId);
            Assert.Equal($"/api/artifacts/{cropId:D}/content", observation.EvidenceContentUrl);
            Assert.Equal(ArtifactType.EvidenceCrop, await ArtifactTypeAsync(factory, cropId));

            using var content = await client.GetAsync(observation.EvidenceContentUrl);
            Assert.Equal(HttpStatusCode.OK, content.StatusCode);
            Assert.Equal("image/jpeg", content.Content.Headers.ContentType?.MediaType);
            Assert.Equal(await StoredSizeAsync(factory, cropId), content.Content.Headers.ContentLength);
        }
    }

    [Fact]
    public async Task TheSameRouteStillRefusesAnEvidenceCropNoObservationReferences()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        _ = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, FullSet, new RepresentativePointer.RankZero());

        // A well-formed EvidenceCrop with real bytes that no Observation of a Completed
        // run references: the route the Track detail hands out must not become a way to
        // read it just because it is the right artifact type.
        var bytes = new byte[] { 7, 7, 7, 7 };
        var sha = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
        var orphan = Artifact.Create(ArtifactType.EvidenceCrop, $"evidence/orphan/{sha}.jpg", "image/jpeg", bytes.Length, sha);
        WriteEvidence(factory, orphan.StorageKey, bytes);
        using (var scope = factory.Services.CreateScope())
        {
            var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
            db.Artifacts.Add(orphan);
            await db.SaveChangesAsync();
        }

        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/artifacts/{orphan.Id:D}/content");
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task TheObservationWireShapeIsExactlyTheContract()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await SeedBaseVideoAsync(factory);
        var seeded = await AddTrackWithEvidenceSetAsync(
            factory, video, CompletedAt, FullSet, new RepresentativePointer.RankZero());

        using var client = factory.CreateClient();
        var body = await client.GetStringAsync($"/api/tracks/{seeded.TrackId:D}");
        using var json = JsonDocument.Parse(body);
        var observation = json.RootElement.GetProperty("observations")[2];

        Assert.Equal(
            ["observationId", "evidenceRole", "evidenceRank", "sourceFrameNumber", "videoOffsetMs", "timestampUtc",
             "confidence", "qualityScore", "selectionScore", "boundingBox", "evidenceArtifactId", "evidenceContentUrl"],
            observation.EnumerateObject().Select(x => x.Name));
        Assert.Equal("EarlyDiverse", observation.GetProperty("evidenceRole").GetString());
        Assert.Equal(2, observation.GetProperty("evidenceRank").GetInt32());
        Assert.Equal(["x", "y", "width", "height"], observation.GetProperty("boundingBox").EnumerateObject().Select(x => x.Name));
        // The compatibility object keeps its historical member names unchanged.
        Assert.Equal(
            ["observationId", "sourceFrameNumber", "videoOffsetMs", "timestampUtc", "confidence", "qualityScore",
             "boundingBox", "thumbnailArtifactId", "thumbnailContentUrl"],
            json.RootElement.GetProperty("representative").EnumerateObject().Select(x => x.Name));
        // No filesystem storage key leaks into the Track detail.
        Assert.DoesNotContain("evidence/", body, StringComparison.Ordinal);
        Assert.DoesNotContain(".jpg", body, StringComparison.Ordinal);
    }

    // --- helpers ---------------------------------------------------------------------

    /// <summary>The compatibility Representative is rank 0 of the same list, field for field.</summary>
    private static void AssertRepresentativeIsRankZero(TrackDetailResponse detail)
    {
        var rankZero = detail.Observations[0];
        var representative = Assert.IsType<TrackRepresentativeResponse>(detail.Representative);
        Assert.Equal("Representative", rankZero.EvidenceRole);
        Assert.Equal(rankZero.ObservationId, representative.ObservationId);
        Assert.Equal(rankZero.SourceFrameNumber, representative.SourceFrameNumber);
        Assert.Equal(rankZero.VideoOffsetMs, representative.VideoOffsetMs);
        Assert.Equal(rankZero.TimestampUtc, representative.TimestampUtc);
        Assert.Equal(rankZero.Confidence, representative.Confidence);
        Assert.Equal(rankZero.QualityScore, representative.QualityScore);
        Assert.Equal(rankZero.BoundingBox, representative.BoundingBox);
        Assert.Equal(rankZero.EvidenceArtifactId, representative.ThumbnailArtifactId);
        Assert.Equal(rankZero.EvidenceContentUrl, representative.ThumbnailContentUrl);
    }

    private static async Task AssertIntegrityFailureAsync(ApiTestFactory factory, SeededEvidence seeded)
    {
        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/tracks/{seeded.TrackId:D}");
        var body = await response.Content.ReadAsStringAsync();

        // Never a 404 (the Track exists), a 400 (the request is fine) or a repaired 200.
        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
        using var json = JsonDocument.Parse(body);
        Assert.Equal("track_evidence_integrity_failure", json.RootElement.GetProperty("code").GetString());
        // No internal detail reaches the client: no invariant name, no Observation id.
        Assert.DoesNotContain("invariant", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Rank", body, StringComparison.Ordinal);
        foreach (var id in seeded.ObservationIds)
            Assert.DoesNotContain(id.ToString("D"), body, StringComparison.OrdinalIgnoreCase);
    }

    private static async Task<TrackDetailResponse> GetDetailAsync(ApiTestFactory factory, Guid trackId)
    {
        using var client = factory.CreateClient();
        var detail = await client.GetFromJsonAsync<TrackDetailResponse>($"/api/tracks/{trackId:D}");
        Assert.NotNull(detail);
        return detail;
    }

    private static async Task<ArtifactType> ArtifactTypeAsync(ApiTestFactory factory, Guid artifactId)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        return (await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == artifactId)).ArtifactType;
    }

    private sealed record LoggedEntry(LogLevel Level, EventId EventId, string Message);

    private sealed class CapturingLoggerProvider : ILoggerProvider
    {
        private readonly System.Collections.Concurrent.ConcurrentQueue<LoggedEntry> _entries = new();

        public IReadOnlyCollection<LoggedEntry> Entries => _entries.ToArray();

        public ILogger CreateLogger(string categoryName) => new Capturing(_entries);

        public void Dispose()
        {
        }

        private sealed class Capturing(System.Collections.Concurrent.ConcurrentQueue<LoggedEntry> entries) : ILogger
        {
            public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

            public bool IsEnabled(LogLevel logLevel) => true;

            public void Log<TState>(
                LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter) =>
                entries.Enqueue(new LoggedEntry(logLevel, eventId, formatter(state, exception)));
        }
    }

    private static async Task<long> StoredSizeAsync(ApiTestFactory factory, Guid artifactId)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        return (await db.Artifacts.AsNoTracking().SingleAsync(x => x.Id == artifactId)).SizeBytes;
    }
}
