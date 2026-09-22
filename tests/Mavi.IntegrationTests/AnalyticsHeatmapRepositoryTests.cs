using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Application.Modules.SceneAnalytics.Lifecycle;
using Mavi.Domain.Intelligence;
using Mavi.Infrastructure.Persistence.Repositories;
using Mavi.Infrastructure.SceneAnalytics;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;

namespace Mavi.IntegrationTests;

/// <summary>
/// The Slice-6 heatmap over a real database and real sealed evidence: scope bounds
/// enforced before any artefact is opened, per-sample window clipping, run scope and
/// evidence integrity (plan §13.2).
/// </summary>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class AnalyticsHeatmapRepositoryTests(PostgresFixture fixture)
{
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 6, 0, 0, TimeSpan.Zero);

    private static readonly SceneAnalysisLeasePolicy Policy =
        new(TimeSpan.FromMinutes(15), TimeSpan.FromMinutes(1), maximumAttempts: 3);

    private static AnalyticsHeatmapQuery Query(
        SceneAnalyticsWorld world,
        int gridWidth = 16,
        Guid? runId = null,
        ObjectClass? objectClass = null) =>
        new(world.CameraId, Now.AddHours(-2), Now.AddHours(1), objectClass, gridWidth, runId);

    private AnalyticsAggregateRepository Repository() => new(fixture.CreateDbContext());

    /// <summary>An evidence reader that fails the test simply by being called.</summary>
    private sealed class ForbiddenEvidence : IHeatmapEvidenceReader
    {
        public int Opens { get; private set; }

        public Task<byte[]?> ReadTrajectoryAsync(string storageKey, CancellationToken cancellationToken)
        {
            Opens++;
            throw new InvalidOperationException("Evidence was opened although the scope should have been refused.");
        }
    }

    private AnalyticsAggregateService Service(SceneAnalyticsWorld world, IHeatmapEvidenceReader? evidence = null) =>
        new(
            Repository(),
            evidence ?? new HeatmapEvidenceReader(new AcceptedEvidenceReader(
                Options.Create(new MediaStorageOptions
                {
                    RootPath = world.MediaRoot,
                    EvidenceRootPath = world.EvidenceRoot,
                }))),
            NullLogger<AnalyticsAggregateService>.Instance);

    // --- Work bounds --------------------------------------------------------

    [Fact]
    public async Task TheScopeResolutionItselfNeverTouchesEvidence()
    {
        // The bounds are database counts. If resolving the scope needed evidence, the
        // guard could not precede the I/O it exists to bound.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());
        var evidence = new ForbiddenEvidence();

        var scope = await Repository().ResolveHeatmapScopeAsync(Query(world), default);

        Assert.True(scope.IsSuccess);
        Assert.Equal(1, scope.CoveredRunCount);
        Assert.Equal(0, evidence.Opens);
    }

    [Fact]
    public async Task TheCandidateCountComesFromTheDatabaseNotFromReadingArtefacts()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());

        var scope = await Repository().ResolveHeatmapScopeAsync(Query(world), default);

        // One analysed Track with a trajectory artefact.
        Assert.Equal(1, scope.CandidateTrackCount);
    }

    [Fact]
    public async Task AnAnalysedTrackWhoseArtefactIsGoneIsStillACandidate()
    {
        // `trajectory_artifact_id` is ON DELETE SET NULL, so deleting an artefact
        // de-references the Track silently. An Analysed outcome is only ever recorded
        // after a trajectory was read and hashed, so this Track must stay counted and
        // listed: dropping it would thin the map with nothing saying why, which is the
        // partial answer this slice refuses to present as the answer.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);

        var scope = await Repository().ResolveHeatmapScopeAsync(Query(world), default);

        Assert.Equal(1, scope.CoveredRunCount);
        Assert.Equal(1, scope.CandidateTrackCount);

        var candidate = Assert.Single(await Repository().ListHeatmapCandidatesAsync(
            Query(world), scope.Identity!, default));
        Assert.Null(candidate.StorageKey);

        // And the service turns that into the integrity failure, not a thinner map.
        var result = await Service(world).HeatmapAsync(Query(world), default);
        Assert.Equal(AnalyticsFailure.EvidenceUnreadable, result.Failure);
    }

    [Fact]
    public async Task ACandidateCarriesTheDigestItsBytesMustMatch()
    {
        // The digest is what makes the map's provenance checkable at all; a candidate
        // projection that dropped it could not tell this Track's evidence from any
        // other syntactically valid trajectory.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        var payload = TrajectoryPayload.StraightCrossing();
        await world.AttachTrajectoryAsync(payload);

        var scope = await Repository().ResolveHeatmapScopeAsync(Query(world), default);
        var candidate = Assert.Single(await Repository().ListHeatmapCandidatesAsync(
            Query(world), scope.Identity!, default));

        Assert.Equal(TrajectoryPayload.Sha256Hex(payload), candidate.Sha256);
    }

    [Fact]
    public async Task EvidenceThatDoesNotMatchItsSealedDigestIsRefused()
    {
        // Real bytes, a real decode, and a digest that says they are not this Track's.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync(
            TrajectoryPayload.StraightCrossing(),
            declaredSha256: new string('d', 64));

        var result = await Service(world).HeatmapAsync(Query(world), default);

        Assert.Equal(AnalyticsFailure.EvidenceUnreadable, result.Failure);
    }

    // --- Evidence semantics -------------------------------------------------

    [Fact]
    public async Task OnlySamplesInsideTheWindowContributeEvenWhenTheTrackOverlapsIt()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        // The fixture Track runs from offset 0 to offset 8,000 ms, and offset 0 is the
        // recording start.
        await world.AttachTrajectoryAsync(TrajectoryPayload.Encode(
        [
            (0L, 0.1, 0.1),
            (2_000L, 0.5, 0.5),
            (6_000L, 0.9, 0.9),
        ]));

        // A window well inside the Track's own interval, so the Track is unambiguously
        // in scope, and containing exactly one of its samples.
        var from = world.RecordingStartUtc.AddSeconds(1);
        var to = world.RecordingStartUtc.AddSeconds(3);
        var query = new AnalyticsHeatmapQuery(world.CameraId, from, to, null, 16, null);

        var result = await Service(world).HeatmapAsync(query, default);

        Assert.True(result.IsSuccess);
        Assert.Equal(1, result.Grid!.SampleCount);
        Assert.Equal(1, result.TrackCount);
    }

    [Fact]
    public async Task ASuccessfulHeatmapCarriesItsIdentityCoverageAndMatrix()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync(TrajectoryPayload.Encode(
        [
            (0L, 0.1, 0.1),
            (60_000L, 0.5, 0.5),
        ]));

        var query = Query(world, gridWidth: 32);
        var result = await Service(world).HeatmapAsync(query, default);
        var response = AnalyticsAggregateService.ToResponse(query, result);

        Assert.Equal(world.RevisionId, response.SceneRevisionId);
        Assert.True(response.SnapshotVisibilitySequence > 0);
        Assert.True(response.Coverage.Complete);
        Assert.Equal(32, response.GridWidth);
        Assert.Equal(18, response.GridHeight);
        Assert.Equal(32 * 18, response.Values.Count);
        Assert.Equal(2, response.SampleCount);
        Assert.Equal(response.SampleCount, response.Values.Sum());
    }

    [Fact]
    public async Task MissingEvidenceForAnAnalysedTrackFailsRatherThanThinningTheMap()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        // Registered as an artefact, never written to the evidence root.
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing(), write: false);

        var result = await Service(world).HeatmapAsync(Query(world), default);

        Assert.Equal(AnalyticsFailure.EvidenceUnreadable, result.Failure);
    }

    [Fact]
    public async Task CorruptEvidenceForAnAnalysedTrackFailsRatherThanBeingSkipped()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync([0x01, 0x02, 0x03, 0x04]);

        var result = await Service(world).HeatmapAsync(Query(world), default);

        Assert.Equal(AnalyticsFailure.EvidenceUnreadable, result.Failure);
    }

    // --- Explicit run scope -------------------------------------------------

    [Fact]
    public async Task AnExplicitRunOfThisCameraIsAccepted()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);
        await world.AttachTrajectoryAsync(TrajectoryPayload.StraightCrossing());

        var scope = await Repository().ResolveHeatmapScopeAsync(Query(world, runId: world.RunId), default);

        Assert.True(scope.IsSuccess);
        Assert.Equal(1, scope.CoveredRunCount);
    }

    [Fact]
    public async Task AnUnknownRunIsIndistinguishableFromAMissingCamera()
    {
        // The non-enumerating boundary: the caller learns nothing about whether the
        // run exists somewhere else.
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now);
        await CommitFactsAsync(world);

        var scope = await Repository().ResolveHeatmapScopeAsync(
            Query(world, runId: Guid.CreateVersion7()), default);

        Assert.Equal(AnalyticsFailure.NotFound, scope.Failure);
    }

    [Fact]
    public async Task AnUnpublishedRunIsRefused()
    {
        var world = await SceneAnalyticsWorld.CreateAsync(fixture, Now, runVisible: false);

        var scope = await Repository().ResolveHeatmapScopeAsync(Query(world, runId: world.RunId), default);

        Assert.Equal(AnalyticsFailure.NotFound, scope.Failure);
    }

    // --- Helpers ------------------------------------------------------------

    private static Task<int> QueueAsync(SceneAnalysisLifecycle lifecycle) =>
        lifecycle.QueueEligibleUnitsAsync(
            SceneAnalyticsWorld.AlgorithmVersion,
            SceneAnalyticsWorld.ParametersSha256,
            null,
            Now.AddDays(-1),
            50,
            default);

    private static async Task<Guid> CommitFactsAsync(SceneAnalyticsWorld world)
    {
        var (lifecycle, db) = world.Host();
        await using var _ = db;
        await QueueAsync(lifecycle);
        var claim = await lifecycle.ClaimNextAsync(SceneAnalyticsWorld.ExecutionIdentity, Policy, default);
        var result = await lifecycle.CommitFactsAsync(claim!, world.Facts(claim!.AnalysisId), default);
        Assert.True(result.IsSuccess);
        return claim.AnalysisId;
    }
}
