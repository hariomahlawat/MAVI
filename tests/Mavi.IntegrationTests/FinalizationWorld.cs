using System.Collections.Concurrent;
using System.Data.Common;
using System.Net;
using System.Net.Http.Json;
using System.Security.Cryptography;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Worker;
using Mavi.Domain.Media;
using Mavi.Domain.Processing;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Npgsql;

namespace Mavi.IntegrationTests;

/// <summary>
/// The F3 test world: an API host with the activation gate on, a controllable clock, captured
/// logs, an optional SQL capture, and the hand-off/claim/prepare helpers every finalizer suite
/// needs. The hosted finalizer is off unless a test turns it on; tests drive the lifecycle,
/// executor or one host cycle deliberately.
/// </summary>
internal sealed class FinalizationWorld : IDisposable
{
    public static readonly DateTimeOffset Start = new(2026, 9, 25, 8, 0, 0, TimeSpan.Zero);
    public static readonly string[] AllRoles = ["representative", "near-view", "early-diverse", "late-diverse"];

    private FinalizationWorld(ApiTestFactory factory, MutableTimeProvider clock, VisionFinalizationSubmissionApiTests.CapturingLoggerProvider logs, SqlTrace sql)
    {
        Factory = factory;
        Clock = clock;
        Logs = logs;
        Sql = sql;
    }

    public ApiTestFactory Factory { get; }
    public MutableTimeProvider Clock { get; }
    public VisionFinalizationSubmissionApiTests.CapturingLoggerProvider Logs { get; }
    public SqlTrace Sql { get; }

    /// <summary>Claim 5 min, extension 5 min, 3 attempts, 6 h deadline, batches of 200.</summary>
    public VisionFinalizationPolicy Policy { get; init; } =
        new(TimeSpan.FromMinutes(5), TimeSpan.FromMinutes(5), 3, TimeSpan.FromHours(6), 200);

    public static async Task<FinalizationWorld> CreateAsync(
        Action<IServiceCollection>? overrideServices = null,
        Action<DbContextOptionsBuilder>? configureDbContext = null,
        VisionFinalizationOptions? options = null,
        bool enableHost = false,
        DateTimeOffset? now = null)
    {
        var clock = new MutableTimeProvider(now ?? Start);
        var logs = new VisionFinalizationSubmissionApiTests.CapturingLoggerProvider();
        var sql = new SqlTrace();
        var factory = new ApiTestFactory
        {
            Clock = clock,
            EnableAsynchronousFinalization = options?.Enabled ?? true,
            EnableVisionFinalizationHost = enableHost,
            ConfigureDbContext = builder =>
            {
                builder.AddInterceptors(sql);
                configureDbContext?.Invoke(builder);
            },
            OverrideServices = services =>
            {
                services.AddSingleton<ILoggerProvider>(logs);
                if (options is not null)
                {
                    services.RemoveAll<IOptions<VisionFinalizationOptions>>();
                    services.AddSingleton(Options.Create(options));
                }
                overrideServices?.Invoke(services);
            },
        };
        await factory.ResetAndMigrateAsync();
        return new FinalizationWorld(factory, clock, logs, sql);
    }

    // -- hand-off -----------------------------------------------------------------------------

    public sealed record HandOff(HttpClient Client, VisionJobLeaseContract Lease, VisionJobCompleteRequest Request, VisionJobFinalizationResponse Ack);

