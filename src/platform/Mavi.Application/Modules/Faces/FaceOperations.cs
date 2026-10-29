using Mavi.Application.Modules.Embeddings;
using Mavi.Application.Modules.Intelligence;
using Mavi.Domain.Faces;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Modules.Faces;

public sealed record FaceBox(double X, double Y, double Width, double Height);

/// <summary>One face of a completed query, as stored on the query (no vector, no image).</summary>
public sealed record FaceQueryFace(int FaceIndex, FaceBox Box, float[] Landmarks, double Score, bool Usable);

/// <summary>One detected face of a Person Track: where it is on which evidence crop, and whether it was embedded.</summary>
public sealed record TrackFace(Guid FaceId, Guid ObservationId, Guid? ArtifactId, FaceBox Box, float[] Landmarks, double Score, bool Usable);

/// <summary>
/// A Person Track's face state under the pinned identity (ADR-022 §1): <c>observed</c>, <c>unknown</c> with a reason,
/// <c>pending</c>, <c>failed</c> with a code, <c>notAnalysed</c>, <c>notEnabled</c> (the camera is not opted in) or
/// <c>notPerson</c>.
/// </summary>
public sealed record TrackFacesView(string State, string? Reason, IReadOnlyList<TrackFace> Faces);

public static class FaceStates
{
    public const string Observed = "observed";
    public const string Unknown = "unknown";
    public const string Pending = "pending";
    public const string Failed = "failed";
    public const string NotAnalysed = "notAnalysed";
    public const string NotEnabled = "notEnabled";
    public const string NotPerson = "notPerson";
}

/// <summary>A search or comparison source: a face of a Track, or a face of a transient query image.</summary>
public sealed record FaceSource(Guid? FaceId, Guid? QueryId, int? FaceIndex)
{
    public bool IsValid => FaceId is not null
        ? QueryId is null && FaceIndex is null
        : QueryId is not null && FaceIndex is >= 0 and < 1000;

    /// <summary>The source's canonical text, bound into the snapshot fingerprint.</summary>
    public string Canonical => FaceId is { } face ? $"face:{face:D}" : $"query:{QueryId:D}:{FaceIndex}";
}

/// <summary>The resolved source face's vector (and what a gallery template needs from it).</summary>
public sealed record ResolvedFace(float[] Vector, Guid? FaceObservationId, byte[]? Thumbnail);

public sealed record FaceSourceResolution(ResolvedFace? Face, string? RefusalCode);

public sealed record FaceCandidateRow(
    Guid TrackId,
    Guid ProcessingRunId,
    Guid CameraId,
    string CameraName,
    DateTimeOffset StartTimestampUtc,
    double Score,
    Guid FaceId,
    Guid ObservationId,
    Guid? ArtifactId,
    FaceBox Box);

public sealed record FaceRankResult(IReadOnlyList<FaceCandidateRow> Rows, long SnapshotVisibilitySequence, DateTimeOffset SnapshotUtc);

public sealed record GalleryCandidate(Guid EnrolledPersonId, string Label, double Score);

public sealed record GalleryTemplateView(
    Guid TemplateId, EnrolledFaceSource SourceKind, Guid? SourceFaceId, Guid? SourceObservationId, Guid? SourceArtifactId, FaceBox? Box,
    byte[]? Thumbnail, DateTimeOffset CreatedAtUtc);

public sealed record GalleryEntryView(
    Guid EnrolledPersonId, string Label, string? Note, DateTimeOffset CreatedAtUtc, DateTimeOffset UpdatedAtUtc,
    IReadOnlyList<GalleryTemplateView> Templates);

public sealed record FaceQueryView(Guid QueryId, FaceQueryStatus Status, string? FailureCode, IReadOnlyList<FaceQueryFace> Faces,
    IReadOnlyDictionary<int, byte[]?> Thumbnails, DateTimeOffset CreatedAtUtc, DateTimeOffset PurgeAfterUtc);

/// <summary>Too many query images already wait for the worker; the caller retries later.</summary>
public sealed class FaceQueryQueueFullException() : InvalidOperationException("face_query_queue_full");

/// <summary>
/// The operator side of ADR-022 against PostgreSQL. Mutations save on the request's scoped context without opening
/// their own transaction, so <c>IAuditWriter.RecordAsync</c> commits each with its audit row. Nothing here stores a
/// match: no table links a Track or a face to an enrolled person (ADR-022 §1).
/// </summary>
public interface IFaceRepository
{
    /// <summary>Sets the camera's switch; switching off deletes its face analyses (and with them every face row). Null when the camera is unknown.</summary>
    Task<int?> SetCameraFaceAnalysisAsync(Guid cameraId, bool enabled, CancellationToken cancellationToken);

    /// <summary>Null when the Track is unknown.</summary>
    Task<TrackFacesView?> GetTrackFacesAsync(Guid trackId, string identityFingerprint, CancellationToken cancellationToken);

    Task<FaceQuery> CreateQueryAsync(string identityFingerprint, byte[] image, string mimeType, int maximumPending, CancellationToken cancellationToken);

    Task<FaceQueryView?> GetQueryAsync(Guid queryId, CancellationToken cancellationToken);

    Task<FaceSourceResolution> ResolveAsync(FaceSource source, string identityFingerprint, CancellationToken cancellationToken);

    /// <summary>
    /// Exact ranking of Person Tracks by their best face cosine to <paramref name="vector"/> under one identity, inside
    /// a snapshot (pinned, or new under the shared barrier), ordered by score descending then Track id.
    /// </summary>
    Task<FaceRankResult> RankAsync(float[] vector, string identityFingerprint, Guid? excludeFaceId, int take,
        long? snapshotVisibilitySequence, DateTimeOffset? snapshotUtc, CancellationToken cancellationToken);

