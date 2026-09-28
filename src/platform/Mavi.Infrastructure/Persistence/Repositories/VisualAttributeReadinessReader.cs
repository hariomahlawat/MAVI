using Mavi.Application.Modules.VisualAttributes;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;

namespace Mavi.Infrastructure.Persistence.Repositories;

public sealed class VisualAttributeReadinessReader(MaviDbContext db) : IVisualAttributeReadinessReader
{
    public async Task<VisualAttributeRunFacts?> ReadAsync(
        Guid processingRunId, string? preferredFingerprint, IReadOnlyList<string> applicableObjectClasses, CancellationToken cancellationToken)
    {
        var run = await db.ProcessingRuns.AsNoTracking()
            .Where(x => x.Id == processingRunId)
            .Select(x => new { x.Status, x.VisibilitySequence, x.CompletedAtUtc })
            .SingleOrDefaultAsync(cancellationToken);
        if (run is null) return null;

        var classes = applicableObjectClasses.Select(VisualAttributeLifecycle.ParseObjectClass).ToList();
        var hasApplicable = classes.Count > 0 &&
            await db.Tracks.AsNoTracking().AnyAsync(track => track.ProcessingRunId == processingRunId && classes.Contains(track.ObjectClass), cancellationToken);
        var analyses = await db.VisualAttributeAnalyses.AsNoTracking()
            .Where(x => x.ProcessingRunId == processingRunId)
            .Select(x => new VisualAttributeAnalysisFacts(x.Id, x.IdentityFingerprint, x.Status, x.AttemptCount, x.QueuedAtUtc, x.CompletedAtUtc, x.FailureCode))
            .ToListAsync(cancellationToken);
        DateTimeOffset? activatedAt = null;
        if (preferredFingerprint is not null)
        {
            var latest = await db.VisualAttributeIdentityActivations.AsNoTracking()
                .OrderByDescending(x => x.ActivatedAtUtc).ThenByDescending(x => x.Id)
                .Select(x => new { x.Fingerprint, x.ActivatedAtUtc })
                .FirstOrDefaultAsync(cancellationToken);
            if (latest?.Fingerprint == preferredFingerprint) activatedAt = latest.ActivatedAtUtc;
        }

        return new VisualAttributeRunFacts(
            run.Status == ProcessingRunStatus.Completed && run.VisibilitySequence != null,
            run.CompletedAtUtc,
            hasApplicable,
            activatedAt,
            analyses);
    }
}
