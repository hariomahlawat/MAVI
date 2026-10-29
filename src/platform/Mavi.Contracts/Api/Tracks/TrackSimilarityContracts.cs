namespace Mavi.Contracts.Api.Tracks;

/// <summary>
/// Similarity results are <i>similarity candidates</i> (ADR-021 §5): ranked by cosine score under one embedding
/// identity, never identity, never grouped. Every surface carries <see cref="Label"/>.
/// </summary>
public static class TrackSimilarityContractRules
{
    public const string Label = "Similarity candidates — Development";

    public const string AppearanceQueryKey = "appearanceQuery";
    public const string AppearanceSnapshotKey = "appearanceSnapshot";

    public const int DefaultSimilarK = 20;
    public const int MaximumSimilarK = 50;
    public const int DefaultAppearanceLimit = 50;
    public const int MaximumAppearanceLimit = 100;

    public const string StateReady = "ready";
    public const string StatePending = "pending";
    public const string StateUnavailable = "unavailable";
    public const string StateNotConfigured = "notConfigured";
    /// <summary>The run has no analysis under the identity (it predates activation); an explicit re-analysis queues it.</summary>
    public const string StateNotAnalysed = "notAnalysed";
    /// <summary>The run's analysis failed (reason = its failure code); an explicit re-analysis requeues it.</summary>
    public const string StateFailed = "failed";
}

public sealed record SimilarityIdentityResponse(string Fingerprint, string ModelId, string ModelVersion);

public sealed record SimilarTrackCandidateResponse(
    int Rank,
    double Score,
    Guid? SourceObservationId,
    TrackSearchItemResponse Track);

/// <summary><c>GET /api/tracks/{id}/similar</c>: the query Track's state and, when ready, its ranked candidates.</summary>
public sealed record SimilarTracksResponse(
    string State,
    string? Reason,
    string Label,
    Guid QueryTrackId,
    SimilarityIdentityResponse? Identity,
    string? Snapshot,
    DateTimeOffset? SnapshotUtc,
    IReadOnlyList<SimilarTrackCandidateResponse> Candidates);

/// <summary>The <c>appearanceQuery</c> block of a Track search response.</summary>
public sealed record AppearanceSearchResponse(
    string Label,
    string IdentityFingerprint,
    string ModelId,
    string ModelVersion,
    string Snapshot,
    DateTimeOffset SnapshotUtc);
