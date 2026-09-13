using System.Net;
using System.Net.Http.Json;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;

namespace Mavi.IntegrationTests;

[Collection(DatabaseIntegrationGroup.Name)]
public sealed class TrackSearchApiTests
{
    [Fact]
    public async Task DefaultSearchReturnsOnlyLatestCompletedRunPerVideo()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var oldTrack = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 7, 0, 0, TimeSpan.Zero),
            1_000,
            ObjectClass.Person,
            0.70);
        var latestTrack = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            5_000,
            ObjectClass.Vehicle,
            0.90);

        using var client = factory.CreateClient();
        var response = await client.GetFromJsonAsync<TrackSearchResponse>("/api/tracks");

        Assert.NotNull(response);
        var item = Assert.Single(response.Items);
        Assert.Equal(latestTrack.TrackId, item.Id);
        Assert.DoesNotContain(response.Items, x => x.Id == oldTrack.TrackId);
    }

    [Fact]
    public async Task ExplicitCompletedRunCanSearchHistoricalTrack()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var oldTrack = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 7, 0, 0, TimeSpan.Zero),
            1_000);
        _ = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            5_000);

        using var client = factory.CreateClient();
        var response = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?processingRunId={oldTrack.ProcessingRunId:D}");

        Assert.NotNull(response);
        var item = Assert.Single(response.Items);
        Assert.Equal(oldTrack.TrackId, item.Id);
    }

    [Fact]
    public async Task LaterFailedRunDoesNotHideLastCompletedIntelligence()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var completed = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            2_000);
        _ = await Task14TestData.AddFailedRunAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 9, 0, 0, TimeSpan.Zero));

        using var client = factory.CreateClient();
        var response = await client.GetFromJsonAsync<TrackSearchResponse>("/api/tracks");

        Assert.NotNull(response);
        Assert.Equal(completed.TrackId, Assert.Single(response.Items).Id);
    }

    [Fact]
    public async Task TimeFilterUsesIntervalOverlap()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var track = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            startOffsetMs: 1_000);

        using var client = factory.CreateClient();
        var from = Uri.EscapeDataString(
            video.RecordingStartUtc.AddMilliseconds(2_500).ToString("O"));
        var to = Uri.EscapeDataString(
            video.RecordingStartUtc.AddMilliseconds(4_000).ToString("O"));
        var overlap = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?fromUtc={from}&toUtc={to}");

        Assert.NotNull(overlap);
        Assert.Equal(track.TrackId, Assert.Single(overlap.Items).Id);

        from = Uri.EscapeDataString(
            video.RecordingStartUtc.AddMilliseconds(3_001).ToString("O"));
        var noOverlap = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?fromUtc={from}");

        Assert.NotNull(noOverlap);
        Assert.Empty(noOverlap.Items);
    }

    [Fact]
    public async Task CameraClassDurationAndConfidenceFiltersComposeWithAnd()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var firstVideo = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-A");
        var secondVideo = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-B");
        var wanted = await Task14TestData.AddCompletedTrackAsync(
            factory,
            firstVideo,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            2_000,
            ObjectClass.Vehicle,
            0.90);
        _ = await Task14TestData.AddCompletedTrackAsync(
            factory,
            secondVideo,
            new DateTimeOffset(2026, 9, 13, 8, 5, 0, TimeSpan.Zero),
            2_000,
            ObjectClass.Vehicle,
            0.95);

        using var client = factory.CreateClient();
        var response = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?cameraId={firstVideo.CameraId:D}&objectClass=Vehicle&minimumDurationMs=2000&minimumConfidence=0.85");

        Assert.NotNull(response);
        Assert.Equal(wanted.TrackId, Assert.Single(response.Items).Id);
    }

    [Fact]
    public async Task CursorPaginationIsStableWhenNewerTrackAppearsBetweenRequests()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();

        var video1 = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-P1",
            new DateTimeOffset(2026, 9, 13, 6, 0, 0, TimeSpan.Zero));
        var video2 = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-P2",
            new DateTimeOffset(2026, 9, 13, 7, 0, 0, TimeSpan.Zero));
        var video3 = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-P3",
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero));

        var first = await Task14TestData.AddCompletedTrackAsync(
            factory, video3,
            new DateTimeOffset(2026, 9, 13, 9, 0, 0, TimeSpan.Zero), 10_000);
        var second = await Task14TestData.AddCompletedTrackAsync(
            factory, video2,
            new DateTimeOffset(2026, 9, 13, 9, 0, 0, TimeSpan.Zero), 10_000);
        var third = await Task14TestData.AddCompletedTrackAsync(
            factory, video1,
            new DateTimeOffset(2026, 9, 13, 9, 0, 0, TimeSpan.Zero), 10_000);

        using var client = factory.CreateClient();
        var page1 = await client.GetFromJsonAsync<TrackSearchResponse>("/api/tracks?limit=2");
        Assert.NotNull(page1);
        Assert.Equal(2, page1.Items.Count);
        Assert.NotNull(page1.NextCursor);

        var newerVideo = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-P4",
            new DateTimeOffset(2026, 9, 13, 10, 0, 0, TimeSpan.Zero));
        _ = await Task14TestData.AddCompletedTrackAsync(
            factory, newerVideo,
            new DateTimeOffset(2026, 9, 13, 10, 30, 0, TimeSpan.Zero), 10_000);

        var page2 = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?limit=2&cursor={Uri.EscapeDataString(page1.NextCursor!)}");
        Assert.NotNull(page2);

        var combined = page1.Items.Concat(page2.Items).Select(x => x.Id).ToArray();
        Assert.Equal(3, combined.Distinct().Count());
        Assert.Contains(first.TrackId, combined);
        Assert.Contains(second.TrackId, combined);
        Assert.Contains(third.TrackId, combined);
    }

    [Fact]
    public async Task CursorPaginationUsesTrackIdAsDeterministicTieBreaker()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();

        var start = new DateTimeOffset(2026, 9, 13, 10, 0, 0, TimeSpan.Zero);
        var firstVideo = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-TIE-A", start);
        var secondVideo = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-TIE-B", start);

        var firstTrack = await Task14TestData.AddCompletedTrackAsync(
            factory,
            firstVideo,
            new DateTimeOffset(2026, 9, 13, 11, 0, 0, TimeSpan.Zero),
            5_000);
        var secondTrack = await Task14TestData.AddCompletedTrackAsync(
            factory,
            secondVideo,
            new DateTimeOffset(2026, 9, 13, 11, 0, 0, TimeSpan.Zero),
            5_000);

        Assert.Equal(firstTrack.StartTimestampUtc, secondTrack.StartTimestampUtc);

        using var client = factory.CreateClient();
        var page1 = await client.GetFromJsonAsync<TrackSearchResponse>("/api/tracks?limit=1");
        Assert.NotNull(page1);
        var firstItem = Assert.Single(page1.Items);
        Assert.NotNull(page1.NextCursor);

        var page2 = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?limit=1&cursor={Uri.EscapeDataString(page1.NextCursor!)}");
        Assert.NotNull(page2);
        var secondItem = Assert.Single(page2.Items);

        Assert.NotEqual(firstItem.Id, secondItem.Id);
        Assert.Equal(
            new[] { firstTrack.TrackId, secondTrack.TrackId }.OrderBy(x => x).ToArray(),
            new[] { firstItem.Id, secondItem.Id }.OrderBy(x => x).ToArray());
    }

    [Fact]
    public async Task CursorSnapshotPreventsReprocessingFromReplacingContinuationSet()
    {
        var clock = new AdvancingTimeProvider(
            new DateTimeOffset(2026, 9, 13, 12, 0, 0, TimeSpan.Zero));
        using var factory = new ApiTestFactory { Clock = clock };
        await factory.ResetAndMigrateAsync();

        var olderVideo = await Task14TestData.SeedBaseVideoAsync(
            factory,
            "CAM-SNAP-A",
            new DateTimeOffset(2026, 9, 13, 10, 0, 0, TimeSpan.Zero));
        var newerVideo = await Task14TestData.SeedBaseVideoAsync(
            factory,
            "CAM-SNAP-B",
            new DateTimeOffset(2026, 9, 13, 11, 0, 0, TimeSpan.Zero));

        var oldContinuation = await Task14TestData.AddCompletedTrackAsync(
            factory,
            olderVideo,
            new DateTimeOffset(2026, 9, 13, 11, 30, 0, TimeSpan.Zero),
            5_000);
        _ = await Task14TestData.AddCompletedTrackAsync(
            factory,
            newerVideo,
            new DateTimeOffset(2026, 9, 13, 11, 40, 0, TimeSpan.Zero),
            5_000);

        using var client = factory.CreateClient();
        var page1 = await client.GetFromJsonAsync<TrackSearchResponse>(
            "/api/tracks?limit=1");
        Assert.NotNull(page1);
        Assert.Single(page1.Items);
        Assert.NotNull(page1.NextCursor);

        clock.Advance(TimeSpan.FromMinutes(10));
        var replacement = await Task14TestData.AddCompletedTrackAsync(
            factory,
            olderVideo,
            new DateTimeOffset(2026, 9, 13, 12, 5, 0, TimeSpan.Zero),
            20_000);

        var page2 = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?limit=1&cursor={Uri.EscapeDataString(page1.NextCursor!)}");

        Assert.NotNull(page2);
        var continuation = Assert.Single(page2.Items);
        Assert.Equal(oldContinuation.TrackId, continuation.Id);
        Assert.NotEqual(replacement.TrackId, continuation.Id);
    }

    [Theory]
    [InlineData("/api/tracks?limit=0")]
    [InlineData("/api/tracks?limit=101")]
    [InlineData("/api/tracks?minimumDurationMs=-1")]
    [InlineData("/api/tracks?minimumConfidence=1.1")]
    [InlineData("/api/tracks?cursor=***")]
    [InlineData("/api/tracks?fromUtc=2026-09-13T10:00:00%2B05:30")]
    [InlineData("/api/tracks?fromUtc=2026-09-13T10:00:00")]
    [InlineData("/api/tracks?objectClass=0")]
    [InlineData("/api/tracks?unknownFilter=value")]
    public async Task InvalidSearchReturnsStableError(string path)
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(path);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains(
            "track_search_invalid",
            await response.Content.ReadAsStringAsync(),
            StringComparison.Ordinal);
    }

    [Fact]
    public async Task SearchAndDetailNeverExposeStorageKeys()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var track = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            1_000);

        using var client = factory.CreateClient();
        var searchJson = await client.GetStringAsync("/api/tracks");
        var detailJson = await client.GetStringAsync($"/api/tracks/{track.TrackId:D}");

        Assert.DoesNotContain("storageKey", searchJson, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("evidence/", searchJson, StringComparison.Ordinal);
        Assert.DoesNotContain("storageKey", detailJson, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("evidence/", detailJson, StringComparison.Ordinal);
    }

    [Fact]
    public async Task HistoricalCompletedTrackDetailRemainsAddressable()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var video = await Task14TestData.SeedBaseVideoAsync(factory);
        var oldTrack = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 7, 0, 0, TimeSpan.Zero),
            1_000);
        _ = await Task14TestData.AddCompletedTrackAsync(
            factory,
            video,
            new DateTimeOffset(2026, 9, 13, 8, 0, 0, TimeSpan.Zero),
            5_000);

        using var client = factory.CreateClient();
        using var response = await client.GetAsync($"/api/tracks/{oldTrack.TrackId:D}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var detail = await response.Content.ReadFromJsonAsync<TrackDetailResponse>();
        Assert.NotNull(detail);
        Assert.Equal(oldTrack.TrackId, detail.Id);
        Assert.NotNull(detail.Representative);
        Assert.Equal(oldTrack.ThumbnailArtifactId, detail.Representative.ThumbnailArtifactId);
        Assert.Equal(oldTrack.TrajectoryArtifactId, detail.TrajectoryArtifactId);
    }
    private sealed class AdvancingTimeProvider(DateTimeOffset now) : TimeProvider
    {
        private DateTimeOffset _now = now;

        public override DateTimeOffset GetUtcNow() => _now;

        public void Advance(TimeSpan duration) => _now = _now.Add(duration);
    }

}
