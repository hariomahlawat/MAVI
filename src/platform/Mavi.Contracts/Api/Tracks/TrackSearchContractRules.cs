namespace Mavi.Contracts.Api.Tracks;

/// <summary>
/// The wire grammar of the analytic extension to <c>GET /api/tracks</c> (plan §S,
/// frozen for Slice 4): the query keys, their closed vocabularies and the shape of
/// a historical algorithm version.
/// </summary>
/// <remarks>
/// <para>
/// These are transport facts only. Which keys depend on which, how a default is
/// canonicalised and what a predicate means against the fact tables are
/// Application behaviour and deliberately not expressed here.
/// </para>
/// <para>
/// Two of the vocabularies differ in case from the values the fact tables persist
/// (<c>AToB</c>/<c>BToA</c>): the wire is camel-cased like every other query value
/// on this endpoint, the storage is not, and the mapping happens once at the API
/// boundary. Headings are the same eight letters on both sides; the engine's
/// <c>None</c> heading is evidence, not a filter, and is absent here on purpose.
/// </para>
/// </remarks>
public static class TrackSearchContractRules
{
    // --- Query keys ---------------------------------------------------------

    public const string SceneRevisionIdKey = "sceneRevisionId";
    public const string AnalyticsAlgorithmVersionKey = "analyticsAlgorithmVersion";
    public const string ZoneIdKey = "zoneId";
    public const string ZoneRelationKey = "zoneRelation";
    public const string MinDwellMsKey = "minDwellMs";
    public const string LineIdKey = "lineId";
    public const string CrossingDirectionKey = "crossingDirection";
    public const string MotionDirectionKey = "motionDirection";
    public const string MinStationaryMsKey = "minStationaryMs";
    public const string LoiteringKey = "loitering";
    public const string AnalyticsCoverageKey = "analyticsCoverage";

    /// <summary>
    /// The operator-facing vehicle subclass filter (Stage 3, X2). An ordinary filter, not an
    /// analytic one. Which values it accepts is the Application's exposure policy.
    /// </summary>
    public const string ObjectSubclassKey = "objectSubclass";

    /// <summary>
    /// The plate-text predicate (Stage 4, plan §5.4): a literal match on the
    /// <c>mavi-plate-normalisation-v1</c> text of a Vehicle Track's default plate analysis. An
    /// ordinary cross-camera filter, not an analytic one; it implies <c>objectClass=Vehicle</c>.
    /// </summary>
    public const string PlateTextKey = "plateText";

    /// <summary>How <see cref="PlateTextKey"/> matches; valid only beside it.</summary>
    public const string PlateMatchKey = "plateMatch";

    /// <summary>The plate predicate keys, in canonical order.</summary>
    public static readonly IReadOnlyList<string> PlateQueryKeys = [PlateTextKey, PlateMatchKey];

    /// <summary>
    /// The keys whose presence makes a Track query analytics-dependent. Any one of
    /// them turns an ordinary search into one that resolves a scene identity and
    /// reports coverage.
    /// </summary>
    public static readonly IReadOnlyList<string> AnalyticsDependentKeys =
    [
        SceneRevisionIdKey,
        AnalyticsAlgorithmVersionKey,
        ZoneIdKey,
        ZoneRelationKey,
        MinDwellMsKey,
        LineIdKey,
        CrossingDirectionKey,
        MotionDirectionKey,
        MinStationaryMsKey,
        LoiteringKey,
    ];

    /// <summary>
    /// Every analytic key the endpoint accepts: the dependent keys plus the coverage
    /// control flag, which on its own makes nothing analytics-dependent.
    /// </summary>
    public static readonly IReadOnlyList<string> AnalyticsQueryKeys =
    [
        .. AnalyticsDependentKeys,
        AnalyticsCoverageKey,
    ];

    // --- Vocabularies -------------------------------------------------------

    public static readonly IReadOnlyList<string> ZoneRelationValues = ["entered", "exited", "dwelled"];

    public const string DefaultZoneRelation = "dwelled";

    public static readonly IReadOnlyList<string> CrossingDirectionValues = ["aToB", "bToA"];

    /// <summary>Screen headings: north is decreasing y. Never compass bearings.</summary>
    public static readonly IReadOnlyList<string> MotionDirectionValues =
        ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

    public static readonly IReadOnlyList<string> CoverageModeValues = ["partial", "complete"];

    public const string DefaultCoverageMode = "partial";

    public const string CompleteCoverageMode = "complete";

