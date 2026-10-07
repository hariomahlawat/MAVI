using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>
/// Stage 3 X2 and X3 over HTTP: the operator-facing vehicle subclass (X1: <c>car</c> from the
/// release profile only) on <c>GET /api/tracks</c> and <c>GET /api/tracks/{id}</c>, and the
/// unchanged Vehicle population of every pre-existing search.
/// </summary>
/// <remarks>
/// One completed run holds every case side by side, so a single ordinary search sees them
/// all: release-profile car, truck, bus and motorcycle; a car resolved by the Development-only
/// A2 profile; an undetermined Vehicle (vocabulary and source, no subclass); a legacy Vehicle
/// with no Stage-3 fields; and a Person. X1 restricts what an operator sees about a Track's
/// subclass; it never narrows which Vehicle Tracks a search returns.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VehicleSubclassExposureApiTests
{
    private const string A2Source =
        "detector-native:b4c6a6cf8c68382f3af266b884801dbb77fb908cbaca7ed41336d4834463e62e";

    private static readonly DateTimeOffset CompletedAtUtc = new(2026, 9, 13, 8, 0, 0, TimeSpan.Zero);

    private enum Case
    {
        ReleaseCar,
        ReleaseCarLater,
        ReleaseTruck,
        ReleaseBus,
        ReleaseMotorcycle,
        A2Car,
        Undetermined,
        LegacyVehicle,
        Person,
    }

    // number, class, start offset, mean confidence, subclass, source
    private static readonly (Case Case, ObjectClass Class, long StartMs, double Confidence, string? Subclass, string? Source)[] Cases =
    [
        (Case.ReleaseCar, ObjectClass.Vehicle, 1_000, 0.90, "car", VehicleSubclassExposurePolicy.ApprovedSource),
        (Case.ReleaseCarLater, ObjectClass.Vehicle, 9_000, 0.60, "car", VehicleSubclassExposurePolicy.ApprovedSource),
        (Case.ReleaseTruck, ObjectClass.Vehicle, 2_000, 0.90, "truck", VehicleSubclassExposurePolicy.ApprovedSource),
        (Case.ReleaseBus, ObjectClass.Vehicle, 3_000, 0.90, "bus", VehicleSubclassExposurePolicy.ApprovedSource),
        (Case.ReleaseMotorcycle, ObjectClass.Vehicle, 4_000, 0.90, "motorcycle", VehicleSubclassExposurePolicy.ApprovedSource),
        (Case.A2Car, ObjectClass.Vehicle, 5_000, 0.90, "car", A2Source),
        (Case.Undetermined, ObjectClass.Vehicle, 6_000, 0.90, null, VehicleSubclassExposurePolicy.ApprovedSource),
        (Case.LegacyVehicle, ObjectClass.Vehicle, 7_000, 0.90, null, null),
        (Case.Person, ObjectClass.Person, 8_000, 0.90, null, null),
    ];

    private sealed record World(Task14TestData.BaseVideo Video, Guid RunId, IReadOnlyDictionary<Case, Guid> Tracks)
    {
        public Guid this[Case key] => Tracks[key];

        public HashSet<Guid> Where(Func<(Case Case, ObjectClass Class, long StartMs, double Confidence, string? Subclass, string? Source), bool> predicate) =>
            [.. Cases.Where(predicate).Select(item => Tracks[item.Case])];

        public HashSet<Guid> Vehicles => Where(item => item.Class == ObjectClass.Vehicle);
    }

    // --- X3: the Vehicle population is unchanged --------------------------------

    [Fact]
    public async Task EveryPreExistingVehicleSearchReturnsEveryVehicleWhateverItsSubclass()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        var from = Uri.EscapeDataString(world.Video.RecordingStartUtc.AddMilliseconds(2_500).ToString("O"));
        var to = Uri.EscapeDataString(world.Video.RecordingStartUtc.AddMilliseconds(6_500).ToString("O"));

        // Pre-X2 semantics, stated from the seed rather than read back from the system:
        // every Vehicle, hidden subclass or not, A2 car or not, legacy or not.
        Assert.Equal(world.Vehicles, await IdsAsync(client, "/api/tracks?objectClass=Vehicle"));
        Assert.Equal(world.Vehicles, await IdsAsync(client, "/api/tracks?objectClass=vehicle"));
        Assert.Equal(world.Where(_ => true), await IdsAsync(client, "/api/tracks"));
        Assert.Equal(world.Vehicles, await IdsAsync(client, $"/api/tracks?cameraId={world.Video.CameraId:D}&objectClass=Vehicle"));
        Assert.Equal(world.Vehicles, await IdsAsync(client, $"/api/tracks?videoAssetId={world.Video.VideoId:D}&objectClass=Vehicle"));
        Assert.Equal(world.Vehicles, await IdsAsync(client, $"/api/tracks?processingRunId={world.RunId:D}&objectClass=Vehicle"));
        // Overlap with [2.5 s, 6.5 s): each Track runs 2 s from its start offset.
        Assert.Equal(
            world.Where(item => item.Class == ObjectClass.Vehicle && item.StartMs + 2_000 >= 2_500 && item.StartMs < 6_500),
            await IdsAsync(client, $"/api/tracks?objectClass=Vehicle&fromUtc={from}&toUtc={to}"));
        Assert.Equal(
            world.Where(item => item.Class == ObjectClass.Vehicle && item.Confidence >= 0.85),
            await IdsAsync(client, "/api/tracks?objectClass=Vehicle&minimumDurationMs=2000&minimumConfidence=0.85"));
    }

    [Fact]
    public async Task APaginatedVehicleSearchWalksTheSamePopulation()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        var seen = new List<Guid>();
        string? cursor = null;
        do
        {
            var path = "/api/tracks?objectClass=Vehicle&limit=2" + (cursor is null ? "" : "&cursor=" + cursor);
            var page = await client.GetFromJsonAsync<TrackSearchResponse>(path);
            seen.AddRange(page!.Items.Select(item => item.Id));
            cursor = page.NextCursor;
        }
        while (cursor is not null);

        Assert.Equal(seen.Count, seen.Distinct().Count());
        Assert.Equal(world.Vehicles, seen.ToHashSet());
    }

    // --- X2: the subclass filter ------------------------------------------------

    [Theory]
    [InlineData("/api/tracks?objectSubclass=car")]
    [InlineData("/api/tracks?objectClass=Vehicle&objectSubclass=car")]
    public async Task TheCarFilterMatchesOnlyReleaseProfileCars(string path)
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        var response = await client.GetFromJsonAsync<TrackSearchResponse>(path);

        Assert.Equal([world[Case.ReleaseCar], world[Case.ReleaseCarLater]], response!.Items.Select(item => item.Id).ToHashSet());
        Assert.All(response.Items, item =>
        {
            Assert.Equal("Vehicle", item.ObjectClass);
            Assert.Equal("car", item.ObjectSubclass);
        });
        // The A2 car is a Vehicle with persisted subclass `car`, and is still not a match.
        Assert.DoesNotContain(world[Case.A2Car], response.Items.Select(item => item.Id));
    }

    [Fact]
    public async Task TheCarFilterComposesWithEveryOrdinaryFilter()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        Assert.Equal(
            [world[Case.ReleaseCar]],
            await IdsAsync(client, $"/api/tracks?cameraId={world.Video.CameraId:D}&objectSubclass=car&minimumConfidence=0.85"));
        Assert.Equal(
            [world[Case.ReleaseCarLater]],
            await IdsAsync(client, $"/api/tracks?processingRunId={world.RunId:D}&objectSubclass=car&fromUtc={Uri.EscapeDataString(world.Video.RecordingStartUtc.AddSeconds(8).ToString("O"))}"));
    }

    [Theory]
    [InlineData("/api/tracks?objectSubclass=truck")]
    [InlineData("/api/tracks?objectSubclass=bus")]
    [InlineData("/api/tracks?objectSubclass=motorcycle")]
    [InlineData("/api/tracks?objectSubclass=Car")]
    [InlineData("/api/tracks?objectSubclass=CAR")]
    [InlineData("/api/tracks?objectSubclass=van")]
    [InlineData("/api/tracks?objectSubclass=")]
    [InlineData("/api/tracks?objectSubclass=%20car")]
    [InlineData("/api/tracks?objectSubclass=car&objectSubclass=car")]
    [InlineData("/api/tracks?objectClass=Person&objectSubclass=car")]
    public async Task AnyOtherSubclassRequestIsTheOrdinarySearchValidationFailure(string path)
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        _ = await SeedAsync(factory);
        using var client = factory.CreateClient();

        using var response = await client.GetAsync(path);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("track_search_invalid", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    // --- X2: what an operator sees ------------------------------------------------

    [Fact]
    public async Task SearchAndDetailExposeCarOnlyFromTheReleaseProfileAndNothingElse()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        var search = await client.GetFromJsonAsync<TrackSearchResponse>("/api/tracks");
        var exposed = search!.Items.ToDictionary(item => item.Id, item => item.ObjectSubclass);
        foreach (var (key, id) in world.Tracks)
        {
            var expected = key is Case.ReleaseCar or Case.ReleaseCarLater ? "car" : null;
            Assert.Equal(expected, exposed[id]);

            var detail = await client.GetFromJsonAsync<TrackDetailResponse>($"/api/tracks/{id:D}");
            Assert.Equal(expected, detail!.ObjectSubclass);
            // Search and detail ask the same policy and agree on every Track.
            Assert.Equal(exposed[id], detail.ObjectSubclass);
        }
    }

    [Fact]
    public async Task NoHiddenSubclassValueOrSourceReachesTheWire()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        var world = await SeedAsync(factory);
        using var client = factory.CreateClient();

        var searchJson = await client.GetStringAsync("/api/tracks");
        var vehicleJson = await client.GetStringAsync("/api/tracks?objectClass=Vehicle");
        foreach (var json in new[] { searchJson, vehicleJson })
            AssertNoHiddenValues(json, exposedCars: 2);

        foreach (var key in new[] { Case.ReleaseTruck, Case.ReleaseBus, Case.ReleaseMotorcycle, Case.A2Car, Case.Undetermined, Case.LegacyVehicle, Case.Person })
        {
            var json = await client.GetStringAsync($"/api/tracks/{world[key]:D}");
            AssertNoHiddenValues(json, exposedCars: 0);
            using var document = JsonDocument.Parse(json);
            Assert.False(document.RootElement.TryGetProperty("objectSubclass", out _), key.ToString());
        }

        var carJson = await client.GetStringAsync($"/api/tracks/{world[Case.ReleaseCar]:D}");
        AssertNoHiddenValues(carJson, exposedCars: 1);
    }

    // --- X2: cursor identity ------------------------------------------------------

    [Fact]
    public async Task ACursorBelongsToItsSubclassPredicate()
    {
        using var factory = new ApiTestFactory();
        await factory.ResetAndMigrateAsync();
        _ = await SeedAsync(factory);
        using var client = factory.CreateClient();

        var carPage = await client.GetFromJsonAsync<TrackSearchResponse>("/api/tracks?objectSubclass=car&limit=1");
        var vehiclePage = await client.GetFromJsonAsync<TrackSearchResponse>("/api/tracks?objectClass=Vehicle&limit=1");
        var carCursor = Uri.EscapeDataString(carPage!.NextCursor!);
        var vehicleCursor = Uri.EscapeDataString(vehiclePage!.NextCursor!);

        // A car cursor is not an ordinary Vehicle cursor, and the reverse.
        await AssertInvalidAsync(client, $"/api/tracks?objectClass=Vehicle&limit=1&cursor={carCursor}");
        await AssertInvalidAsync(client, $"/api/tracks?objectSubclass=car&limit=1&cursor={vehicleCursor}");
        await AssertInvalidAsync(client, $"/api/tracks?objectClass=Vehicle&objectSubclass=car&limit=1&cursor={vehicleCursor}");
        await AssertInvalidAsync(client, $"/api/tracks?limit=1&cursor={carCursor}");

        // The canonical equivalent of the car search continues it.
        var continued = await client.GetFromJsonAsync<TrackSearchResponse>(
            $"/api/tracks?objectClass=Vehicle&objectSubclass=car&limit=1&cursor={carCursor}");
        var next = Assert.Single(continued!.Items);
        Assert.NotEqual(carPage.Items[0].Id, next.Id);
        Assert.Equal("car", next.ObjectSubclass);
        Assert.Null(continued.NextCursor);
    }

    // --- helpers ------------------------------------------------------------------

    private static void AssertNoHiddenValues(string json, int exposedCars)
    {
        foreach (var hidden in new[] { "\"truck\"", "\"bus\"", "\"motorcycle\"", "detector-native", "b4c6a6cf", "afb03b6c", "mavi-vehicle-subclass" })
            Assert.DoesNotContain(hidden, json, StringComparison.OrdinalIgnoreCase);
        Assert.Equal(exposedCars, CountOccurrences(json, "\"objectSubclass\":\"car\""));
        Assert.Equal(exposedCars, CountOccurrences(json, "\"objectSubclass\""));
    }

    private static int CountOccurrences(string text, string value)
    {
        var count = 0;
        for (var index = text.IndexOf(value, StringComparison.Ordinal); index >= 0;
             index = text.IndexOf(value, index + value.Length, StringComparison.Ordinal))
            count++;
        return count;
    }

    private static async Task AssertInvalidAsync(HttpClient client, string path)
    {
        using var response = await client.GetAsync(path);
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("track_search_invalid", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    private static async Task<HashSet<Guid>> IdsAsync(HttpClient client, string path)
    {
        var response = await client.GetFromJsonAsync<TrackSearchResponse>(path);
        Assert.NotNull(response);
        Assert.Null(response.NextCursor);
        return [.. response.Items.Select(item => item.Id)];
    }

    /// <summary>One completed run on one video holding every case.</summary>
    private static async Task<World> SeedAsync(ApiTestFactory factory)
    {
        var video = await Task14TestData.SeedBaseVideoAsync(factory, "CAM-X2");
        var run = ProcessingRun.Create(video.VideoId, "phase1-detection-tracking-v1", "{}", CompletedAtUtc.AddMinutes(-2));
        run.MarkRunning("worker-01", CompletedAtUtc.AddMinutes(-1));

        var tracks = new Dictionary<Case, Guid>();
        var entities = new List<Track>();
        for (var index = 0; index < Cases.Length; index++)
        {
            var item = Cases[index];
            var track = Track.Create(
                run.Id,
                video.VideoId,
                index + 1,
                item.Class,
                item.StartMs,
                item.StartMs + 2_000,
                video.RecordingStartUtc,
                detectionCount: 8,
                meanConfidence: item.Confidence,
                maxConfidence: Math.Min(1.0, item.Confidence + 0.05),
                createdAtUtc: CompletedAtUtc,
                objectSubclass: item.Subclass,
                objectSubclassVocabulary: item.Source is null ? null : VehicleSubclass.VocabularyV1,
                objectSubclassSource: item.Source);
            tracks[item.Case] = track.Id;
            entities.Add(track);
        }

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        db.ProcessingRuns.Add(run);
        db.Tracks.AddRange(entities);
        await db.SaveChangesAsync();

        await using var completion = await db.Database.BeginTransactionAsync();
        await ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync(db, CancellationToken.None);
        var sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, CancellationToken.None);
        run.MarkCompleted(framesProcessed: 300, tracksCreated: entities.Count, durationMs: 12_000, completedAtUtc: CompletedAtUtc);
        run.AssignCompletionVisibilitySequence(sequence);
        await db.SaveChangesAsync();
        await completion.CommitAsync();

        return new World(video, run.Id, tracks);
    }
}