    /// <summary>Seeds a video, leases it, stages one Track's evidence and posts the 3.1 hand-off.</summary>
    public async Task<HandOff> HandOffAsync(string workerId = "gpu-sdd-01", string[]? roles = null, string cameraCode = "CAM-COMPLETE")
    {
        var videoId = await SeedVideoAsync(cameraCode);
        var client = Factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, workerId);
        var request = await VisionFinalizationSubmissionApiTests.BuildRequestAsync(Factory, lease, roles ?? AllRoles);
        using var response = await client.PostAsJsonAsync($"/api/vision/jobs/{lease.JobId}/complete", request);
        var body = await response.Content.ReadAsStringAsync();
        Assert.True(response.StatusCode == HttpStatusCode.OK, body);
        var ack = (await response.Content.ReadFromJsonAsync<VisionJobFinalizationResponse>())!;
        Assert.Equal("finalizing", ack.State);
        return new HandOff(client, lease, request, ack);
    }

    private async Task<Guid> SeedVideoAsync(string cameraCode)
    {
        using var scope = Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var camera = Mavi.Domain.Cameras.Camera.Create(cameraCode, "Completion", "UTC", Start);
        var sourceId = Guid.CreateVersion7();
        var sourceSha = Convert.ToHexStringLower(SHA256.HashData(sourceId.ToByteArray()));
        var source = Artifact.Create(ArtifactType.SourceVideo, $"source/{sourceId}.mp4", "video/mp4", 100, sourceSha, createdAtUtc: Start);
        var video = VideoAsset.Create(camera.Id, source.Id, "source.mp4", Start, 60_000, 25, 1, 1920, 1080, "h264", TimestampSource.Manual, 1, importedAtUtc: Start);
        db.AddRange(camera, source, video);
        await db.SaveChangesAsync();
        return video.Id;
    }

    // -- lifecycle ----------------------------------------------------------------------------

    public async Task<T> WithLifecycleAsync<T>(Func<IVisionFinalizationLifecycle, Task<T>> action)
    {
        await using var scope = Factory.Services.CreateAsyncScope();
        return await action(scope.ServiceProvider.GetRequiredService<IVisionFinalizationLifecycle>());
    }

    public Task<VisionFinalizationClaim?> ClaimAsync(VisionFinalizationPolicy? policy = null) =>
        WithLifecycleAsync(lifecycle => lifecycle.ClaimNextAsync(policy ?? Policy, CancellationToken.None));

    /// <summary>Loads, decodes, validates, seals every object and builds the graph: the executor's work, done plainly.</summary>
    public async Task<(ValidatedVisionResult Result, FinalizationGraphPlan Graph)> PrepareAsync(VisionFinalizationClaim claim)
    {
        var inputs = (await WithLifecycleAsync(l => l.LoadInputsAsync(claim, CancellationToken.None)))!;
        var request = VisionFinalizationPayloadCodec.Decode(inputs.Payload!.Payload);
        var result = Factory.Services.GetRequiredService<VisionResultValidator>().Validate(claim.JobId, request, inputs.VideoDurationMs);
        var sealer = Factory.Services.GetRequiredService<IAcceptedEvidenceStore>();
        var accepted = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var unit in EvidenceSealingPlan.Build(claim.JobId, result))
        {
            var sealedResult = await sealer.SealAsync(unit.SourceStorageKey, unit.AcceptedStorageKey, unit.ExpectedSizeBytes, unit.ExpectedSha256, CancellationToken.None);
            Assert.Equal(AcceptedEvidenceSealStatus.Sealed, sealedResult.Status);
            accepted[unit.SourceStorageKey] = sealedResult.StorageKey!;
        }

        var graph = FinalizationGraphBuilder.Build(result, accepted, claim.ProcessingRunId, claim.VideoAssetId, inputs.RecordingStartUtc, Clock.GetUtcNow());
        return (result, graph);
    }

    // -- database -----------------------------------------------------------------------------

    public async Task<VisionJob> JobAsync(Guid jobId)
    {
        using var scope = Factory.Services.CreateScope();
        return await scope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionJobs.AsNoTracking().SingleAsync(x => x.Id == jobId);
    }

    public async Task<(VisionJob Job, ProcessingRun Run, VideoAsset Video)> StateAsync(Guid jobId)
    {
        using var scope = Factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<MaviDbContext>();
        var job = await db.VisionJobs.AsNoTracking().SingleAsync(x => x.Id == jobId);
        var run = await db.ProcessingRuns.AsNoTracking().SingleAsync(x => x.Id == job.ProcessingRunId);
        var video = await db.VideoAssets.AsNoTracking().SingleAsync(x => x.Id == run.VideoAssetId);
        return (job, run, video);
    }

    public async Task<int> TrackCountAsync(Guid runId)
    {
        using var scope = Factory.Services.CreateScope();
        return await scope.ServiceProvider.GetRequiredService<MaviDbContext>().Tracks.CountAsync(x => x.ProcessingRunId == runId);
    }

    public async Task<int> PayloadCountAsync()
    {
        using var scope = Factory.Services.CreateScope();
        return await scope.ServiceProvider.GetRequiredService<MaviDbContext>().VisionFinalizationPayloads.CountAsync();
    }

    public async Task ExecuteSqlAsync(string sql, params object[] parameters)
    {
        await using var connection = new NpgsqlConnection(Factory.ConnectionString);
        await connection.OpenAsync();
        await using var command = new NpgsqlCommand(sql, connection);
        foreach (var parameter in parameters)
            command.Parameters.AddWithValue(parameter);
        await command.ExecuteNonQueryAsync();
    }

    /// <summary>Writes the ownership triple directly, as only a database edit could (the aggregate never does).</summary>
    public Task SetClaimTripleAsync(Guid jobId, byte[]? hash, DateTimeOffset? expiresAtUtc, DateTimeOffset? extendedAtUtc) =>
        ExecuteSqlAsync(
            "UPDATE vision_jobs SET finalization_claim_token_hash = $1, finalization_claim_expires_at_utc = $2, finalization_claim_extended_at_utc = $3 WHERE id = $4",
            (object?)hash ?? DBNull.Value, (object?)expiresAtUtc ?? DBNull.Value, (object?)extendedAtUtc ?? DBNull.Value, jobId);

    public Task<long> VisibilityAllocationsAsync() => VisionFinalizationSubmissionApiTests.VisibilitySequenceAllocationsAsync(Factory);

    public string[] EvidenceFiles() =>
        Directory.Exists(Factory.EvidenceRoot) ? Directory.GetFiles(Factory.EvidenceRoot, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal).ToArray() : [];

    public string StagingAttemptPath(VisionJobLeaseContract lease) =>
        Path.Combine(Factory.MediaRoot, "staging", lease.JobId.ToString("D"), $"attempt-{lease.AttemptCount:0000}");

    public static (byte[] Token, byte[] Hash) Token(byte fill)
    {
        var token = new byte[VisionJob.FinalizationClaimTokenByteLength];
        Array.Fill(token, fill);
        return (token, SHA256.HashData(token));
    }

    public string AllLogText() => string.Join('\n', Logs.Entries.Select(x => x.Message));

    public void Dispose() => Factory.Dispose();

    /// <summary>Every command text the host issued, in order; cleared by the test that reads it.</summary>
    internal sealed class SqlTrace : DbCommandInterceptor
    {
        private readonly ConcurrentQueue<string> _commands = new();

        public IReadOnlyList<string> Commands => [.. _commands];

        public void Clear() => _commands.Clear();

        public override InterceptionResult<DbDataReader> ReaderExecuting(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result)
        {
            _commands.Enqueue(command.CommandText);
            return result;
        }

        public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
        {
            _commands.Enqueue(command.CommandText);
            return ValueTask.FromResult(result);
        }

        public override ValueTask<InterceptionResult<object>> ScalarExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<object> result, CancellationToken cancellationToken = default)
        {
            _commands.Enqueue(command.CommandText);
            return ValueTask.FromResult(result);
        }

        public override ValueTask<InterceptionResult<int>> NonQueryExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
        {
            _commands.Enqueue(command.CommandText);
            return ValueTask.FromResult(result);
        }
    }
}