    /// <summary>Enrolled persons whose best template under the identity reaches <paramref name="threshold"/>, best first.</summary>
    Task<IReadOnlyList<GalleryCandidate>> CompareGalleryAsync(float[] vector, string identityFingerprint, double threshold, int take,
        CancellationToken cancellationToken);

    Task<IReadOnlyList<GalleryEntryView>> ListGalleryAsync(CancellationToken cancellationToken);

    Task<GalleryEntryView?> GetGalleryEntryAsync(Guid enrolledPersonId, CancellationToken cancellationToken);

    Task<Guid> EnrolAsync(string? label, string? note, ResolvedFace face, string identityFingerprint, CancellationToken cancellationToken);

    /// <summary>False when the entry is unknown.</summary>
    Task<bool> UpdateGalleryEntryAsync(Guid enrolledPersonId, string? label, string? note, bool noteGiven, CancellationToken cancellationToken);

    /// <summary>Null when the entry is unknown.</summary>
    Task<Guid?> AddTemplateAsync(Guid enrolledPersonId, ResolvedFace face, string identityFingerprint, CancellationToken cancellationToken);

    Task<bool> DeleteTemplateAsync(Guid enrolledPersonId, Guid templateId, CancellationToken cancellationToken);

    /// <summary>Hard delete of the entry, its templates and thumbnails; false when unknown.</summary>
    Task<bool> DeleteGalleryEntryAsync(Guid enrolledPersonId, CancellationToken cancellationToken);
}

/// <summary>
/// "Find this face" and the gallery comparison (ADR-022 §1, §7): candidates with score, the identity's reference
/// threshold and whether each is above it, inside a signed snapshot that a replay reproduces exactly. A candidate is
/// never identity, and nothing here writes a Track, an Entity or a match.
/// </summary>
public sealed class FaceSearchService(IFaceRepository repository, TrackCursorSigningKey signingKey, TimeProvider timeProvider)
{
    public const string InvalidCode = "face_search_invalid";
    public const int MaximumK = 50;
    public const int DefaultK = 20;
    public const int GalleryCandidates = 3;

    public sealed record SearchResult(string? ErrorCode, int HttpStatus, IReadOnlyList<FaceCandidateRow> Candidates, string? Snapshot,
        DateTimeOffset? SnapshotUtc);

    public async Task<SearchResult> FindAsync(FaceReleaseDefinition definition, FaceSource source, int? k, string? snapshotToken,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(source);
        var take = k ?? DefaultK;
        if (!source.IsValid || take is < 1 or > MaximumK) return new(InvalidCode, 400, [], null, null);
        var identity = definition.Identity.Fingerprint;
        var scope = new TrackSearchQuery(null, null, null, ObjectClass.Person, null, null, null, null, null, take);
        var fingerprint = SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.FaceKind, source.Canonical, take, scope, identity,
            signingKey);
        SimilaritySnapshot? pinned = null;
        if (snapshotToken is not null)
        {
            pinned = SimilaritySnapshotCodec.TryDecode(snapshotToken, signingKey, timeProvider.GetUtcNow());
            if (pinned is null || pinned.Kind != SimilaritySnapshotCodec.FaceKind || pinned.IdentityFingerprint != identity ||
                pinned.FilterFingerprint != fingerprint)
                return new(InvalidCode, 400, [], null, null);
        }

        var resolved = await repository.ResolveAsync(source, identity, cancellationToken);
        if (resolved.Face is not { } face) return new(resolved.RefusalCode, StatusFor(resolved.RefusalCode), [], null, null);
        var ranked = await repository.RankAsync(face.Vector, identity, source.FaceId, take, pinned?.SnapshotVisibilitySequence,
            pinned?.SnapshotUtc, cancellationToken);
        var snapshot = SimilaritySnapshotCodec.Encode(new SimilaritySnapshot(SimilaritySnapshotCodec.FaceKind, fingerprint, identity,
            ranked.SnapshotVisibilitySequence, ranked.SnapshotUtc), signingKey);
        return new(null, 200, ranked.Rows, snapshot, ranked.SnapshotUtc);
    }

    public sealed record CompareResult(string? ErrorCode, int HttpStatus, IReadOnlyList<GalleryCandidate> Candidates);

    public async Task<CompareResult> CompareAsync(FaceReleaseDefinition definition, FaceSource source, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(definition);
        ArgumentNullException.ThrowIfNull(source);
        if (!source.IsValid) return new(InvalidCode, 400, []);
        var resolved = await repository.ResolveAsync(source, definition.Identity.Fingerprint, cancellationToken);
        if (resolved.Face is not { } face) return new(resolved.RefusalCode, StatusFor(resolved.RefusalCode), []);
        var candidates = await repository.CompareGalleryAsync(face.Vector, definition.Identity.Fingerprint, definition.ReferenceThreshold.Cosine,
            GalleryCandidates, cancellationToken);
        return new(null, 200, candidates);
    }

    public static int StatusFor(string? code) => code is FaceSourceCodes.NotFound ? 404 : 409;
}

public static class FaceSourceCodes
{
    public const string NotFound = "face_source_not_found";

    /// <summary>The source face exists but has no vector under the pinned identity (too small, or another identity).</summary>
    public const string NotUsable = "face_source_not_usable";

    public const string QueryNotReady = "face_query_not_ready";
}
