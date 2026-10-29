using Mavi.Application.Modules.Embeddings;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Embeddings;
using Microsoft.EntityFrameworkCore;
using Pgvector;
using Pgvector.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// Exact, deterministic similarity ranking (ADR-021 §4). Candidates are the shared base Track candidate set at the
/// snapshot (the one implementation Track search uses), joined to the pinned identity's fact-bearing analysis of each
/// candidate's run published inside the snapshot, ordered by cosine distance and then Track id. There is no ANN
/// index: an approximate index is not deterministic, so it could not keep a replayed snapshot identical.
/// </summary>
public sealed class TrackSimilarityRepository(MaviDbContext db, TimeProvider timeProvider) : ITrackSimilarityRepository
{
    public async Task<SimilarityTrackState?> GetTrackStateAsync(
        Guid trackId, string identityFingerprint, long? snapshotVisibilitySequence, CancellationToken cancellationToken)
    {
        var track = await db.Tracks.AsNoTracking()
            .Where(x => x.Id == trackId)
            .Select(x => new { x.Id, x.ObjectClass, x.ProcessingRunId })
            .SingleOrDefaultAsync(cancellationToken);
        if (track is null) return null;

        var fact = await (
                from analysis in db.EmbeddingAnalyses.AsNoTracking()
                where analysis.ProcessingRunId == track.ProcessingRunId && analysis.IdentityFingerprint == identityFingerprint &&
                      (analysis.Status == EmbeddingAnalysisStatus.Completed || analysis.Status == EmbeddingAnalysisStatus.Superseded) &&
                      (snapshotVisibilitySequence == null || analysis.VisibilitySequence <= snapshotVisibilitySequence)
                join row in db.TrackEmbeddings.AsNoTracking() on analysis.Id equals row.AnalysisId
                where row.TrackId == trackId
                select new { row.Outcome, row.UnavailableReason, row.Embedding })
            .SingleOrDefaultAsync(cancellationToken);
        if (fact is null)
        {
            // No fact inside the snapshot: say why. A unit Queued/Running (or published after a pinned snapshot) is
            // pending; a Failed unit is failed with its code; no unit at all is not analysed (a run from before the
            // identity's activation, or of another identity) — both recoverable by an explicit re-analysis.
            var unit = await db.EmbeddingAnalyses.AsNoTracking()
                .Where(analysis => analysis.ProcessingRunId == track.ProcessingRunId && analysis.IdentityFingerprint == identityFingerprint)
                .Select(analysis => new { analysis.Status, analysis.FailureCode })
                .SingleOrDefaultAsync(cancellationToken);
            return unit switch
            {
                null => new SimilarityTrackState(track.Id, track.ObjectClass, TrackSimilarityContractRules.StateNotAnalysed, null, null),
                { Status: EmbeddingAnalysisStatus.Failed } => new SimilarityTrackState(track.Id, track.ObjectClass,
                    TrackSimilarityContractRules.StateFailed, unit.FailureCode, null),
                _ => new SimilarityTrackState(track.Id, track.ObjectClass, TrackSimilarityContractRules.StatePending, null, null),
            };
        }

        return fact.Outcome == "Embedded" && fact.Embedding is { } embedding
            ? new SimilarityTrackState(track.Id, track.ObjectClass, TrackSimilarityContractRules.StateReady, null, embedding.ToArray())
            : new SimilarityTrackState(track.Id, track.ObjectClass, TrackSimilarityContractRules.StateUnavailable, fact.UnavailableReason, null);
    }

    public async Task<SimilarityRankResult> RankAsync(
        TrackSearchQuery scope, float[] vector, string identityFingerprint, Guid? excludeTrackId, int take,
        long? snapshotVisibilitySequence, DateTimeOffset? snapshotUtc, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(scope);
        ArgumentNullException.ThrowIfNull(vector);
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        long sequence;
        DateTimeOffset at;
        if (snapshotVisibilitySequence is { } pinned && snapshotUtc is { } pinnedAt)
        {
            sequence = pinned;
            at = pinnedAt;
        }
        else
        {
            // As a first-page Track search: the shared barrier before any scope is read, so no publication can
            // commit between the snapshot and the candidates it admits.
            await ProcessingVisibilityBarrier.AcquireSearchSharedAsync(db, cancellationToken);
            sequence = await ProcessingVisibilityBarrier.AllocateSequenceAsync(db, cancellationToken);
            at = timeProvider.GetUtcNow().ToUniversalTime();
        }

        var query = new Vector(vector);
        var candidates = AnalyticsScopeQuery.BaseCandidates(db, AnalyticsScopeRequest.From(scope), sequence);
        var ranked =
            from x in candidates
            join row in db.TrackEmbeddings.AsNoTracking() on x.track.Id equals row.TrackId
            join analysis in db.EmbeddingAnalyses.AsNoTracking() on row.AnalysisId equals analysis.Id
            where analysis.IdentityFingerprint == identityFingerprint &&
                  (analysis.Status == EmbeddingAnalysisStatus.Completed || analysis.Status == EmbeddingAnalysisStatus.Superseded) &&
                  analysis.VisibilitySequence <= sequence &&
                  analysis.ProcessingRunId == x.track.ProcessingRunId &&
                  row.Outcome == "Embedded" &&
                  (excludeTrackId == null || x.track.Id != excludeTrackId)
            let distance = row.Embedding!.CosineDistance(query)
            orderby distance, x.track.Id
            select new
            {
                Row = new TrackSearchRow(
                    x.track.Id,
                    x.track.ProcessingRunId,
                    x.track.VideoAssetId,
                    x.camera.Id,
                    x.camera.Code,
                    x.camera.Name,
                    x.track.ObjectClass,
                    x.track.StartTimestampUtc,
                    x.track.EndTimestampUtc,
                    x.track.StartOffsetMs,
                    x.track.EndOffsetMs,
                    x.track.DurationMs,
                    x.track.DetectionCount,
                    x.track.MeanConfidence,
                    x.track.MaxConfidence,
                    x.track.ReviewStatus,
                    x.observation == null ? null : x.observation.ThumbnailArtifactId,
                    x.track.ObjectSubclass,
                    x.track.ObjectSubclassSource),
                Distance = distance,
                Sources = row.SourceObservationIds,
            };
        var rows = await ranked.Take(take).ToListAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
        return new SimilarityRankResult(
            rows.Select(item => new SimilarityRankedRow(item.Row, Math.Round(1.0 - item.Distance, 6),
                item.Sources.Length > 0 ? item.Sources[0] : null)).ToList(),
            sequence,
            at);
    }
}
