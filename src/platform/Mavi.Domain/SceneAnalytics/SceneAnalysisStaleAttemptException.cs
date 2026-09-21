using Mavi.Domain.Common;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// Thrown when an attempt that no longer owns its unit tries to write to it.
/// </summary>
/// <remarks>
/// Its own type rather than a bare <see cref="DomainValidationException"/> because
/// callers must treat it differently from a programming error: a stale attempt is an
/// expected outcome of the fencing model, is logged and discarded, and must not be
/// retried or escalated.
/// </remarks>
public sealed class SceneAnalysisStaleAttemptException(Guid analysisId, int attemptCount)
    : Exception($"Attempt {attemptCount} no longer owns scene analysis {analysisId}.")
{
    public string Code { get; } = SceneAnalyticsErrorCodes.AttemptStale;

    public Guid AnalysisId { get; } = analysisId;

    public int AttemptCount { get; } = attemptCount;
}