    /// <summary>The only value <c>loitering</c> accepts; false is represented by omission.</summary>
    public const string LoiteringTrue = "true";

    /// <summary>
    /// A Track's analytics status on the detail surface. The first two are the persisted
    /// per-Track outcome kinds; the rest are the run-readiness words the Processing
    /// surfaces already use, so no new state vocabulary arrives with this contract.
    /// </summary>
    public static readonly IReadOnlyList<string> TrackAnalyticsStatusValues =
        ["Analysed", "Unavailable", "Pending", "Failed", "Stale", "NotConfigured", "Disabled"];

    /// <summary>
    /// <c>plateMatch</c>: a substring, a prefix or the whole normalised text. Literal in every mode:
    /// no confusable expansion (O/0, I/1, B/8, …) and no edit distance (plan B5).
    /// </summary>
    public static readonly IReadOnlyList<string> PlateMatchValues = ["contains", "prefix", "exact"];

    public const string DefaultPlateMatch = "contains";

    /// <summary>
    /// The normalised query text's bounds. Three is the shortest text a trigram index can serve
    /// (plan §2.8); fifteen is longer than any Indian registration in either advisory format.
    /// </summary>
    public const int MinimumPlateTextLength = 3;

    public const int MaximumPlateTextLength = 15;

    /// <summary>
    /// The raw <c>plateText</c> bound, before normalisation removes separators. Bounded so a
    /// request cannot make the parser normalise an arbitrarily long string.
    /// </summary>
    public const int MaximumRawPlateTextLength = 64;

    /// <summary>
    /// A Vehicle Track's plate readiness on the detail surface and the bucket words of the search
    /// coverage block: the run-level readiness words (ADR-013 §12) a Vehicle Track can be in.
    /// <c>NotApplicable</c> is absent on purpose: a run with a Vehicle Track is always applicable.
    /// </summary>
    public static readonly IReadOnlyList<string> PlateReadinessValues = ["NotConfigured", "Pending", "Ready", "Failed", "Stale"];

    /// <summary>The persisted Track-level plate outcome kinds.</summary>
    public static readonly IReadOnlyList<string> PlateTrackOutcomeValues = ["Analysed", "Unavailable"];

    /// <summary>
    /// How a Vehicle Track's searchable readings relate (plan §2.7): derived from its Track texts,
    /// never asserted. No value means "confirmed".
    /// </summary>
    public static readonly IReadOnlyList<string> PlateAgreementValues = ["none", "single", "consistent", "conflicting"];

    public static bool IsPlateMatch(string? value) => Contains(PlateMatchValues, value);

    // --- Algorithm version shape -------------------------------------------

    /// <summary>The frozen engine version shape, <c>scene-analytics-v&lt;major&gt;</c> (plan §R).</summary>
    public const string AlgorithmVersionPrefix = "scene-analytics-v";

    public const int MaximumAlgorithmVersionLength = 64;

    public static bool IsZoneRelation(string? value) => Contains(ZoneRelationValues, value);

    public static bool IsCrossingDirection(string? value) => Contains(CrossingDirectionValues, value);

    public static bool IsMotionDirection(string? value) => Contains(MotionDirectionValues, value);

    public static bool IsCoverageMode(string? value) => Contains(CoverageModeValues, value);

    public static bool IsTrackAnalyticsStatus(string? value) => Contains(TrackAnalyticsStatusValues, value);

    public static bool IsAnalyticsDependentKey(string? value) => Contains(AnalyticsDependentKeys, value);

    /// <summary>
    /// Whether a value has the shape of an engine version: the fixed prefix and a
    /// positive major number with no leading zero, sign or whitespace.
    /// </summary>
    public static bool IsAlgorithmVersion(string? value)
    {
        if (value is null ||
            value.Length > MaximumAlgorithmVersionLength ||
            !value.StartsWith(AlgorithmVersionPrefix, StringComparison.Ordinal))
        {
            return false;
        }

        var major = value.AsSpan(AlgorithmVersionPrefix.Length);
        if (major.Length is 0 or > 4 || major[0] == '0')
        {
            return false;
        }

        foreach (var character in major)
        {
            if (character is < '0' or > '9')
            {
                return false;
            }
        }

        return true;
    }

    private static bool Contains(IReadOnlyList<string> allowed, string? value)
    {
        if (value is null)
        {
            return false;
        }

        for (var index = 0; index < allowed.Count; index++)
        {
            if (string.Equals(allowed[index], value, StringComparison.Ordinal))
            {
                return true;
            }
        }

        return false;
    }
}
