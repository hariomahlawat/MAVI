using Mavi.Application.Modules.Plates;
using Mavi.Contracts.Api.Tracks;
using Mavi.Domain.Plates;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>How a plate predicate matches the normalised Track texts. Always literal (plan B5).</summary>
public enum TrackPlateMatch
{
    Contains,
    Prefix,
    Exact,
}

/// <summary>
/// The plate predicate of a Track search (Stage 4, plan §5.4): a normalised query text and a match
/// mode. <paramref name="Text"/> is already <c>mavi-plate-normalisation-v1</c> output of 3–15
/// <c>[A-Z0-9]</c> characters; the only way to build one from a request is
/// <see cref="TrackPlateQueryRules.TryParse"/>.
/// </summary>
public sealed record TrackPlateQuery(string Text, TrackPlateMatch Match);

/// <summary>The grammar of <c>plateText</c> and <c>plateMatch</c>.</summary>
public static class TrackPlateQueryRules
{
    /// <summary>
    /// Parses the two keys. Both missing is no predicate (true, null). <c>plateMatch</c> alone, an
    /// unknown match mode, a text the frozen normalisation rejects (or cannot read), or a normalised
    /// text outside 3–15 characters is a refusal.
    /// </summary>
    public static bool TryParse(string? rawText, string? rawMatch, out TrackPlateQuery? query)
    {
        query = null;
        if (rawText is null)
            return rawMatch is null;

        var match = TrackPlateMatch.Contains;
        if (rawMatch is not null && !TryParseMatch(rawMatch, out match))
            return false;

        if (!TryNormalise(rawText, out var text))
            return false;

        query = new TrackPlateQuery(text, match);
        return true;
    }

    /// <summary>
    /// The frozen <c>mavi-plate-normalisation-v1</c> applied to a query: the same function the
    /// platform applies to persisted readings, so a query and a reading normalise identically. No
    /// confusable substitution happens here or anywhere else.
    /// </summary>
    public static bool TryNormalise(string rawText, out string text)
    {
        text = string.Empty;
        if (rawText.Length is 0 or > TrackSearchContractRules.MaximumRawPlateTextLength)
            return false;

        NormalisedPlate normalised;
        try
        {
            normalised = PlateNormalisation.Normalise(rawText);
        }
        catch (ArgumentException)
        {
            // Ill-formed UTF-16 (a lone surrogate): not a text the normalisation can read.
            return false;
        }

        if (normalised.Normalised is not { } value ||
            value.Length is < TrackSearchContractRules.MinimumPlateTextLength or > TrackSearchContractRules.MaximumPlateTextLength)
            return false;

        text = value;
        return true;
    }

    public static bool TryParseMatch(string raw, out TrackPlateMatch match)
    {
        switch (raw)
        {
            case "contains":
                match = TrackPlateMatch.Contains;
                return true;
            case "prefix":
                match = TrackPlateMatch.Prefix;
                return true;
            case "exact":
                match = TrackPlateMatch.Exact;
                return true;
            default:
                match = default;
                return false;
        }
    }

    public static string ToWire(TrackPlateMatch match) => match switch
    {
        TrackPlateMatch.Contains => "contains",
        TrackPlateMatch.Prefix => "prefix",
        TrackPlateMatch.Exact => "exact",
        _ => throw new ArgumentOutOfRangeException(nameof(match)),
    };

    /// <summary>
    /// Whether a persisted normalised text matches. The in-memory twin of the SQL predicate, used by
    /// the per-page explanation's tests and as the specification of the predicate.
    /// </summary>
    public static bool Matches(TrackPlateQuery query, string normalisedText)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(normalisedText);
        return query.Match switch
        {
            TrackPlateMatch.Contains => normalisedText.Contains(query.Text, StringComparison.Ordinal),
            TrackPlateMatch.Prefix => normalisedText.StartsWith(query.Text, StringComparison.Ordinal),
            TrackPlateMatch.Exact => string.Equals(normalisedText, query.Text, StringComparison.Ordinal),
            _ => false,
        };
    }

    /// <summary>
    /// The <c>LIKE</c> pattern of a contains or prefix predicate. The text is <c>[A-Z0-9]</c> only, so
    /// it holds no <c>LIKE</c> metacharacter and needs no escaping.
    /// </summary>
    public static string LikePattern(TrackPlateQuery query)
    {
        ArgumentNullException.ThrowIfNull(query);
        return query.Match switch
        {
            TrackPlateMatch.Contains => "%" + query.Text + "%",
            TrackPlateMatch.Prefix => query.Text + "%",
            _ => throw new ArgumentException("An exact plate predicate is an equality, not a pattern.", nameof(query)),
        };
    }
}

