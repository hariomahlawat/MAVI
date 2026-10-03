using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Measurement;
using Mavi.MeasurementExport;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

/// <summary>The read-only vehicle subclass measurement export (Stage 3, S3.2 plan T1).</summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class SubclassMeasurementExportTests
{
    // Success

    [Fact]
    public async Task CompletedStage3RunExportsEveryTrackWithItsSubclassStateAndVerifiedEvidence()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var output = world.NewOutputPath();

        var result = await world.ExportAsync(output);

        var jsonBytes = await File.ReadAllBytesAsync(Path.Combine(output, SubclassMeasurementExporter.ExportFileName));
        Assert.Equal(SubclassMeasurementExportWorld.Sha256(jsonBytes), result.ExportSha256);
        var document = JsonNode.Parse(jsonBytes)!.AsObject();
        Assert.Equal("vehicle-subclass-measurement-export-v1", (string?)document["schemaVersion"]);

        var run = document["processingRun"]!;
        Assert.Equal(world.RunId.ToString("D"), (string?)run["processingRunId"]);
        Assert.Equal("Completed", (string?)run["status"]);
        Assert.Equal(world.ProfileSha256, (string?)run["attestation"]!["pipelineProfileSha256"]);

        var video = document["video"]!;
        Assert.Equal("CAM-S32", (string?)video["cameraCode"]);
        Assert.Equal(SubclassMeasurementExportWorld.Sha256(world.Video.SourceBytes), (string?)video["sourceSha256"]);
        Assert.Equal(world.Video.SourceBytes.Length, (long)video["sourceSizeBytes"]!);

        var profile = document["profile"]!;
        Assert.Equal(world.ProfileSha256, (string?)profile["pipelineProfileSha256"]);
        Assert.Equal("evidence-selector-v1-two-tier", (string?)profile["evidenceSelectorVersion"]);
        Assert.Equal("quality-v2", (string?)profile["evidenceScorerVersion"]);

        var tracks = document["tracks"]!.AsArray();
        Assert.Equal(world.Tracks.Select(x => x.LocalTrackNumber), tracks.Select(x => (int)x!["localTrackNumber"]!));
        var source = VehicleSubclass.DetectorNativeSourcePrefix + world.ProfileSha256;
        foreach (var (exported, seeded) in tracks.Zip(world.Tracks))
        {
            Assert.Equal(seeded.TrackId.ToString("D"), (string?)exported!["id"]);
            Assert.Equal(seeded.ObjectClass.ToString(), (string?)exported["objectClass"]);
            Assert.Equal(seeded.Subclass, (string?)exported["objectSubclass"]);
            if (seeded.ObjectClass == ObjectClass.Vehicle)
            {
                Assert.Equal(VehicleSubclass.VocabularyV1, (string?)exported["objectSubclassVocabulary"]);
                Assert.Equal(source, (string?)exported["objectSubclassSource"]);
            }
            else
            {
                Assert.Null(exported["objectSubclassVocabulary"]);
                Assert.Null(exported["objectSubclassSource"]);
            }

            var observations = exported["observations"]!.AsArray();
            Assert.Equal(seeded.ObservationIds.Count, observations.Count);
            Assert.Equal(Enumerable.Range(0, observations.Count), observations.Select(x => (int)x!["evidenceRank"]!));
            Assert.Equal("Representative", (string?)observations[0]!["evidenceRole"]);
            Assert.Equal((long)observations[0]!["videoOffsetMs"]!, (long)exported["representative"]!["videoOffsetMs"]!);
            Assert.True(JsonNode.DeepEquals(observations[0]!["boundingBox"], exported["representative"]!["boundingBox"]));
            Assert.NotNull(exported["trajectorySha256"]);
            foreach (var observation in observations)
            {
                var sha = (string)observation!["evidenceSha256"]!;
                var path = (string)observation["evidencePath"]!;
                Assert.Equal($"evidence/{sha}.jpg", path);
                Assert.NotNull(observation["qualityScore"]);
                var bytes = await File.ReadAllBytesAsync(Path.Combine(output, path.Replace('/', Path.DirectorySeparatorChar)));
                Assert.Equal(sha, SubclassMeasurementExportWorld.Sha256(bytes));
                Assert.Equal(bytes.Length, (long)observation["evidenceSizeBytes"]!);
            }
        }

        // Every resolved v1 value, an abstention and a Person are all present.
        Assert.Equal(
            new string?[] { "car", "truck", "bus", "motorcycle", null, null },
            tracks.Select(x => (string?)x!["objectSubclass"]).ToArray());
        Assert.Equal(result.EvidenceFileCount, Directory.GetFiles(Path.Combine(output, "evidence")).Length);
        Assert.Equal(
            new[] { SubclassMeasurementExporter.ExportFileName },
            Directory.GetFiles(output).Select(Path.GetFileName).ToArray());
    }

    [Fact]
    public async Task ExportJsonIsCanonicalAndRepeatsByteForByte()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var first = world.NewOutputPath("first");
        var second = world.NewOutputPath("second");

        var a = await world.ExportAsync(first);
        var b = await world.ExportAsync(second);

        var firstBytes = await File.ReadAllBytesAsync(Path.Combine(first, SubclassMeasurementExporter.ExportFileName));
        var secondBytes = await File.ReadAllBytesAsync(Path.Combine(second, SubclassMeasurementExporter.ExportFileName));
        Assert.Equal(firstBytes, secondBytes);
        Assert.Equal(a.ExportSha256, b.ExportSha256);
        Assert.Equal(EvidenceListing(first), EvidenceListing(second));

        // Canonical: no BOM, no insignificant whitespace, sorted members at every depth.
        Assert.NotEqual(0xEF, firstBytes[0]);
        var text = Encoding.UTF8.GetString(firstBytes);
        Assert.DoesNotContain('\n', text);
        Assert.DoesNotContain("\": ", text, StringComparison.Ordinal);
        AssertMembersSorted(JsonNode.Parse(firstBytes)!);
        Assert.DoesNotContain("\\u002B", text, StringComparison.Ordinal);
    }

    [Fact]
    public async Task EmbeddedAttestationIsTheAttestationEndpointResponse()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var output = world.NewOutputPath();
        await world.ExportAsync(output);

        using var client = world.Factory.CreateClient();
        var endpoint = JsonNode.Parse(await client.GetStringAsync($"/api/processing/runs/{world.RunId}/attestation"));
        var exported = JsonNode.Parse(await File.ReadAllBytesAsync(Path.Combine(output, SubclassMeasurementExporter.ExportFileName)))!;

        Assert.True(JsonNode.DeepEquals(endpoint, exported["processingRun"]!["attestation"]));
        Assert.Equal("detector", (string?)exported["processingRun"]!["attestation"]!["capabilityId"]);
    }

    [Fact]
    public async Task OnlyTheRequestedRunIsExported()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var otherRunId = await world.AddOtherCompletedRunAsync();
        var output = world.NewOutputPath();

        await world.ExportAsync(output);

        var document = JsonNode.Parse(await File.ReadAllBytesAsync(Path.Combine(output, SubclassMeasurementExporter.ExportFileName)))!;
        Assert.Equal(world.Tracks.Count, document["tracks"]!.AsArray().Count);
        Assert.DoesNotContain(otherRunId.ToString("D"), document.ToJsonString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task ExportShapeAgreesWithTheContractExample()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var output = world.NewOutputPath();
        await world.ExportAsync(output);

        var exported = JsonNode.Parse(await File.ReadAllBytesAsync(Path.Combine(output, SubclassMeasurementExporter.ExportFileName)))!;
        var example = JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(
            SubclassMeasurementExportWorld.FindRepositoryRoot(), "contracts", "examples", "vehicle-subclass-measurement-export-v1.example.json")))!;

        Assert.Equal(Keys(example), Keys(exported));
        Assert.Equal(Keys(example["processingRun"]!), Keys(exported["processingRun"]!));
        Assert.Equal(Keys(example["processingRun"]!["attestation"]!), Keys(exported["processingRun"]!["attestation"]!));
        Assert.Equal(Keys(example["video"]!), Keys(exported["video"]!));
        Assert.Equal(Keys(example["profile"]!), Keys(exported["profile"]!));
        Assert.Equal(Keys(example["tracks"]![0]!), Keys(exported["tracks"]![0]!));
        Assert.Equal(Keys(example["tracks"]![0]!["observations"]![0]!), Keys(exported["tracks"]![0]!["observations"]![0]!));
        Assert.Equal(Keys(example["tracks"]![0]!["representative"]!), Keys(exported["tracks"]![0]!["representative"]!));
    }

    [Fact]
    public async Task SnapshotIsOneReadOnlyRepeatableReadTransaction()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        string? isolation = null;
        string? readOnly = null;
        using var scope = world.Factory.Services.CreateScope();
        var exporter = SubclassMeasurementExportWorld.CreateExporter(scope, async (db, cancellationToken) =>
        {
            // Observed after every read, inside the exporter's own transaction.
            isolation = await db.Database
                .SqlQueryRaw<string>("SELECT current_setting('transaction_isolation') AS \"Value\"")
                .SingleAsync(cancellationToken);
            readOnly = await db.Database
                .SqlQueryRaw<string>("SELECT current_setting('transaction_read_only') AS \"Value\"")
                .SingleAsync(cancellationToken);
        });

        await exporter.ExportAsync(world.RunId, world.ProfilePath, CancellationToken.None);

        Assert.Equal("repeatable read", isolation);
        Assert.Equal("on", readOnly);
    }

    // Run and job state

    [Fact]
    public async Task RunStillFinalizingIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync(completeRun: false, finalizeJob: true);
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.RunNotTerminal);
    }

    [Fact]
    public async Task RunThatHasNotCompletedIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync(completeRun: false);
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.RunNotTerminal);
    }

    [Fact]
    public async Task CompletedRunWhoseJobHasNotCompletedIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync(completeJob: false);
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.RunNotTerminal);
    }

    [Fact]
    public async Task UnknownRunIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.RunNotFound, runId: Guid.NewGuid());
    }

    [Fact]
    public async Task MalformedPersistedProvenanceIsAnAttestationIntegrityRefusal()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync(provenanceJson: "{}");
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.AttestationIntegrity);
    }

    // Pipeline profile

    [Fact]
    public async Task ValidProfileThatIsNotTheAttestedOneIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var other = Path.Combine(world.Scratch, "other-profile.json");
        var bytes = SubclassMeasurementExportWorld.ShippedProfileBytes().Concat("\n"u8.ToArray()).ToArray();
        await File.WriteAllBytesAsync(other, bytes);

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.PipelineProfileMismatch, profilePath: other);
    }

    [Fact]
    public async Task MissingProfileFileIsInvalid()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        await AssertRefusedAsync(
            world,
            SubclassMeasurementExportCodes.PipelineProfileInvalid,
            profilePath: Path.Combine(world.Scratch, "absent.json"));
    }

    [Fact]
    public async Task MalformedProfileWhoseBytesAreTheAttestedOnesIsInvalid()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync(profileBytes: "{\"evidence\": "u8.ToArray());
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.PipelineProfileInvalid);
    }

    [Fact]
    public async Task AttestedProfileWithoutEvidenceVersionsIsInvalid()
    {
        var bytes = MutateShippedProfile(profile => profile["evidence"]!.AsObject().Remove("scorerVersion"));
        using var world = await SubclassMeasurementExportWorld.CreateAsync(profileBytes: bytes);
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.PipelineProfileInvalid);
    }

    [Fact]
    public async Task AttestedProfileWithAnotherSubclassVocabularyIsInvalid()
    {
        var bytes = MutateShippedProfile(profile => profile["vehicleSubclass"]!["vocabularyId"] = "mavi-vehicle-subclass-v2");
        using var world = await SubclassMeasurementExportWorld.CreateAsync(profileBytes: bytes);
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.PipelineProfileInvalid);
    }

    [Fact]
    public async Task AttestedProfileWithoutTheVehicleSubclassBlockIsNotStage3()
    {
        var bytes = MutateShippedProfile(profile => profile.Remove("vehicleSubclass"));
        using var world = await SubclassMeasurementExportWorld.CreateAsync(profileBytes: bytes);
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.ProfileNotStage3);
    }

    // Linkage and subclass state

    [Fact]
    public async Task TrackRepointedToAnotherRunIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var otherRunId = await world.AddOtherCompletedRunAsync();
        await world.ExecuteSqlAsync($"UPDATE tracks SET processing_run_id = {otherRunId} WHERE id = {world.Tracks[1].TrackId}");

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.TrackRunMismatch);
        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.TrackRunMismatch, runId: otherRunId);
    }

    [Fact]
    public async Task TrackMovedToAnotherVideoIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var otherVideo = await Task14TestData.SeedBaseVideoAsync(world.Factory, "CAM-S32-OTHER");
        await world.ExecuteSqlAsync($"UPDATE tracks SET video_asset_id = {otherVideo.VideoId} WHERE id = {world.Tracks[3].TrackId}");

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.TrackRunMismatch);
    }

    [Fact]
    public async Task RepresentativePointerToAnotherTracksObservationIsAnOrphan()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        await world.ExecuteSqlAsync(
            $"UPDATE tracks SET representative_observation_id = {world.Tracks[1].ObservationIds[0]} WHERE id = {world.Tracks[0].TrackId}");

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.ObservationOrphan);
    }

    [Fact]
    public async Task VehicleSourceNamingAnotherProfileIsAnInvalidSubclassState()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var foreign = VehicleSubclass.DetectorNativeSourcePrefix + new string('f', 64);
        await world.ExecuteSqlAsync($"UPDATE tracks SET object_subclass_source = {foreign} WHERE id = {world.Tracks[2].TrackId}");

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.SubclassStateInvalid);
    }

    [Fact]
    public async Task VehicleWithoutSubclassDataInAStage3RunIsAnInvalidSubclassState()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        await world.ExecuteSqlAsync(
            $"UPDATE tracks SET object_subclass = NULL, object_subclass_vocabulary = NULL, object_subclass_source = NULL WHERE id = {world.Tracks[0].TrackId}");

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.SubclassStateInvalid);
    }

    [Fact]
    public async Task MalformedSubclassRowBehindDroppedConstraintsIsAnInvalidSubclassState()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        // Only in this test database: remove the guards so the exporter meets a row the schema forbids.
        await world.ExecuteRawSqlAsync(
            "ALTER TABLE tracks DROP CONSTRAINT ck_tracks_object_subclass_state, " +
            "DROP CONSTRAINT ck_tracks_object_subclass_value, DROP CONSTRAINT ck_tracks_object_subclass_identity");
        var person = world.Tracks.Single(x => x.ObjectClass == ObjectClass.Person);
        await world.ExecuteSqlAsync($"UPDATE tracks SET object_subclass = 'car' WHERE id = {person.TrackId}");

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.SubclassStateInvalid);
    }

    // Bytes

    [Fact]
    public async Task TamperedEvidenceFileIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var path = world.EvidencePath(world.Tracks[3].CropStorageKeys[1]);
        var bytes = await File.ReadAllBytesAsync(path);
        bytes[0] ^= 0xFF;
        await File.WriteAllBytesAsync(path, bytes);

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.EvidenceChanged);
    }

    [Fact]
    public async Task MissingEvidenceFileIsIncompleteProvenance()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        File.Delete(world.EvidencePath(world.Tracks[0].CropStorageKeys[2]));

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.ProvenanceIncomplete);
    }

    [Fact]
    public async Task ChangedSourceVideoIsRefused()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var bytes = await File.ReadAllBytesAsync(world.SourcePath());
        bytes[^1] ^= 0x01;
        await File.WriteAllBytesAsync(world.SourcePath(), bytes);

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.SourceChanged);
    }

    [Fact]
    public async Task MissingSourceVideoIsIncompleteProvenance()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        File.Delete(world.SourcePath());

        await AssertRefusedAsync(world, SubclassMeasurementExportCodes.ProvenanceIncomplete);
    }

    // Output

    [Fact]
    public async Task ExistingOutputIsNeverOverwritten()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var output = world.NewOutputPath();
        Directory.CreateDirectory(output);
        var marker = Path.Combine(output, "keep.txt");
        await File.WriteAllTextAsync(marker, "operator data");

        var refusal = await Assert.ThrowsAsync<SubclassMeasurementExportException>(() => world.ExportAsync(output));

        Assert.Equal(SubclassMeasurementExportCodes.OutputExists, refusal.Code);
        Assert.Equal(new[] { marker }, Directory.GetFileSystemEntries(output));
        Assert.Equal("operator data", await File.ReadAllTextAsync(marker));
    }

    // Command line

    [Fact]
    public async Task CommandWritesTheExportAndReportsItsIdentity()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        var output = world.NewOutputPath();
        using var stdout = new StringWriter();
        using var stderr = new StringWriter();

        var exitCode = await MeasurementExportCommand.RunAsync(
            ["--run", world.RunId.ToString("D"), "--pipeline-profile", world.ProfilePath, "--out", output],
            Configuration(world),
            stdout,
            stderr,
            CancellationToken.None);

        Assert.Equal(MeasurementExportCommand.Success, exitCode);
        var sha = SubclassMeasurementExportWorld.Sha256(await File.ReadAllBytesAsync(Path.Combine(output, SubclassMeasurementExporter.ExportFileName)));
        Assert.Contains($"exportSha256 {sha}", stdout.ToString(), StringComparison.Ordinal);
        Assert.Equal(string.Empty, stderr.ToString());
    }

    [Fact]
    public async Task CommandRefusalExitsTwoAndLeavesNoOutput()
    {
        using var world = await SubclassMeasurementExportWorld.CreateAsync();
        File.Delete(world.EvidencePath(world.Tracks[4].CropStorageKeys[0]));
        var output = world.NewOutputPath();
        using var stdout = new StringWriter();
        using var stderr = new StringWriter();

        var exitCode = await MeasurementExportCommand.RunAsync(
            ["--run", world.RunId.ToString("D"), "--pipeline-profile", world.ProfilePath, "--out", output],
            Configuration(world),
            stdout,
            stderr,
            CancellationToken.None);

        Assert.Equal(MeasurementExportCommand.Refused, exitCode);
        Assert.Contains(SubclassMeasurementExportCodes.ProvenanceIncomplete, stderr.ToString(), StringComparison.Ordinal);
        Assert.False(Directory.Exists(output));
        Assert.Empty(Directory.GetDirectories(world.Scratch, ".*partial*"));
    }

    [Theory]
    [InlineData]
    [InlineData("--run", "not-a-guid", "--pipeline-profile", "p.json", "--out", "o")]
    [InlineData("--run", "00000000-0000-0000-0000-000000000000", "--pipeline-profile", "p.json", "--out", "o")]
    [InlineData("--run", "0199a1b2-0000-7000-8000-000000000001", "--pipeline-profile", "p.json", "--output", "o")]
    [InlineData("--run", "0199a1b2-0000-7000-8000-000000000001", "--run", "0199a1b2-0000-7000-8000-000000000001", "--out", "o")]
    public async Task CommandRejectsInvalidUsage(params string[] args)
    {
        using var stdout = new StringWriter();
        using var stderr = new StringWriter();

        var exitCode = await MeasurementExportCommand.RunAsync(
            args, new ConfigurationBuilder().Build(), stdout, stderr, CancellationToken.None);

        Assert.Equal(MeasurementExportCommand.Refused, exitCode);
        Assert.Contains(MeasurementExportCommand.UsageInvalid, stderr.ToString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task CommandWithoutAConnectionStringIsAConfigurationRefusal()
    {
        using var stdout = new StringWriter();
        using var stderr = new StringWriter();

        var exitCode = await MeasurementExportCommand.RunAsync(
            ["--run", Guid.NewGuid().ToString("D"), "--pipeline-profile", "p.json", "--out", "o"],
            new ConfigurationBuilder().Build(),
            stdout,
            stderr,
            CancellationToken.None);

        Assert.Equal(MeasurementExportCommand.Refused, exitCode);
        Assert.Contains(MeasurementExportCommand.ConfigurationInvalid, stderr.ToString(), StringComparison.Ordinal);
    }

    // Helpers

    private static async Task AssertRefusedAsync(
        SubclassMeasurementExportWorld world,
        string code,
        Guid? runId = null,
        string? profilePath = null)
    {
        var output = world.NewOutputPath();
        var refusal = await Assert.ThrowsAsync<SubclassMeasurementExportException>(
            () => world.ExportAsync(output, runId, profilePath));
        Assert.Equal(code, refusal.Code);
        Assert.False(Directory.Exists(output), "No output may survive a refusal.");
        Assert.Empty(Directory.GetDirectories(world.Scratch, ".*partial*"));
    }

    private static IConfiguration Configuration(SubclassMeasurementExportWorld world) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["ConnectionStrings:Mavi"] = world.Factory.ConnectionString,
                ["MediaStorage:RootPath"] = world.Factory.MediaRoot,
                ["MediaStorage:EvidenceRootPath"] = world.Factory.EvidenceRoot,
            })
            .Build();

    private static byte[] MutateShippedProfile(Action<JsonObject> mutate)
    {
        var profile = JsonNode.Parse(SubclassMeasurementExportWorld.ShippedProfileBytes())!.AsObject();
        mutate(profile);
        return JsonSerializer.SerializeToUtf8Bytes(profile);
    }

    private static string[] EvidenceListing(string output) =>
        Directory.GetFiles(Path.Combine(output, "evidence"))
            .Select(path => $"{Path.GetFileName(path)}:{Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)))}")
            .Order(StringComparer.Ordinal)
            .ToArray();

    private static string[] Keys(JsonNode node) =>
        node.AsObject().Select(member => member.Key).Order(StringComparer.Ordinal).ToArray();

    private static void AssertMembersSorted(JsonNode node)
    {
        switch (node)
        {
            case JsonObject value:
                var keys = value.Select(member => member.Key).ToArray();
                Assert.Equal(keys.Order(StringComparer.Ordinal), keys);
                foreach (var member in value)
                {
                    if (member.Value is not null)
                        AssertMembersSorted(member.Value);
                }

                break;
            case JsonArray value:
                foreach (var item in value)
                {
                    if (item is not null)
                        AssertMembersSorted(item);
                }

                break;
        }
    }
}
