using Mavi.Domain.Common;
using Mavi.Domain.Scene.Geometry;

namespace Mavi.Domain.Scene;

/// <summary>
/// One counting line inside a scene revision. Immutable, with a stable
/// <see cref="LineId"/> carried forward by later revisions.
/// </summary>
public sealed class TripLine
{
    private TripLine() { }

    internal static TripLine Create(
        Guid revisionId,
        Guid lineId,
        string? name,
        bool enabled,
        ScenePointDraft? a,
        ScenePointDraft? b,
        bool directed,
        string? aToBLabel,
        string? bToALabel)
    {
        if (revisionId == Guid.Empty || lineId == Guid.Empty)
        {
            throw new DomainValidationException(
                SceneErrorCodes.RevisionInvalid,
                "A trip line requires a revision and a line identity.");
        }

        var normalizedName = NormalizeName(name);

        if (a is null || b is null)
        {
            throw new DomainValidationException(SceneErrorCodes.LineRange, "A trip line needs both endpoints.");
        }

        var pointA = NormalizedPoint.Create(a.X, a.Y, SceneErrorCodes.LineRange);
        var pointB = NormalizedPoint.Create(b.X, b.Y, SceneErrorCodes.LineRange);
        if (pointA.DistanceTo(pointB) < SceneRules.MinimumLineEndpointSeparation)
        {
            throw new DomainValidationException(
                SceneErrorCodes.LineEndpointsIdentical,
                $"Trip line endpoints must be at least {SceneRules.MinimumLineEndpointSeparation} apart.");
        }

        return new TripLine
        {
            RevisionId = revisionId,
            LineId = lineId,
            Name = normalizedName,
            Enabled = enabled,
            A = pointA,
            B = pointB,
            Directed = directed,
            AToBLabel = NormalizeLabel(aToBLabel, "A to B"),
            BToALabel = NormalizeLabel(bToALabel, "B to A"),
        };
    }

    public Guid RevisionId { get; private set; }

    /// <summary>Stable across revisions.</summary>
    public Guid LineId { get; private set; }

    public string Name { get; private set; } = string.Empty;

    public bool Enabled { get; private set; }

    public NormalizedPoint A { get; private set; }

    public NormalizedPoint B { get; private set; }

    /// <summary>
    /// Whether the operator cares which way the line is crossed. Direction is recorded
    /// either way; this only decides how the crossing is presented.
    /// </summary>
    public bool Directed { get; private set; }

    public string AToBLabel { get; private set; } = string.Empty;

    public string BToALabel { get; private set; } = string.Empty;

    private static string NormalizeName(string? name)
    {
        if (string.IsNullOrWhiteSpace(name))
        {
            throw new DomainValidationException(SceneErrorCodes.LineNameRequired, "A trip line needs a name.");
        }

        var trimmed = name.Trim();
        if (trimmed.Length > SceneRules.MaximumNameLength)
        {
            throw new DomainValidationException(
                SceneErrorCodes.LineNameTooLong,
                $"A trip line name must not exceed {SceneRules.MaximumNameLength} characters.");
        }

        return trimmed;
    }

    private static string NormalizeLabel(string? label, string fallback)
    {
        if (string.IsNullOrWhiteSpace(label))
        {
            return fallback;
        }

        var trimmed = label.Trim();
        if (trimmed.Length > SceneRules.MaximumDirectionLabelLength)
        {
            throw new DomainValidationException(
                SceneErrorCodes.LineLabelTooLong,
                $"A direction label must not exceed {SceneRules.MaximumDirectionLabelLength} characters.");
        }

        return trimmed;
    }
}