/// <summary>
/// The plate coverage of a search's base candidate scope, in Vehicle Tracks (plan §5.4). The five
/// buckets partition <see cref="VehicleTracksInScope"/>.
/// </summary>
public sealed record TrackPlateCoverage(
    string? IdentityFingerprint,
    int VehicleTracksInScope,
    int Ready,
    int Pending,
    int Failed,
    int Stale,
    int NotConfigured)
{
    public static TrackPlateCoverage Empty(string? identityFingerprint) => new(identityFingerprint, 0, 0, 0, 0, 0, 0);
}

/// <summary>Why one row matched the plate predicate (the item <c>plate</c> block).</summary>
public sealed record TrackItemPlate(
    string MatchedText,
    TrackPlateMatch MatchKind,
    int SupportCount,
    int PlateObservationCount,
    int DistinctTextCount,
    double MaxConfidence,
    Guid BestPlateObservationId);

/// <summary>
/// Everything a continuation page of a plate search needs from its first page, carried inside the
/// authenticated v4 cursor and never recomputed: the keyset and snapshot, the plate identity the
/// first page pinned with its coverage, and — when analytic predicates are combined — the analytics
/// identity and coverage exactly as the v3 cursor would carry them (ADR-013 §16).
/// </summary>
public sealed record TrackPlateCursorPosition(
    TrackCursorPosition Position,
    string PlateIdentityFingerprint,
    TrackPlateCoverage PlateCoverage,
    TrackAnalyticsPinnedIdentity? AnalyticsIdentity = null,
    TrackAnalyticsCoverage? AnalyticsCoverage = null)
{
    public bool IsAnalytic => AnalyticsIdentity is not null;
}

/// <summary>One page of a plate search with what its first page resolved.</summary>
public sealed record TrackPlateSearchRepositoryPage(
    IReadOnlyList<TrackSearchRow> Items,
    DateTimeOffset SnapshotUtc,
    long SnapshotVisibilitySequence,
    TrackPlateCoverage PlateCoverage,
    IReadOnlyDictionary<Guid, TrackItemPlate> ItemPlates,
    TrackAnalyticsPinnedIdentity? AnalyticsIdentity = null,
    TrackAnalyticsCoverage? AnalyticsCoverage = null,
    IReadOnlyDictionary<Guid, TrackItemAnalytics>? ItemAnalytics = null,
    IReadOnlyList<PlateCoverageIntegrityFault>? IntegrityFaults = null);

/// <summary>
/// A Ready plate analysis whose header does not account for the run's Vehicle Tracks (PR-3 publishes one
/// outcome per Vehicle Track, so this is an integrity fault). Coverage used the Tracks' own count; this
/// carries ids and counts only, for the server log, never a plate value.
/// </summary>
public sealed record PlateCoverageIntegrityFault(Guid AnalysisId, Guid ProcessingRunId, int HeaderTracks, int VehicleTracks);

/// <summary>A page, or a refusal for the reasons an analytic search refuses (scope or geometry).</summary>
public sealed record TrackPlateSearchRepositoryResult(TrackPlateSearchRepositoryPage? Page)
{
    public bool IsValid => Page is not null;

    public static TrackPlateSearchRepositoryResult Invalid { get; } = new((TrackPlateSearchRepositoryPage?)null);
}

