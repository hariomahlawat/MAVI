using System.Net;
using System.Net.Http.Headers;
using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.VisualAttributes;
using Mavi.Application.Modules.VisualAttributes.Completion;
using Mavi.Contracts.Worker.Attributes;
using Mavi.Domain.VisualAttributes;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Mavi.Infrastructure.Persistence.Repositories;

namespace Mavi.IntegrationTests;

/// <summary>
/// Ownership over the lifetime of an operation, not only at its start (S2b plan §10, §12, §13):
/// a streamed evidence read or prediction upload stops when the attempt loses ownership, and a
/// completion that passed Phase A keeps its entitlement to Phase C through the bounded
/// publication window — the platform sweep can neither exhaust nor deadline-fail it meanwhile.
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class VisualAttributeLeaseLifetimeTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    private static readonly Dictionary<string, string?> FinalAttemptPolicy = new()
    {
        ["VisualAttributes:MaximumAttempts"] = "1",
        ["VisualAttributes:LeaseSeconds"] = "60",
        ["VisualAttributes:HeartbeatExtensionSeconds"] = "60",
    };

    private static readonly Dictionary<string, string?> ShortDeadlinePolicy = new()
    {
        ["VisualAttributes:LeaseSeconds"] = "60",
        ["VisualAttributes:HeartbeatExtensionSeconds"] = "60",
        ["VisualAttributes:MaximumAnalysisDurationSeconds"] = "90",
    };

    private async Task<VisualAttributeApiHost> HostAsync(
        IReadOnlyDictionary<string, string?>? configuration = null, Action<IServiceCollection>? services = null, bool kestrel = false)
    {
        var host = await VisualAttributeApiHost.CreateAsync(fixture, Now, configuration: configuration, services: services, kestrel: kestrel);
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        await host.World.SeedRunAsync(1, 1, 2, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        return host;
    }

    private static async Task<BuiltCompletion> StagedAsync(VisualAttributeApiHost host, LeasedUnit unit)
    {
        var completion = AttributeCompletionBuilder.Build(unit);
        using var uploaded = await host.UploadAsync(unit, completion.Predictions);
        Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
        return completion;
    }

    private static async Task<VisualAttributeCompletionResult> CompleteAsync(
        VisualAttributeApiHost host, LeasedUnit unit, BuiltCompletion completion, Func<CancellationToken, Task> beforePhaseC)
    {
        var (service, scope) = host.CompletionService(beforePhaseC);
        using (scope)
            return await service.CompleteAsync(unit.AnalysisId, unit.Capability, completion.Request, CancellationToken.None);
    }

    // --- Phase B versus the platform sweep --------------------------------------------------

    [Fact]
    public async Task TheSweepCannotExhaustAFinalAttemptWhosePublicationIsInFlight()
    {
        await using var host = await HostAsync(FinalAttemptPolicy);
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        host.World.Clock.Advance(TimeSpan.FromSeconds(10));
        VisualAttributeSweepResult? duringPhaseB = null;

        var result = await CompleteAsync(host, unit, completion, async _ =>
        {
            // Phase A passed; the seal is slow and the claim's own lease (60 s) runs out.
            host.World.Clock.Advance(TimeSpan.FromSeconds(55));
            duringPhaseB = await host.SweepAsync();
        });

        Assert.Equal(new VisualAttributeSweepResult(0, 0), duringPhaseB);
        Assert.Equal(VisualAttributeCompletionStatus.Completed, result.Status);
        Assert.Equal(VisualAttributeAnalysisStatus.Completed, await host.StatusAsync(unit.AnalysisId));
    }

    [Fact]
    public async Task TheDeadlineSweepCannotFailAPublicationValidatedBeforeTheDeadline()
    {
        await using var host = await HostAsync(ShortDeadlinePolicy);
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        host.World.Clock.Advance(TimeSpan.FromSeconds(50));
        VisualAttributeSweepResult? duringPhaseB = null;

        var result = await CompleteAsync(host, unit, completion, async _ =>
        {
            // Validated at +50 s; the 90 s deadline passes while the object is being sealed.
            host.World.Clock.Advance(TimeSpan.FromSeconds(45));
            duringPhaseB = await host.SweepAsync();
        });

        Assert.Equal(new VisualAttributeSweepResult(0, 0), duringPhaseB);
        Assert.Equal(VisualAttributeCompletionStatus.Completed, result.Status);
    }

    [Fact]
    public async Task AnAbandonedPublicationOfTheFinalAttemptIsExhaustedOnceItsWindowLapses()
    {
        await using var host = await HostAsync(FinalAttemptPolicy);
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        host.World.Clock.Advance(TimeSpan.FromSeconds(10));

        await Assert.ThrowsAsync<InvalidOperationException>(() => CompleteAsync(host, unit, completion,
            _ => throw new InvalidOperationException("platform process died in Phase B")));

        // The publication window (one lease from Phase A) still protects it...
        host.World.Clock.Advance(TimeSpan.FromSeconds(59));
        Assert.Equal(new VisualAttributeSweepResult(0, 0), await host.SweepAsync());
        Assert.Equal(VisualAttributeAnalysisStatus.Running, await host.StatusAsync(unit.AnalysisId));
        // ...and nothing longer: abandoned work is bounded.
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        Assert.Equal(new VisualAttributeSweepResult(0, 1), await host.SweepAsync());
        Assert.Equal(VisualAttributeAnalysisStatus.Failed, await host.StatusAsync(unit.AnalysisId));

        // The exact replay after that is not a publication: the unit ended.
        using var replay = await host.CompleteAsync(unit, completion.Request);
        Assert.Equal(HttpStatusCode.Conflict, replay.StatusCode);
    }

    [Fact]
    public async Task AnAbandonedPublicationPastTheDeadlineIsFailedOnceItsWindowLapses()
    {
        await using var host = await HostAsync(ShortDeadlinePolicy);
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        host.World.Clock.Advance(TimeSpan.FromSeconds(50));

        await Assert.ThrowsAsync<InvalidOperationException>(() => CompleteAsync(host, unit, completion,
            _ => throw new InvalidOperationException("platform process died in Phase B")));

        // Deadline +90 s passed, publication window (+50 s + 60 s = +110 s) not yet.
        host.World.Clock.Advance(TimeSpan.FromSeconds(59));
        Assert.Equal(new VisualAttributeSweepResult(0, 0), await host.SweepAsync());
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        Assert.Equal(new VisualAttributeSweepResult(1, 0), await host.SweepAsync());
        Assert.Equal(VisualAttributeAnalysisStatus.Failed, await host.StatusAsync(unit.AnalysisId));
    }

    [Fact]
    public async Task APublicationOutlivingItsWindowIsReclaimedAndRefusedAtPhaseC()
    {
        await using var host = await HostAsync();
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        LeasedUnit? second = null;

        var result = await CompleteAsync(host, unit, completion, async _ =>
        {
            // A Phase B slower than the whole publication window: another worker reclaims.
            host.World.Clock.Advance(TimeSpan.FromSeconds(121));
            second = await host.LeaseAsync("attributes-02");
        });

        Assert.Equal(2, second!.Attempt);
        Assert.Equal(VisualAttributeAnalysis.StaleAttemptCode, result.Code);
        Assert.Equal(VisualAttributeAnalysisStatus.Running, await host.StatusAsync(unit.AnalysisId));
    }

    [Fact]
    public async Task APublicationWithinItsWindowIsNotReclaimable()
    {
        await using var host = await HostAsync();
        var unit = await host.LeaseAsync();
        var completion = await StagedAsync(host, unit);
        host.World.Clock.Advance(TimeSpan.FromSeconds(100));
        HttpStatusCode? reclaim = null;

        var result = await CompleteAsync(host, unit, completion, async _ =>
        {
            // The claim's own lease (+120 s) runs out; the window from Phase A (+100 s) does not.
            host.World.Clock.Advance(TimeSpan.FromSeconds(30));
            using var attempt = await host.PostLeaseAsync("attributes-02");
            reclaim = attempt.StatusCode;
        });

        Assert.Equal(HttpStatusCode.NoContent, reclaim);
        Assert.Equal(VisualAttributeCompletionStatus.Completed, result.Status);
    }

    [Fact]
    public async Task APublishingUnitNeverStarvesTheDeadlineSweepOfAnAbandonedOne()
    {
        var policy = new VisualAttributeLeasePolicy(TimeSpan.FromSeconds(60), TimeSpan.FromSeconds(60), 3, TimeSpan.FromSeconds(90));
        using var world = await VisualAttributeWorld.CreateAsync(fixture, Now);
        var definition = VisualAttributeReleaseFixture.Definition();
        VisualAttributeLifecycle Lifecycle() => new(world.Read(), world.Clock, new Mavi.Infrastructure.Security.LeaseCapabilityService());
        var activated = await Lifecycle().EnsureActivationAsync(definition, CancellationToken.None);
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        await world.SeedRunAsync(1, 0, 1, completedAtUtc: world.Clock.GetUtcNow());
        await world.SeedRunAsync(1, 0, 1, completedAtUtc: world.Clock.GetUtcNow());
        Assert.Equal(2, await Lifecycle().QueueEligibleAsync(definition, activated, 100, CancellationToken.None));
        var publishing = (await Lifecycle().ClaimNextAsync("attributes-01", definition.Identity.Fingerprint, policy, CancellationToken.None))!;
        world.Clock.Advance(TimeSpan.FromSeconds(1));
        var abandoned = (await Lifecycle().ClaimNextAsync("attributes-02", definition.Identity.Fingerprint, policy, CancellationToken.None))!;

        // The first unit's completion passes Phase A just before its deadline and is sealing.
        world.Clock.Advance(TimeSpan.FromSeconds(58));
        await using (var db = world.Read())
        {
            var unit = await db.VisualAttributeAnalyses.SingleAsync(x => x.Id == publishing.AnalysisId);
            unit.BeginPublication("attributes-01", tokenMatches: true, 1, world.Clock.GetUtcNow(), policy);
            await db.SaveChangesAsync();
        }

        // Both deadlines have passed; only the abandoned unit's lease has lapsed. A one-unit batch
        // must still reach it rather than select the protected unit and stop.
        world.Clock.Advance(TimeSpan.FromSeconds(40));
        Assert.Equal(1, (await Lifecycle().SweepAsync(policy, 1, CancellationToken.None)).DeadlineFailed);
        await using var read = world.Read();
        Assert.Equal(VisualAttributeAnalysisStatus.Running, (await read.VisualAttributeAnalyses.AsNoTracking().SingleAsync(x => x.Id == publishing.AnalysisId)).Status);
        Assert.Equal(VisualAttributeAnalysisStatus.Failed, (await read.VisualAttributeAnalyses.AsNoTracking().SingleAsync(x => x.Id == abandoned.AnalysisId)).Status);
    }

    // --- Evidence reads over the lifetime of the stream ------------------------------------

    private sealed class Gate
    {
        public TaskCompletionSource Reached { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    }

    /// <summary>An evidence reader whose streams deliver 16 bytes, then block until released.</summary>
    private sealed class GatedEvidenceReader(Func<string, byte[]> read, Gate gate) : IAcceptedEvidenceReader
    {
        public Task<Stream> OpenReadAsync(string acceptedStorageKey, CancellationToken cancellationToken) =>
            Task.FromResult<Stream>(new GatedStream(read(acceptedStorageKey), gate));
    }

    private sealed class GatedStream(byte[] content, Gate gate) : Stream
    {
        private int _position;

        public override bool CanRead => true;
        public override bool CanSeek => true;
        public override bool CanWrite => false;
        public override long Length => content.Length;
        public override long Position { get => _position; set => throw new NotSupportedException(); }

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            if (_position >= 16)
            {
                gate.Reached.TrySetResult();
                await gate.Release.Task.WaitAsync(cancellationToken);
            }

            var count = Math.Min(buffer.Length, (_position < 16 ? 16 : content.Length) - _position);
            content.AsMemory(_position, count).CopyTo(buffer);
            _position += count;
            return count;
        }

        public override int Read(byte[] buffer, int offset, int count) => ReadAsync(buffer.AsMemory(offset, count)).AsTask().GetAwaiter().GetResult();
        public override void Flush() { }
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }

    private async Task<(VisualAttributeApiHost Host, Gate Gate, SeededRun Run)> GatedEvidenceHostAsync()
    {
        var gate = new Gate();
        VisualAttributeWorld? world = null;
        var host = await VisualAttributeApiHost.CreateAsync(fixture, Now, kestrel: true, services: services =>
        {
            services.RemoveAll<IAcceptedEvidenceReader>();
            services.AddSingleton<IAcceptedEvidenceReader>(_ => new GatedEvidenceReader(key => File.ReadAllBytes(world!.EvidencePath(key)), gate));
        });
        world = host.World;
        await host.RunCycleAsync();
        host.World.Clock.Advance(TimeSpan.FromSeconds(1));
        // A crop large enough that the body is still in flight at the gate.
        var run = await host.World.SeedRunAsync(1, 0, 1, completedAtUtc: host.World.Clock.GetUtcNow());
        Assert.Equal(1, (await host.RunCycleAsync()).Queued);
        return (host, gate, run);
    }

    /// <summary>Reads the whole body, or as much as arrives before the server aborts it.</summary>
    private static async Task<(int Bytes, bool Aborted)> DrainAsync(HttpResponseMessage response)
    {
        var total = 0;
        var buffer = new byte[256];
        try
        {
            await using var body = await response.Content.ReadAsStreamAsync();
            int read;
            while ((read = await body.ReadAsync(buffer)) > 0) total += read;
            return (total, false);
        }
        catch (Exception exception) when (exception is IOException or HttpRequestException or OperationCanceledException)
        {
            return (total, true);
        }
    }

    private static Task<HttpResponseMessage> StartEvidenceAsync(VisualAttributeApiHost host, LeasedUnit unit, Guid observationId)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, $"{VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/evidence/{observationId}");
        request.Headers.Add(VisualAttributeContractRules.CapabilityHeader, unit.Capability);
        request.Headers.Add(VisualAttributeContractRules.WorkerHeader, unit.WorkerId);
        request.Headers.Add(VisualAttributeContractRules.AttemptHeader, unit.Attempt.ToString(System.Globalization.CultureInfo.InvariantCulture));
        return host.Client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead);
    }

    [Fact]
    public async Task AnEvidenceStreamStopsWhenOwnershipIsReclaimedMidRead()
    {
        var (host, gate, run) = await GatedEvidenceHostAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var crop = run.Track(0).Observations[0];

        var reading = StartEvidenceAsync(host, unit, crop.ObservationId);
        await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(10));
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        var second = await host.LeaseAsync("attributes-02");
        gate.Release.SetResult();
        using var response = await reading;
        var (bytes, aborted) = await DrainAsync(response);

        Assert.Equal(2, second.Attempt);
        Assert.True(aborted || bytes < crop.Bytes.Length, $"the stale attempt received {bytes} of {crop.Bytes.Length} bytes");
        Assert.True(bytes < crop.Bytes.Length);
    }

    [Fact]
    public async Task AnEvidenceStreamStopsWhenTheLeaseExpiresMidRead()
    {
        var (host, gate, run) = await GatedEvidenceHostAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var crop = run.Track(0).Observations[0];

        var reading = StartEvidenceAsync(host, unit, crop.ObservationId);
        await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(10));
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        gate.Release.SetResult();
        using var response = await reading;
        var (bytes, _) = await DrainAsync(response);

        Assert.True(bytes < crop.Bytes.Length, $"an expired lease received {bytes} of {crop.Bytes.Length} bytes");
    }

    [Fact]
    public async Task AnEvidenceStreamStopsWhenTheOwnerGaveUpAndAnotherAttemptHoldsTheUnit()
    {
        var (host, gate, run) = await GatedEvidenceHostAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var crop = run.Track(0).Observations[0];

        var reading = StartEvidenceAsync(host, unit, crop.ObservationId);
        await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(10));
        // Ownership moves before the first lease would have expired: the owner's retryable
        // failure requeues the unit and another worker claims it at once.
        using (var failed = await host.FailAsync(unit, "visual_attribute_inference_failed", "gave up"))
            Assert.Equal(HttpStatusCode.OK, failed.StatusCode);
        var second = await host.LeaseAsync("attributes-02");
        host.World.Clock.Advance(TimeSpan.FromSeconds(10));
        gate.Release.SetResult();
        using var response = await reading;
        var (bytes, _) = await DrainAsync(response);

        Assert.Equal(2, second.Attempt);
        Assert.True(bytes < crop.Bytes.Length, $"a superseded attempt received {bytes} of {crop.Bytes.Length} bytes");
    }

    [Fact]
    public async Task AnEvidenceStreamKeptAliveByHeartbeatsCompletes()
    {
        var (host, gate, run) = await GatedEvidenceHostAsync();
        await using var owned = host;
        var unit = await host.LeaseAsync();
        var crop = run.Track(0).Observations[0];

        var reading = StartEvidenceAsync(host, unit, crop.ObservationId);
        await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(10));
        host.World.Clock.Advance(TimeSpan.FromSeconds(100));
        using (var heartbeat = await host.HeartbeatAsync(unit))
            Assert.Equal(HttpStatusCode.OK, heartbeat.StatusCode);
        // Past the lease the read began under, inside the renewed one.
        host.World.Clock.Advance(TimeSpan.FromSeconds(60));
        gate.Release.SetResult();
        using var response = await reading;
        var (bytes, aborted) = await DrainAsync(response);

        Assert.False(aborted);
        Assert.Equal(crop.Bytes.Length, bytes);
    }

    // --- Prediction uploads over the lifetime of the body ----------------------------------

    /// <summary>
    /// A raw HTTP/1.1 upload over a socket: the headers and half the body are sent at once, the
    /// rest only when the gate is released. (A pooled client may hold a partial body back.)
    /// Returns the response status, or null when the server closed the connection instead.
    /// </summary>
    private static async Task<HttpStatusCode?> UploadInTwoHalvesAsync(VisualAttributeApiHost host, LeasedUnit unit, byte[] bytes, Gate gate)
    {
        var address = host.Client.BaseAddress!;
        using var tcp = new System.Net.Sockets.TcpClient();
        await tcp.ConnectAsync(address.Host, address.Port);
        await using var network = tcp.GetStream();
        var head = string.Join("\r\n",
            $"PUT {VisualAttributeContractRules.RoutePrefix}/{unit.AnalysisId}/predictions HTTP/1.1",
            $"Host: {address.Authority}",
            $"Content-Type: {VisualAttributeContractRules.PredictionsMediaType}",
            $"Content-Length: {bytes.Length}",
            $"{VisualAttributeContractRules.CapabilityHeader}: {unit.Capability}",
            $"{VisualAttributeContractRules.WorkerHeader}: {unit.WorkerId}",
            $"{VisualAttributeContractRules.AttemptHeader}: {unit.Attempt}",
            $"{VisualAttributeContractRules.ContentSha256Header}: {VisualAttributeApiHost.Sha256(bytes)}",
            "Connection: close", "", "");
        var half = bytes.Length / 2;
        try
        {
            await network.WriteAsync(System.Text.Encoding.ASCII.GetBytes(head));
            await network.WriteAsync(bytes.AsMemory(0, half));
            await network.FlushAsync();
            await gate.Release.Task;
            await network.WriteAsync(bytes.AsMemory(half));
            await network.FlushAsync();
            using var reader = new StreamReader(network, System.Text.Encoding.ASCII);
            var status = await reader.ReadLineAsync();
            return status is null ? null : (HttpStatusCode)int.Parse(status.Split(' ')[1], System.Globalization.CultureInfo.InvariantCulture);
        }
        catch (IOException)
        {
            return null;
        }
    }

    /// <summary>
    /// Signals once the platform has authorised an upload and is streaming its body into staging,
    /// so a test changes ownership only while the transfer is genuinely in flight.
    /// </summary>
    private sealed class SignallingStagingStore(IAttributeStagingStore inner, Gate gate) : IAttributeStagingStore
    {
        public Task<AttributeUploadResult> WriteAsync(Guid analysisId, int attemptCount, Stream body, long declaredSizeBytes,
            string declaredSha256, CancellationToken cancellationToken)
        {
            gate.Reached.TrySetResult();
            return inner.WriteAsync(analysisId, attemptCount, body, declaredSizeBytes, declaredSha256, cancellationToken);
        }

        public StagedPredictions? Describe(Guid analysisId, int attemptCount) => inner.Describe(analysisId, attemptCount);

        public Task<Stream> OpenReadAsync(Guid analysisId, int attemptCount, CancellationToken cancellationToken) =>
            inner.OpenReadAsync(analysisId, attemptCount, cancellationToken);
    }

    private Task<VisualAttributeApiHost> UploadHostAsync(Gate gate) => HostAsync(kestrel: true, services: services =>
    {
        services.RemoveAll<IAttributeStagingStore>();
        services.AddSingleton<IAttributeStagingStore>(provider => new SignallingStagingStore(
            new Mavi.Infrastructure.Storage.AttributeStagingStore(
                provider.GetRequiredService<Microsoft.Extensions.Options.IOptions<Mavi.Infrastructure.Storage.MediaStorageOptions>>()),
            gate));
    });

    private static string AttemptDirectory(VisualAttributeApiHost host, LeasedUnit unit) =>
        Path.Combine(host.World.MediaRoot, AttributeStagingLayout.RootDirectoryName, unit.AnalysisId.ToString("D"),
            AttributeStagingLayout.AttemptDirectoryName(unit.Attempt));

    [Fact]
    public async Task AnUploadStopsWhenOwnershipIsReclaimedMidBodyAndStagesNothing()
    {
        var gate = new Gate();
        await using var host = await UploadHostAsync(gate);
        var unit = await host.LeaseAsync();
        var bytes = AttributeCompletionBuilder.Build(unit).Predictions;

        var sending = UploadInTwoHalvesAsync(host, unit, bytes, gate);
        await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(10));
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        var second = await host.LeaseAsync("attributes-02");
        gate.Release.SetResult();
        var status = await sending;

        Assert.NotEqual(HttpStatusCode.OK, status);
        var directory = AttemptDirectory(host, unit);
        Assert.False(File.Exists(Path.Combine(directory, AttributeStagingLayout.PredictionsFileName)));
        Assert.True(!Directory.Exists(directory) || Directory.GetFiles(directory).Length == 0, "temporary residue left behind");

        // The owner's own create-once upload is unaffected.
        var retry = AttributeCompletionBuilder.Build(second);
        using var uploaded = await host.UploadAsync(second, retry.Predictions);
        Assert.Equal(HttpStatusCode.OK, uploaded.StatusCode);
    }

    [Fact]
    public async Task AnUploadStopsWhenTheLeaseExpiresMidBody()
    {
        var gate = new Gate();
        await using var host = await UploadHostAsync(gate);
        var unit = await host.LeaseAsync();
        var bytes = AttributeCompletionBuilder.Build(unit).Predictions;

        var sending = UploadInTwoHalvesAsync(host, unit, bytes, gate);
        await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(10));
        host.World.Clock.Advance(TimeSpan.FromMinutes(3));
        gate.Release.SetResult();
        var status = await sending;

        Assert.NotEqual(HttpStatusCode.OK, status);
        Assert.False(File.Exists(Path.Combine(AttemptDirectory(host, unit), AttributeStagingLayout.PredictionsFileName)));
    }

    [Fact]
    public async Task AnUploadWhoseLeaseHoldsThroughoutIsStaged()
    {
        var gate = new Gate();
        await using var host = await UploadHostAsync(gate);
        var unit = await host.LeaseAsync();
        var bytes = AttributeCompletionBuilder.Build(unit).Predictions;

        var sending = UploadInTwoHalvesAsync(host, unit, bytes, gate);
        await gate.Reached.Task.WaitAsync(TimeSpan.FromSeconds(10));
        host.World.Clock.Advance(TimeSpan.FromSeconds(100));
        gate.Release.SetResult();

        Assert.Equal(HttpStatusCode.OK, await sending);
        Assert.Equal(bytes, await File.ReadAllBytesAsync(Path.Combine(AttemptDirectory(host, unit), AttributeStagingLayout.PredictionsFileName)));
    }
}
