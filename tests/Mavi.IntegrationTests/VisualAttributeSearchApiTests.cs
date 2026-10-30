using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Mavi.IntegrationTests;

/// <summary>
/// PoC S5 (register C2.2): attribute Track search with the v4 cursor, its coverage, and the Track attribute detail,
/// over analyses published through the real S2b lease and completion plane. Stage-2 E5–E8 are not closed here.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeSearchApiTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 10, 29, 12, 0, 0, TimeSpan.Zero);
    private const string Lower = "fixture-person-lower";
    private const string Upper = "fixture-person-upper";

    private sealed record World(VisualAttributeApiHost Host, SeededRun RunA, SeededRun RunB, Guid CameraB);

    /// <summary>
    /// Camera A: three persons and a vehicle, lower <c>dark</c>, upper Unknown, the third person Unavailable.
    /// Camera B: two persons, both <c>light</c>.
    /// </summary>
    private async Task<World> PublishedWorldAsync()
    {
        var host = await VisualAttributeApiHost.CreateAsync(fixture, Now);
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        var cameraB = await host.World.CreateCameraAsync("CAM-VA-02");
        var runA = await host.World.SeedRunAsync(3, 1, completedAtUtc: host.World.Clock.GetUtcNow(), linkRepresentative: true);
        var runB = await host.World.SeedRunAsync(2, 0, completedAtUtc: host.World.Clock.GetUtcNow(), cameraId: cameraB);
        Assert.Equal(2, (await host.RunCycleAsync()).Queued);

        for (var index = 0; index < 2; index++)
        {
            var unit = await host.LeaseAsync();
            var isA = unit.Lease.ProcessingRunId == runA.RunId;
            var completion = isA
                ? AttributeCompletionBuilder.Build(unit, value: "dark", unknown: new HashSet<string> { Upper },
                    unavailable: track => track == runA.Track(2).TrackId ? "evidence_decode_failed" : null,
                    unavailableObservation: null)
                : AttributeCompletionBuilder.Build(unit, value: "light");
            using var response = await host.UploadAndCompleteAsync(unit, completion);
            Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        }

        return new World(host, runA, runB, cameraB);
    }

    private static async Task<JsonObject> GetJsonAsync(HttpClient client, string path)
    {
        using var response = await client.GetAsync(path);
        var text = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == HttpStatusCode.OK, $"{path}: {(int)response.StatusCode} {text}");
        return JsonNode.Parse(text)!.AsObject();
    }

    private static string[] Ids(JsonObject page) =>
        page["items"]!.AsArray().Select(item => item!["id"]!.GetValue<string>()).ToArray();

    [Fact]
    public async Task AnAttributeSearchSpansCamerasAndExplainsEachRowWithItsObservedValue()
    {
        var world = await PublishedWorldAsync();
        await using var owned = world.Host;
        var client = world.Host.Client;

        var dark = await GetJsonAsync(client, $"/api/tracks?attribute={Lower}:dark");
        Assert.Equal(
            new[] { world.RunA.Track(0).TrackId, world.RunA.Track(1).TrackId }.Select(id => id.ToString()).Order(),
            Ids(dark).Order());
        foreach (var item in dark["items"]!.AsArray())
        {
            Assert.Equal("Person", item!["objectClass"]!.GetValue<string>());
            var match = Assert.Single(item["attributes"]!.AsArray());
            Assert.Equal(Lower, match!["attributeType"]!.GetValue<string>());
            Assert.Equal("dark", match["value"]!.GetValue<string>());
            Assert.Equal(0.7, match["confidence"]!.GetValue<double>(), 6);
        }

        // Coverage over every Person Track of both cameras: four analysed, one unavailable, none missing.
        var coverage = dark["attributeCoverage"]!;
        Assert.Equal(world.Host.PreferredFingerprint, coverage["identityFingerprint"]!.GetValue<string>());
        Assert.Equal(5, coverage["tracksInScope"]!.GetValue<int>());
        Assert.Equal(4, coverage["analysed"]!.GetValue<int>());
        Assert.Equal(1, coverage["unavailable"]!.GetValue<int>());
        Assert.Equal(0, coverage["notAnalysed"]!.GetValue<int>());
        Assert.Equal($"{Lower}:dark", Assert.Single(coverage["predicates"]!.AsArray())!.GetValue<string>());

        // Attribute-only search is not camera-bound (E7): camera B's Tracks match their own value.
        var light = await GetJsonAsync(client, $"/api/tracks?attribute={Lower}:light");
        Assert.Equal(world.RunB.Tracks.Select(track => track.TrackId.ToString()).Order(), Ids(light).Order());
        Assert.All(light["items"]!.AsArray(), item => Assert.Equal(world.CameraB.ToString(), item!["cameraId"]!.GetValue<string>()));
    }

    [Fact]
    public async Task UnknownNeverMatchesAndIsCountedPerPredicate()
    {
        var world = await PublishedWorldAsync();
        await using var owned = world.Host;

        var page = await GetJsonAsync(world.Host.Client, $"/api/tracks?attribute={Lower}:dark&attribute={Upper}:dark");

        Assert.Empty(page["items"]!.AsArray());
        var unknown = page["attributeCoverage"]!["unknown"]!.AsArray();
        Assert.Equal([Lower, Upper], unknown.Select(item => item!["attributeType"]!.GetValue<string>()));
        Assert.Equal([0, 2], unknown.Select(item => item!["tracks"]!.GetValue<int>()));
    }

    [Fact]
    public async Task TheV4CursorPagesASnapshotAndAcceptsThePredicatesInAnyOrder()
    {
        var world = await PublishedWorldAsync();
        await using var owned = world.Host;
        var client = world.Host.Client;

        var first = await GetJsonAsync(client, $"/api/tracks?attribute={Upper}:light&attribute={Lower}:light&limit=1");
        var cursor = first["nextCursor"]!.GetValue<string>();
        var escaped = Uri.EscapeDataString(cursor);

        // The same predicates in canonical order are the same search, so the cursor continues it (E6).
        var second = await GetJsonAsync(client, $"/api/tracks?attribute={Lower}:light&attribute={Upper}:light&limit=1&cursor={escaped}");
        Assert.Null(second["nextCursor"]);
        Assert.Equal(world.RunB.Tracks.Select(track => track.TrackId.ToString()).Order(), Ids(first).Concat(Ids(second)).Order());
        // A continuation returns the coverage the first page pinned (E5).
        Assert.Equal(first["attributeCoverage"]!.ToJsonString(), second["attributeCoverage"]!.ToJsonString());

        // Another value, another identity's predicates or a tampered cursor is refused (E5).
        using (var otherValue = await client.GetAsync($"/api/tracks?attribute={Lower}:light&attribute={Upper}:dark&limit=1&cursor={escaped}"))
            Assert.Equal(HttpStatusCode.BadRequest, otherValue.StatusCode);
        var tampered = cursor[..^2] + (cursor[^2] == 'A' ? 'B' : 'A') + cursor[^1];
        using (var forged = await client.GetAsync($"/api/tracks?attribute={Lower}:light&attribute={Upper}:light&limit=1&cursor={Uri.EscapeDataString(tampered)}"))
            Assert.Equal(HttpStatusCode.BadRequest, forged.StatusCode);
        // An attribute cursor is not a plate cursor, nor an ordinary one.
        using (var ordinary = await client.GetAsync($"/api/tracks?limit=1&cursor={escaped}"))
            Assert.Equal(HttpStatusCode.BadRequest, ordinary.StatusCode);
    }

    [Theory]
    [InlineData($"attribute={Lower}:purple")]
    [InlineData("attribute=not-in-schema:dark")]
    [InlineData($"attribute={Lower}:dark&attribute=fixture-vehicle-body:dark")]
    [InlineData($"attribute={Lower}:dark&objectClass=Vehicle")]
    [InlineData($"attribute={Lower}:dark&attribute={Lower}:light")]
    [InlineData($"attribute={Lower}")]
    [InlineData($"attribute={Lower}:Dark")]
    [InlineData($"attribute={Lower}:dark&plateText=AB123")]
    [InlineData($"attribute={Lower}:dark&attribute={Upper}:dark&attribute=a:b&attribute=c:d&attribute=e:f")]
    public async Task AnAttributePredicateOutsideTheGrammarOrTheBoundSchemaIsRefused(string query)
    {
        var world = await PublishedWorldAsync();
        await using var owned = world.Host;

        using var response = await world.Host.Client.GetAsync("/api/tracks?" + query);

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task TheTrackDetailStatesObservedUnknownAndUnavailableWithProvenance()
    {
        var world = await PublishedWorldAsync();
        await using var owned = world.Host;
        var client = world.Host.Client;

        var analysed = (await GetJsonAsync(client, $"/api/tracks/{world.RunA.Track(0).TrackId}"))["attributes"]!;
        Assert.Equal("Ready", analysed["readiness"]!.GetValue<string>());
        Assert.True(analysed["developmentOnly"]!.GetValue<bool>());
        Assert.Equal("Analysed", analysed["trackOutcome"]!.GetValue<string>());
        var rows = analysed["attributes"]!.AsArray();
        Assert.Equal([Lower, Upper], rows.Select(row => row!["attributeType"]!.GetValue<string>()));
        Assert.Equal("Observed", rows[0]!["outcome"]!.GetValue<string>());
        Assert.Equal("dark", rows[0]!["value"]!.GetValue<string>());
        Assert.Equal("Unknown", rows[1]!["outcome"]!.GetValue<string>());
        Assert.Null(rows[1]!["value"]);
        Assert.Equal(world.Host.PreferredFingerprint, analysed["provenance"]!["identityFingerprint"]!.GetValue<string>());

        var unavailable = (await GetJsonAsync(client, $"/api/tracks/{world.RunA.Track(2).TrackId}"))["attributes"]!;
        Assert.Equal("Unavailable", unavailable["trackOutcome"]!.GetValue<string>());
        Assert.Equal("evidence_decode_failed", unavailable["unavailableReason"]!.GetValue<string>());
        Assert.Empty(unavailable["attributes"]!.AsArray());
    }

    [Fact]
    public async Task TheVocabularyIsTheBoundSchemaAndANotConfiguredSearchSaysSo()
    {
        var world = await PublishedWorldAsync();
        await using var owned = world.Host;

        var vocabulary = await GetJsonAsync(world.Host.Client, "/api/visual-attributes/vocabulary");
        Assert.True(vocabulary["configured"]!.GetValue<bool>());
        Assert.Equal(["fixture-person-lower", "fixture-person-upper", "fixture-vehicle-body"],
            vocabulary["attributes"]!.AsArray().Select(item => item!["attributeType"]!.GetValue<string>()));

        await world.Host.RestartNotConfiguredAsync();
        var page = await GetJsonAsync(world.Host.Client, $"/api/tracks?attribute={Lower}:dark");
        Assert.Empty(page["items"]!.AsArray());
        var coverage = page["attributeCoverage"]!;
        Assert.Null(coverage["identityFingerprint"]);
        Assert.Equal(coverage["tracksInScope"]!.GetValue<int>(), coverage["notAnalysed"]!.GetValue<int>());
        Assert.False((await GetJsonAsync(world.Host.Client, "/api/visual-attributes/vocabulary"))["configured"]!.GetValue<bool>());
    }
}