/// <summary>A plate analysis of one run as a search snapshot sees it.</summary>
public sealed record PlateCoverageAnalysis(
    Guid AnalysisId,
    string IdentityFingerprint,
    PlateAnalysisStatus Status,
    long? VisibilitySequence);

/// <summary>
/// The coverage bucket of one run, by the PR-3 readiness rule, as of a search snapshot: an analysis
/// published after the snapshot is not fact-bearing for it (it was still running), so it counts as
/// pending rather than ready.
/// </summary>
public static class PlateCoverageRule
{
    public static PlateReadinessState Classify(
        Guid processingRunId,
        string? pinnedFingerprint,
        IReadOnlyList<PlateCoverageAnalysis> analyses,
        long snapshotVisibilitySequence)
    {
        ArgumentNullException.ThrowIfNull(analyses);
        var facts = new PlateRunFacts(
            IsCompletedAndVisible: true,
            CompletedAtUtc: null,
            HasVehicleTracks: true,
            CurrentActivationAtUtc: null,
            analyses.Select(analysis => new PlateAnalysisFacts(
                    analysis.AnalysisId,
                    analysis.IdentityFingerprint,
                    AsOfSnapshot(analysis, snapshotVisibilitySequence),
                    0,
                    DateTimeOffset.UnixEpoch,
                    null,
                    null))
                .ToArray());
        return PlateReadinessRule.Evaluate(processingRunId, pinnedFingerprint, null, facts, null).State;
    }

    private static PlateAnalysisStatus AsOfSnapshot(PlateCoverageAnalysis analysis, long snapshotVisibilitySequence) =>
        analysis.Status is PlateAnalysisStatus.Completed or PlateAnalysisStatus.Superseded &&
        (analysis.VisibilitySequence is not { } sequence || sequence > snapshotVisibilitySequence)
            ? PlateAnalysisStatus.Running
            : analysis.Status;
}

/// <summary>
/// The agreement of a Track's plate observations (plan §2.7 as clarified by the owner on 2026-10-14,
/// the frozen rank-0 summary policy <c>plate-track-text-rank0</c>): derived from the <b>qualifying</b>
/// observations only — <c>Read</c> observations whose rank-0 reading normalises successfully under
/// <c>mavi-plate-normalisation-v1</c>. Rank &gt; 0 readings never count, and a Read observation whose
/// rank-0 reading is rejected supplies no Track text, so it cannot manufacture agreement. Observations
/// carrying the same rank-0 text are each counted; they are not collapsed first. Nothing here confirms
/// a plate.
/// </summary>
public static class PlateAgreementRule
{
    public const string NoReading = "none";
    public const string OneReading = "single";
    public const string Consistent = "consistent";
    public const string Conflicting = "conflicting";

    /// <summary>
    /// <c>none</c> — no qualifying observation; <c>single</c> — exactly one; <c>consistent</c> — two or
    /// more, with exactly one distinct normalised rank-0 text; <c>conflicting</c> — two or more distinct
    /// normalised rank-0 texts.
    /// </summary>
    /// <param name="qualifyingRank0Texts">The normalised rank-0 text of each qualifying observation, one entry per observation.</param>
    public static string Derive(IReadOnlyCollection<string> qualifyingRank0Texts)
    {
        ArgumentNullException.ThrowIfNull(qualifyingRank0Texts);
        if (qualifyingRank0Texts.Distinct(StringComparer.Ordinal).Count() >= 2)
            return Conflicting;
        return qualifyingRank0Texts.Count switch
        {
            0 => NoReading,
            1 => OneReading,
            _ => Consistent,
        };
    }

    /// <summary>The normalised rank-0 text of each qualifying observation, in the order given.</summary>
    public static IReadOnlyList<string> QualifyingRank0Texts(IEnumerable<TrackPlateObservationRow> observations)
    {
        ArgumentNullException.ThrowIfNull(observations);
        var texts = new List<string>();
        foreach (var observation in observations)
        {
            if (observation.Outcome != PlateObservationOutcome.Read)
                continue;
            var rank0 = observation.Readings.FirstOrDefault(reading => reading.Rank == 0);
            if (rank0 is { NormalisationOutcome: PlateNormalisationOutcome.Ok, NormalisedText: { Length: > 0 } text })
                texts.Add(text);
        }

        return texts;
    }
}

