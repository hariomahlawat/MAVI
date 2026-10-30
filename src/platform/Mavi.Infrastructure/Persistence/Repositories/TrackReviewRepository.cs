using Mavi.Application.Modules.Audit;
using Mavi.Application.Modules.Identity;
using Mavi.Application.Modules.Review;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Mavi.Domain.Review;
using Microsoft.EntityFrameworkCore;
using Npgsql;

namespace Mavi.Infrastructure.Persistence.Repositories;

/// <summary>
/// Track review decisions (ADR-027 §1). One transaction per decision: the Track row is locked
/// <c>FOR NO KEY UPDATE</c> (which does not block the key-share locks of foreign-key inserts), the replay and the
/// expectation are checked under the lock, then the audit row, the decision and the projection are written together.
/// </summary>
public sealed class TrackReviewRepository(MaviDbContext db, IAuditWriter audit, ICurrentOperator currentOperator) : ITrackReviewRepository
{
    public const string AuditAction = "tracks.review-decided";
    public const string AuditSubjectType = "track";

    public async Task<TrackReviewOutcome> DecideAsync(TrackReviewRequest request, string requestSha256, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);
        var note = TrackReviewDecision.NormaliseNote(request.Note);
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        var track = await db.Tracks
            .FromSqlInterpolated($"SELECT * FROM tracks WHERE id = {request.TrackId} FOR NO KEY UPDATE")
            .SingleOrDefaultAsync(cancellationToken);

        // The decision id is global: a reuse on another Track is found here too, and that Track's lock is not needed to
        // see a committed row (a concurrent insert of the same id on another Track fails on the primary key instead).
        var prior = await db.TrackReviewDecisions.AsNoTracking().SingleOrDefaultAsync(x => x.Id == request.DecisionId, cancellationToken);
        if (prior is not null)
            return prior.RequestSha256 == requestSha256 && prior.TrackId == request.TrackId
                ? new TrackReviewOutcome(TrackReviewOutcomeKind.Replayed, track?.ReviewStatus, View(prior), await LatestAsync(prior.TrackId, cancellationToken))
                : new TrackReviewOutcome(TrackReviewOutcomeKind.DecisionIdConflict, track?.ReviewStatus, View(prior));
        if (track is null)
            return new TrackReviewOutcome(TrackReviewOutcomeKind.TrackNotFound, null, null);
        if (track.ReviewStatus != request.ExpectedReviewStatus)
            return new TrackReviewOutcome(TrackReviewOutcomeKind.StatusConflict, track.ReviewStatus,
                await LatestAsync(track.Id, cancellationToken));
        if (request.Decision == TrackReviewDecisionKind.Cleared && track.ReviewStatus == ReviewStatus.Unreviewed)
            return new TrackReviewOutcome(TrackReviewOutcomeKind.NothingToClear, track.ReviewStatus, null);

        var receipt = await audit.AppendInTransactionAsync(new AuditRecord(AuditAction, AuditSubjectType, track.Id.ToString("D"),
            new
            {
                decisionId = request.DecisionId,
                trackId = track.Id,
                decision = request.Decision.ToString(),
                expectedReviewStatus = request.ExpectedReviewStatus.ToString(),
                note,
            }), cancellationToken);
        var actor = currentOperator.Required;
        var decision = TrackReviewDecision.Create(request.DecisionId, track.Id, request.Decision, track.ReviewStatus, note, actor.OperatorId,
            actor.DisplayName, actor.IdentitySource, receipt.RecordedAtUtc, requestSha256, receipt.AuditEntryId);
        track.ApplyReviewDecision(decision);
        db.TrackReviewDecisions.Add(decision);
        try
        {
            await db.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateException exception) when (exception.InnerException is PostgresException { SqlState: PostgresErrorCodes.UniqueViolation })
        {
            // The same decision id committed concurrently for another Track: a reuse, never a second decision.
            db.ChangeTracker.Clear();
            await transaction.RollbackAsync(cancellationToken);
            var reused = await db.TrackReviewDecisions.AsNoTracking().SingleAsync(x => x.Id == request.DecisionId, cancellationToken);
            return new TrackReviewOutcome(TrackReviewOutcomeKind.DecisionIdConflict, null, View(reused));
        }

        await transaction.CommitAsync(cancellationToken);
        return new TrackReviewOutcome(TrackReviewOutcomeKind.Recorded, track.ReviewStatus, View(decision), View(decision));
    }

    public async Task<TrackReviewState?> GetStateAsync(Guid trackId, CancellationToken cancellationToken)
    {
        var track = await db.Tracks.AsNoTracking()
            .Where(x => x.Id == trackId)
            .Select(x => new { x.Id, x.ProcessingRunId, x.VideoAssetId, x.ReviewStatus })
            .SingleOrDefaultAsync(cancellationToken);
        if (track is null) return null;

        // Other completed runs of the same video and how many of their Tracks carry a decision; nothing is copied (§5).
        var otherRuns = await db.ProcessingRuns.AsNoTracking()
            .Where(run => run.VideoAssetId == track.VideoAssetId && run.Id != track.ProcessingRunId && run.Status == ProcessingRunStatus.Completed)
            .Select(run => new
            {
                run.Id,
                run.CompletedAtUtc,
                Reviewed = db.Tracks.Count(other => other.ProcessingRunId == run.Id &&
                                                    db.TrackReviewDecisions.Any(decision => decision.TrackId == other.Id)),
            })
            .OrderByDescending(run => run.CompletedAtUtc)
            .ToListAsync(cancellationToken);
        return new TrackReviewState(track.Id, track.ProcessingRunId, track.ReviewStatus, await LatestAsync(track.Id, cancellationToken),
            otherRuns.Select(run => new EarlierRunDecisions(run.Id, run.CompletedAtUtc, run.Reviewed)).ToList());
    }

    public async Task<TrackReviewHistoryPage?> GetHistoryAsync(Guid trackId, long? beforeSequence, int limit, CancellationToken cancellationToken)
    {
        if (!await db.Tracks.AnyAsync(x => x.Id == trackId, cancellationToken)) return null;
        var query = db.TrackReviewDecisions.AsNoTracking().Where(x => x.TrackId == trackId);
        if (beforeSequence is { } before) query = query.Where(x => x.Sequence < before);
        var rows = await query.OrderByDescending(x => x.Sequence).Take(limit + 1).ToListAsync(cancellationToken);
        var items = rows.Take(limit).Select(View).ToList();
        return new TrackReviewHistoryPage(items, rows.Count > limit ? items[^1].Sequence : null);
    }

    private async Task<TrackReviewDecisionView?> LatestAsync(Guid trackId, CancellationToken cancellationToken)
    {
        var latest = await db.TrackReviewDecisions.AsNoTracking()
            .Where(x => x.TrackId == trackId)
            .OrderByDescending(x => x.Sequence)
            .FirstOrDefaultAsync(cancellationToken);
        return latest is null ? null : View(latest);
    }

    private static TrackReviewDecisionView View(TrackReviewDecision row) =>
        new(row.Id, row.TrackId, row.Decision, row.PreviousStatus, row.ResultingStatus, row.Note, row.OperatorId, row.OperatorDisplayName,
            row.IdentitySource, row.DecidedAtUtc, row.AuditEntryId, row.Sequence);
}
