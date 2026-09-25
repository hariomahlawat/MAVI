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

    private FinalizationWorld(ApiTestFactory factory, MutableTimeProvider clock, VisionFinalizationSubmissionApiTests.CapturingLoggerProvider logs, SqlTrace sql, ControllableSealer sealer)
    {
        Factory = factory;
        Clock = clock;
        Logs = logs;
        Sql = sql;
        Sealer = sealer;
    }

    public ApiTestFactory Factory { get; }
    public MutableTimeProvider Clock { get; }
    public VisionFinalizationSubmissionApiTests.CapturingLoggerProvider Logs { get; }
    public SqlTrace Sql { get; }

    /// <summary>The real accepted-evidence store behind a decorator that counts, faults and traps deletion.</summary>
    public ControllableSealer Sealer { get; }

    /// <summary>Claim 5 min, extension 5 min, 3 attempts, 6 h deadline, batches of 200.</summary>
    public VisionFinalizationPolicy Policy { get; init; } =
        new(TimeSpan.FromMinutes(5), TimeSpan.FromMinutes(5), 3, TimeSpan.FromHours(6), 200);

    public static async Task<FinalizationWorld> CreateAsync(
        Action<IServiceCollection>? overrideServices = null,
        Action<DbContextOptionsBuilder>? configureDbContext = null,
        VisionFinalizationOptions? options = null,
        bool enableHost = false,
        DateTimeOffset? now = null,
        FinalizationWorld? sharedWith = null,
        MutableTimeProvider? clockOverride = null)
    {
        var clock = clockOverride ?? sharedWith?.Clock ?? new MutableTimeProvider(now ?? Start);
        var logs = new VisionFinalizationSubmissionApiTests.CapturingLoggerProvider();
        var sql = new SqlTrace();
        var sealer = new ControllableSealer();
        var factory = new ApiTestFactory
        {
            Clock = clock,
            EnableAsynchronousFinalization = options?.Enabled ?? true,
            EnableVisionFinalizationHost = enableHost,
            MediaRootOverride = sharedWith?.Factory.MediaRoot,
            EvidenceRootOverride = sharedWith?.Factory.EvidenceRoot,
            ConfigureDbContext = builder =>
            {
                builder.AddInterceptors(sql);
                configureDbContext?.Invoke(builder);
            },
            OverrideServices = services =>
            {
                services.AddSingleton<ILoggerProvider>(logs);
                services.RemoveAll<IAcceptedEvidenceStore>();
                services.AddSingleton<IAcceptedEvidenceStore>(provider =>
                {
                    sealer.Inner = new Mavi.Infrastructure.Storage.AcceptedEvidenceStore(
                        provider.GetRequiredService<IMediaStore>(),
                        provider.GetRequiredService<IOptions<Mavi.Infrastructure.Storage.MediaStorageOptions>>());
                    return sealer;
                });
                if (options is not null)
                {
                    services.RemoveAll<IOptions<VisionFinalizationOptions>>();
                    services.AddSingleton(Options.Create(options));
                }
                overrideServices?.Invoke(services);
            },
        };
        // A second host over the same database, staging and evidence roots shares the world
        // (two API hosts, or a restart); it never resets what the first one wrote.
        if (sharedWith is null)
            await factory.ResetAndMigrateAsync();
        return new FinalizationWorld(factory, clock, logs, sql, sealer);
    }

    // -- hand-off -----------------------------------------------------------------------------

    public sealed record HandOff(HttpClient Client, VisionJobLeaseContract Lease, VisionJobCompleteRequest Request, VisionJobFinalizationResponse Ack);

    /// <summary>Seeds a video, leases it, stages one Track's evidence and posts the 3.1 hand-off.</summary>
    public Task<HandOff> HandOffAsync(string workerId = "gpu-sdd-01", string[]? roles = null, string cameraCode = "CAM-COMPLETE") =>
        HandOffAsync(lease => VisionFinalizationSubmissionApiTests.BuildRequestAsync(Factory, lease, roles ?? AllRoles), workerId, cameraCode);

    /// <summary>Seeds a video, leases it, builds the body for that lease and posts the 3.1 hand-off.</summary>
    public async Task<HandOff> HandOffAsync(Func<VisionJobLeaseContract, Task<VisionJobCompleteRequest>> build, string workerId = "gpu-sdd-01", string cameraCode = "CAM-COMPLETE")
    {
        var videoId = await SeedVideoAsync(cameraCode);
        var client = Factory.CreateClient();
        (await client.PostAsync($"/api/videos/{videoId}/process", null)).EnsureSuccessStatusCode();
        var lease = await VisionResultCompletionApiTests.LeaseAsync(client, workerId);
        var request = await build(lease);
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

    /// <summary>A host instance wired as the application wires it, whose cycles a test drives by hand.</summary>
    public Mavi.Api.Finalization.VisionFinalizationHostedService Host() => new(
        Factory.Services.GetRequiredService<IServiceScopeFactory>(),
        Factory.Services.GetRequiredService<IOptions<VisionFinalizationOptions>>(),
        Factory.Services.GetRequiredService<Mavi.Infrastructure.Finalization.VisionFinalizationExecutor>(),
        Factory.Services.GetRequiredService<Mavi.Infrastructure.Finalization.VisionFinalizationState>(),
        Clock,
        Factory.Services.GetRequiredService<ILogger<Mavi.Api.Finalization.VisionFinalizationHostedService>>());

    public async Task<System.Text.Json.JsonElement> HealthAsync()
    {
        using var client = Factory.CreateClient();
        using var document = System.Text.Json.JsonDocument.Parse(await client.GetStringAsync("/api/health"));
        return document.RootElement.GetProperty("details").GetProperty("visionFinalization").Clone();
    }

    /// <summary>Waits, bounded, for a condition a background loop satisfies; never a bare sleep-then-assert.</summary>
    public static async Task WaitUntilAsync(Func<Task<bool>> condition, TimeSpan? timeout = null)
    {
        var deadline = DateTime.UtcNow + (timeout ?? TimeSpan.FromSeconds(30));
        while (!await condition())
        {
            if (DateTime.UtcNow > deadline)
                throw new TimeoutException("The background host did not reach the expected state in time.");
            await Task.Delay(50);
        }
    }

    public void Dispose() => Factory.Dispose();

    /// <summary>
    /// Wraps the real store. Any deletion is a test failure, not a no-op: the finalizer must
    /// never compensate by deleting accepted evidence (ADR-006 §7). Faults and hooks let a test
    /// inject a transient IO error, rotate the clock or a claim between objects, or block.
    /// </summary>
    internal sealed class ControllableSealer : IAcceptedEvidenceStore
    {
        private int _seals;
        private int _deletes;

        public IAcceptedEvidenceStore Inner { get; set; } = null!;
        public int Seals => _seals;
        public int Deletes => _deletes;

        /// <summary>Throws an IOException on the given one-based seal call, once.</summary>
        public int? ThrowIoOnSeal { get; set; }

        /// <summary>Runs before each seal with the one-based call number.</summary>
        public Func<int, Task>? BeforeSeal { get; set; }

        public async Task<AcceptedEvidenceSealResult> SealAsync(string sourceStorageKey, string acceptedStorageKey, long expectedSizeBytes, string expectedSha256, CancellationToken cancellationToken)
        {
            var call = Interlocked.Increment(ref _seals);
            if (BeforeSeal is { } hook)
                await hook(call);
            if (ThrowIoOnSeal == call)
            {
                ThrowIoOnSeal = null;
                throw new IOException("injected transient IO failure at /this/path/must/never/be/logged");
            }

            return await Inner.SealAsync(sourceStorageKey, acceptedStorageKey, expectedSizeBytes, expectedSha256, cancellationToken);
        }

        public Task DeleteAcceptedAsync(string acceptedStorageKey, CancellationToken cancellationToken)
        {
            Interlocked.Increment(ref _deletes);
            throw new InvalidOperationException("The asynchronous finalization path must never delete accepted evidence.");
        }
    }

    /// <summary>Throws a database transient once, on the next command whose text contains the armed fragment.</summary>
    internal sealed class DatabaseFault : DbCommandInterceptor
    {
        private volatile string? _fragment;

        /// <summary>Whether the armed fault has fired (once).</summary>
        public bool Tripped { get; private set; }

        public void ArmOnCommandContaining(string fragment)
        {
            Tripped = false;
            _fragment = fragment;
        }

        public override ValueTask<InterceptionResult<DbDataReader>> ReaderExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<DbDataReader> result, CancellationToken cancellationToken = default)
        {
            Trip(command);
            return base.ReaderExecutingAsync(command, eventData, result, cancellationToken);
        }

        public override ValueTask<InterceptionResult<int>> NonQueryExecutingAsync(DbCommand command, CommandEventData eventData, InterceptionResult<int> result, CancellationToken cancellationToken = default)
        {
            Trip(command);
            return base.NonQueryExecutingAsync(command, eventData, result, cancellationToken);
        }

        private void Trip(DbCommand command)
        {
            if (_fragment is { } fragment && command.CommandText.Contains(fragment, StringComparison.Ordinal))
            {
                _fragment = null;
                Tripped = true;
                throw new NpgsqlException("Injected database transient at /this/path/must/never/be/logged");
            }
        }
    }

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