// --- Detail ----------------------------------------------------------------------------------

/// <summary>One kept reading as the detail reads it.</summary>
public sealed record TrackPlateReadingRow(
    int Rank,
    string RawText,
    int RawLineCount,
    string? NormalisedText,
    PlateNormalisationOutcome NormalisationOutcome,
    double Confidence,
    string? FormatClass);

/// <summary>One plate observation with its source Observation's evidence position and its readings.</summary>
public sealed record TrackPlateObservationRow(
    Guid PlateObservationId,
    Guid SourceObservationId,
    Domain.Intelligence.ObservationType Role,
    int EvidenceRank,
    int PlateIndex,
    long OffsetMs,
    long SourceFrameNumber,
    DateTimeOffset TimestampUtc,
    int BoxX,
    int BoxY,
    int BoxWidth,
    int BoxHeight,
    int CropWidth,
    int CropHeight,
    double DetectorConfidence,
    PlateObservationOutcome Outcome,
    IReadOnlyList<TrackPlateReadingRow> Readings);

public sealed record TrackPlateTextRow(string NormalisedText, int SupportCount, double MaxConfidence, Guid BestPlateObservationId);

/// <summary>The analysis behind the facts.</summary>
public sealed record TrackPlateProvenance(
    Guid AnalysisId,
    string PlateDetectorModelPackId,
    string OcrModelPackId,
    string NormalisationId,
    string NormalisationSha256,
    string SummaryPolicyId,
    string SummaryPolicyVersion,
    string SummaryPolicySha256,
    DateTimeOffset CompletedAtUtc);

/// <summary>
/// The default analysis's facts for one Track. <paramref name="Outcome"/> is null only when the
/// completed analysis has no outcome row for the Track, which its completion forbids; the detail then
/// reports it as unavailable without a reason rather than inventing facts.
/// </summary>
public sealed record TrackPlateFacts(
    PlateTrackOutcomeKind? Outcome,
    string? UnavailableReason,
    IReadOnlyList<TrackPlateTextRow> Texts,
    IReadOnlyList<TrackPlateObservationRow> Observations,
    TrackPlateProvenance Provenance)
{
    /// <summary>The derived agreement of an <c>Analysed</c> Track's qualifying observations; null otherwise.</summary>
    public string? Agreement => Outcome == PlateTrackOutcomeKind.Analysed
        ? PlateAgreementRule.Derive(PlateAgreementRule.QualifyingRank0Texts(Observations))
        : null;
}

/// <summary>A Vehicle Track's plate detail: its run's readiness and, when Ready, the default analysis's facts.</summary>
public sealed record TrackPlateDetail(PlateReadinessState Readiness, TrackPlateFacts? Facts);

/// <summary>The plate half of Track search and detail against the operational store.</summary>
public interface ITrackPlateSearchRepository
{
    /// <summary>
    /// A search carrying a plate predicate, coordinated as one operation. With no
    /// <paramref name="cursor"/>, the first page takes the shared visibility barrier, allocates the
    /// snapshot, resolves the analytic scope when analytic predicates are present (exactly as an
    /// analytic search does), computes both coverage blocks over the base candidate scope and fetches
    /// the page under <paramref name="preferredFingerprint"/>. With a cursor it evaluates against the
    /// pinned identities and snapshot and returns the pinned coverage untouched.
    /// </summary>
    Task<TrackPlateSearchRepositoryResult> SearchPlatesAsync(
        TrackSearchQuery query,
        string? preferredFingerprint,
        TrackPlateCursorPosition? cursor,
        int take,
        CancellationToken cancellationToken);

    /// <summary>The facts one analysis holds for one Track: header, outcome, texts and observations with readings.</summary>
    Task<TrackPlateFacts?> GetTrackPlateFactsAsync(
        Guid trackId,
        Guid analysisId,
        CancellationToken cancellationToken);
}
