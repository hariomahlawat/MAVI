using System.Globalization;
using Mavi.Application.Modules.Plates;
using Mavi.Domain.Plates;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace Mavi.Infrastructure.Storage;

/// <summary>
/// Reclaims <c>{MediaStorage:RootPath}/staging-plates/{analysisId}/attempt-NNNN</c>
/// directories that the plate analysis row proves dead.
/// </summary>
/// <remarks>
/// <para>
/// Authority, per analysis directory, from one row read:
/// <list type="bullet">
/// <item><b>Running</b>: attempts <c>k &lt; AttemptCount</c>; the current attempt is never removed,
/// however old — it is the input of the Phase B seal.</item>
/// <item><b>Queued</b> (after a retryable failure): every attempt <c>k ≤ AttemptCount</c>; the next claim
/// is a later attempt, and a requeued attempt can never publish.</item>
/// <item><b>Completed / Superseded / Failed</b>: the whole directory once <c>now ≥ CompletedAtUtc + grace</c>;
/// a published artefact lives in the accepted-evidence root, not here.</item>
/// <item><b>No row</b>: only once the directory is older than <see cref="UnknownAnalysisGrace"/>.</item>
/// </list>
/// </para>
/// <para>
/// It never opens <c>staging/</c> (the VisionJob janitor's tree) or the evidence root. Only
/// canonical names are acted on, and deletion goes through the handle-relative
/// <see cref="StagingDirectory"/>, which never follows a link.
/// </para>
/// </remarks>
public sealed partial class PlateStagingJanitor(
    MaviDbContext db,
    IOptions<MediaStorageOptions> mediaOptions,
    IOptions<PlateOptions> plateOptions,
    TimeProvider clock,
    ILogger<PlateStagingJanitor> logger) : IPlateStagingJanitor
{
    public static readonly TimeSpan UnknownAnalysisGrace = TimeSpan.FromHours(24);
    /// <summary>The most directories one cycle removes; the scan itself is not capped.</summary>
    public const int MaximumDirectoriesPerCycle = 1000;
    private const int RowLookupBatchSize = 1000;

    internal Func<string, StagingDirectory> OpenRoot { get; init; } = StagingDirectory.OpenRoot;

    public async Task<int> RunCycleAsync(CancellationToken cancellationToken)
    {
        if (!StagingDirectory.IsSupported) return 0;
        var nowUtc = clock.GetUtcNow();
        var grace = TimeSpan.FromMinutes(plateOptions.Value.StagingGraceMinutes);

        using var root = OpenRoot(mediaOptions.Value.RootPath);
        if (root.TryOpenChildDirectory(PlateStagingLayout.RootDirectoryName, out var stagingRoot) != StagingChildOpen.Opened)
            return 0;

        using (stagingRoot!)
        {
            var directories = new List<(string Name, Guid AnalysisId, DateTimeOffset LastWriteUtc)>();
            foreach (var entry in stagingRoot!.ListChildren())
            {
                if (entry.Name is { } name && entry.IsRealDirectory && TryParseAnalysisId(name, out var analysisId))
                    directories.Add((name, analysisId, entry.LastWriteTimeUtc));
                else
                    LogUnrecognised(logger, entry.Name ?? "<non-utf8>");
            }

            // Every directory is judged: capping the scan instead would let a thousand live units
            // listed first hide every reclaimable one behind them, cycle after cycle.
            var rows = new Dictionary<Guid, (PlateAnalysisStatus Status, int AttemptCount, DateTimeOffset? CompletedAtUtc)>();
            foreach (var chunk in directories.Select(item => item.AnalysisId).Chunk(RowLookupBatchSize))
            {
                var found = await db.PlateAnalyses.AsNoTracking()
                    .Where(unit => chunk.Contains(unit.Id))
                    .Select(unit => new { unit.Id, unit.Status, unit.AttemptCount, unit.CompletedAtUtc })
                    .ToListAsync(cancellationToken);
                foreach (var unit in found) rows[unit.Id] = (unit.Status, unit.AttemptCount, unit.CompletedAtUtc);
            }

            var removed = 0;
            foreach (var (name, analysisId, lastWriteUtc) in directories)
            {
                cancellationToken.ThrowIfCancellationRequested();
                // The cap bounds the work a cycle does, not what it considers; the rest wait for the next.
                if (removed >= MaximumDirectoriesPerCycle) break;
                try
                {
                    if (!rows.TryGetValue(analysisId, out var row))
                    {
                        if (lastWriteUtc <= nowUtc - UnknownAnalysisGrace && stagingRoot.RemoveChildTree(name) is not null)
                        {
                            LogOrphanRemoved(logger, name);
                            removed++;
                        }

                        continue;
                    }

                    switch (row.Status)
                    {
                        case PlateAnalysisStatus.Completed:
                        case PlateAnalysisStatus.Superseded:
                        case PlateAnalysisStatus.Failed:
                            if (row.CompletedAtUtc is { } endedUtc && nowUtc >= endedUtc + grace && stagingRoot.RemoveChildTree(name) is not null)
                                removed++;
                            break;
                        case PlateAnalysisStatus.Running:
                            removed += RemoveAttempts(stagingRoot, name, number => number < row.AttemptCount);
                            break;
                        case PlateAnalysisStatus.Queued:
                            removed += RemoveAttempts(stagingRoot, name, number => number <= row.AttemptCount);
                            break;
                    }
                }
                catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
                {
                    // One unremovable directory must not stop the others; it is retried next cycle.
                    LogRemovalFailed(logger, name, exception);
                }
            }

            return removed;
        }
    }

    private static int RemoveAttempts(StagingDirectory stagingRoot, string analysisName, Func<int, bool> removable)
    {
        if (stagingRoot.TryOpenChildDirectory(analysisName, out var analysis) != StagingChildOpen.Opened)
            return 0;
        using (analysis!)
        {
            var removed = 0;
            foreach (var entry in analysis!.ListChildren())
            {
                if (entry.Name is { } name && entry.IsRealDirectory && StagingJanitor.TryParseAttempt(name, out var number) &&
                    removable(number) && analysis.RemoveChildTree(name) is not null)
                    removed++;
            }

            return removed;
        }
    }

    internal static bool TryParseAnalysisId(string name, out Guid analysisId) =>
        Guid.TryParseExact(name, "D", out analysisId) &&
        string.Equals(name, analysisId.ToString("D", CultureInfo.InvariantCulture), StringComparison.Ordinal);

    [LoggerMessage(EventId = 2110, EventName = "plate_staging_unrecognised", Level = LogLevel.Warning,
        Message = "Plate staging entry {Name} is not a canonical analysis directory and is left alone.")]
    private static partial void LogUnrecognised(ILogger logger, string name);

    [LoggerMessage(EventId = 2111, EventName = "plate_staging_orphan_removed", Level = LogLevel.Warning,
        Message = "Plate staging directory {Name} has no analysis row and was removed after the unknown-analysis grace.")]
    private static partial void LogOrphanRemoved(ILogger logger, string name);

    [LoggerMessage(EventId = 2112, EventName = "plate_staging_removal_failed", Level = LogLevel.Error,
        Message = "Plate staging directory {Name} could not be reclaimed; it is retried next cycle.")]
    private static partial void LogRemovalFailed(ILogger logger, string name, Exception exception);
}
