using System.Text.Json.Serialization;

namespace Mavi.Contracts.Api.Tracks;

// The Stage-4 plate additions to the Track contracts (plan §5.4). Every member list here is pinned
// by a wire test; an optional member is omitted when null, as the established Track contracts do.

/// <summary>
/// Why a search row matched a <c>plateText</c> predicate: the Track text that matched, how, and how
/// strongly it is supported. Never "the plate": a Track may carry several texts.
/// </summary>
/// <param name="MatchedText">The normalised Track text that matched; when several did, the best supported.</param>
/// <param name="MatchKind"><c>contains</c>, <c>prefix</c> or <c>exact</c>: the request's (defaulted) match mode.</param>
/// <param name="SupportCount">Plate observations whose rank-0 reading normalises to <paramref name="MatchedText"/>.</param>
/// <param name="PlateObservationCount">All plate observations of the Track in this analysis, unreadable ones included.</param>
/// <param name="DistinctTextCount">Distinct searchable texts of the Track; above one the readings conflict.</param>
/// <param name="MaxConfidence">The best model confidence among the supporting readings, in [0,1].</param>
/// <param name="BestPlateObservationId">The plate observation that carries <paramref name="MaxConfidence"/>.</param>
public sealed record TrackItemPlateResponse(
    string MatchedText,
    string MatchKind,
    int SupportCount,
    int PlateObservationCount,
    int DistinctTextCount,
    double MaxConfidence,
    Guid BestPlateObservationId);

/// <summary>
/// How much of a plate search's scope had plate readings to search, in Vehicle Tracks of the base
/// candidate scope (every ordinary filter, before the plate and analytic predicates). It is always
/// returned when <c>plateText</c> is present, so an empty page is never read as "no such plate".
/// The five buckets partition <paramref name="VehicleTracksInScope"/>.
/// </summary>
/// <param name="IdentityFingerprint">
/// The plate analysis identity the search was pinned to (64 hex), or null when no plate capability
/// is configured in the release.
/// </param>
public sealed record PlateCoverageResponse(
    string? IdentityFingerprint,
    int VehicleTracksInScope,
    int Ready,
    int Pending,
    int Failed,
    int Stale,
    int NotConfigured);

/// <summary>
/// A Vehicle Track's plate evidence on the detail surface (plan §5.4). Person Tracks omit the block.
/// </summary>
/// <param name="Readiness">One of <see cref="TrackSearchContractRules.PlateReadinessValues"/> for the Track's run.</param>
/// <param name="TrackOutcome"><c>Analysed</c> or <c>Unavailable</c>; present only when <paramref name="Readiness"/> is <c>Ready</c>.</param>
/// <param name="UnavailableReason">The persisted reason of an <c>Unavailable</c> outcome.</param>
/// <param name="Agreement">One of <see cref="TrackSearchContractRules.PlateAgreementValues"/>; present only for an <c>Analysed</c> Track.</param>
/// <param name="Texts">The Track texts, best supported first; empty unless analysed with a searchable reading.</param>
/// <param name="Observations">
/// Every plate observation, Unreadable ones included, in evidence order: the selected plate of each scored
/// crop. An abstained crop — including an OCR-output-fault abstention, which keeps its detector proposals
/// but not its readings (ADR-013 item 15) — and an excluded or unavailable crop have no entry; their record
/// is the sealed <c>PlatePredictions</c> artefact.
/// </param>
/// <param name="Provenance">The default analysis that produced the facts; present only when <paramref name="Readiness"/> is <c>Ready</c>.</param>
public sealed record TrackPlatesResponse(
    string Readiness,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? TrackOutcome,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? UnavailableReason,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? Agreement,
    IReadOnlyList<TrackPlateTextResponse> Texts,
    IReadOnlyList<TrackPlateObservationResponse> Observations,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    TrackPlateProvenanceResponse? Provenance);

/// <summary>One distinct searchable text of the Track (a search-acceleration fact, never "the plate").</summary>
public sealed record TrackPlateTextResponse(
    string NormalisedText,
    int SupportCount,
    double MaxConfidence,
    Guid BestPlateObservationId);

/// <summary>
/// One selected plate of one evidence crop. The plate region is <see cref="Box"/> in the decoded
/// pixel space of the source Observation's sealed crop; the UI cuts it from that crop's existing
/// content URL (ADR-013 implementation amendment 2026-10-13, item 12).
/// </summary>
/// <param name="Role">The source Observation's evidence role, as <c>observations[].evidenceRole</c> spells it.</param>
/// <param name="Outcome"><c>Read</c> or <c>Unreadable</c>; an Unreadable plate has no readings.</param>
public sealed record TrackPlateObservationResponse(
    Guid PlateObservationId,
    Guid SourceObservationId,
    string Role,
    long OffsetMs,
    long SourceFrameNumber,
    DateTimeOffset TimestampUtc,
    TrackPlateBoxResponse Box,
    double DetectorConfidence,
    string Outcome,
    IReadOnlyList<TrackPlateReadingResponse> Readings);

/// <summary>The plate box and the decoded crop size it lies in, in integer crop pixels.</summary>
public sealed record TrackPlateBoxResponse(int X, int Y, int Width, int Height, int CropWidth, int CropHeight);

/// <summary>
/// One kept reading. <see cref="RawText"/> is the immutable OCR output (a two-line reading joins its
/// lines with one LF); <see cref="NormalisedText"/> and <see cref="FormatClass"/> are present only
/// when <see cref="NormalisationOutcome"/> is <c>ok</c>. A <c>rejected</c> reading stays visible and
/// is never searchable. <see cref="Confidence"/> is the recogniser's confidence in the <b>whole</b>
/// reading: Stage 4 records no per-character confidence (ADR-013 item 13), and nothing here implies one.
/// Ranks follow confidence descending, ties by raw text in ordinal order (PR-3's reading order).
/// </summary>
public sealed record TrackPlateReadingResponse(
    int Rank,
    string RawText,
    int RawLineCount,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? NormalisedText,
    string NormalisationOutcome,
    double Confidence,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    string? FormatClass);

/// <summary>The default plate analysis behind a Track's plate facts.</summary>
public sealed record TrackPlateProvenanceResponse(
    Guid AnalysisId,
    string PlateDetectorModelPackId,
    string OcrModelPackId,
    TrackPlateNormalisationResponse Normalisation,
    TrackPlateSummaryPolicyResponse SummaryPolicy,
    DateTimeOffset CompletedAtUtc);

public sealed record TrackPlateNormalisationResponse(string Id, string Sha256);

public sealed record TrackPlateSummaryPolicyResponse(string Id, string Version, string Sha256);
