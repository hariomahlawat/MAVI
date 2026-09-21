using System.Globalization;

namespace Mavi.Domain.SceneAnalytics;

/// <summary>
/// The two dimensions along which one analysis identity is newer than another: the scene
/// revision it was computed against, and the engine that computed it.
/// </summary>
public readonly record struct SceneAnalysisIdentityOrder(int RevisionNumber, string AlgorithmVersion);

/// <summary>
/// Orders analysis identities of one run by recency, so that currency is decided by
/// <b>which identity is newer</b> and never by which attempt happened to finish first.
/// </summary>
/// <remarks>
/// <para>
/// Completion order is not identity order. Two attempts for one run can overlap — a
/// geometry edit activates a new revision while the previous revision is still being
/// analysed — and the slower one can commit last. If the late finisher took currency, a
/// slow analysis of last week's geometry would demote today's, readiness would report
/// <c>Stale</c>, and re-analysis could not repair it: the newer identity's row already
/// exists and classifies as already analysed.
/// </para>
/// <para>
/// <b>Revision number dominates.</b> Geometry is what the operator edits and what
/// readiness is keyed on, so a newer revision is newer whatever engine produced it. The
/// algorithm version breaks ties within one revision (plan §R: a version change makes
/// existing facts stale for readiness). Ordering revision first also matches the shape of
/// the readiness rule, which resolves the active revision before it looks at the version.
/// </para>
/// <para>
/// The cross-dimensional case — a higher revision number with an older engine — is not
/// reachable through any supported path, because units are only ever created for the
/// camera's <i>active</i> revision and both dimensions advance forward. The order is
/// nonetheless total and deterministic, so no transaction timing can decide it.
/// </para>
/// </remarks>
public static class SceneAnalysisIdentityRecency
{
    /// <summary>The frozen engine version shape: <c>scene-analytics-v&lt;major&gt;</c>.</summary>
    private const string MajorVersionMarker = "-v";

    /// <summary>Whether <paramref name="candidate"/> is a newer identity than <paramref name="other"/>.</summary>
    public static bool IsNewerThan(SceneAnalysisIdentityOrder candidate, SceneAnalysisIdentityOrder other) =>
        Compare(candidate, other) > 0;

    /// <summary>Negative, zero or positive as <paramref name="left"/> is older, equal or newer.</summary>
    public static int Compare(SceneAnalysisIdentityOrder left, SceneAnalysisIdentityOrder right)
    {
        var byRevision = left.RevisionNumber.CompareTo(right.RevisionNumber);
        return byRevision != 0
            ? byRevision
            : CompareAlgorithmVersions(left.AlgorithmVersion, right.AlgorithmVersion);
    }

    /// <summary>
    /// Compares two engine versions by their major number.
    /// </summary>
    /// <remarks>
    /// An ordinal string comparison would put <c>scene-analytics-v10</c> before
    /// <c>scene-analytics-v9</c>, so the major number is parsed and compared as a number.
    /// A value that does not carry one — which the domain never mints, but a future
    /// rename or hand-edited row might — falls back to an ordinal comparison so the order
    /// stays total rather than throwing inside a completion transaction.
    /// </remarks>
    public static int CompareAlgorithmVersions(string left, string right)
    {
        if (string.Equals(left, right, StringComparison.Ordinal))
        {
            return 0;
        }

        return TryReadMajor(left, out var leftMajor) && TryReadMajor(right, out var rightMajor)
            ? leftMajor.CompareTo(rightMajor)
            : string.CompareOrdinal(left, right);
    }

    private static bool TryReadMajor(string algorithmVersion, out int major)
    {
        major = 0;
        if (string.IsNullOrEmpty(algorithmVersion))
        {
            return false;
        }

        var marker = algorithmVersion.LastIndexOf(MajorVersionMarker, StringComparison.Ordinal);
        if (marker < 0)
        {
            return false;
        }

        return int.TryParse(
            algorithmVersion.AsSpan(marker + MajorVersionMarker.Length),
            NumberStyles.None,
            CultureInfo.InvariantCulture,
            out major);
    }
}
