using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Application.Modules.Intelligence;
using Mavi.Contracts.Api.Tracks;
using Mavi.Contracts.Worker.Embeddings;
using Mavi.Domain.Embeddings;
using Mavi.Domain.Intelligence;
using Microsoft.Extensions.Options;

namespace Mavi.Application.Modules.Embeddings;

/// <summary>The query Track's own vector state under one identity, inside a snapshot when one is pinned.</summary>
public sealed record SimilarityTrackState(Guid TrackId, ObjectClass ObjectClass, string State, string? Reason, float[]? Vector);

public sealed record SimilarityRankedRow(TrackSearchRow Row, double Score, Guid? SourceObservationId);

public sealed record SimilarityRankResult(IReadOnlyList<SimilarityRankedRow> Rows, long SnapshotVisibilitySequence, DateTimeOffset SnapshotUtc);

/// <summary>Exact cosine ranking over the base Track candidates of a snapshot (ADR-021 §4).</summary>
public interface ITrackSimilarityRepository
{
    Task<SimilarityTrackState?> GetTrackStateAsync(Guid trackId, string identityFingerprint, long? snapshotVisibilitySequence, CancellationToken cancellationToken);

    /// <param name="snapshotVisibilitySequence">A pinned snapshot, or null to take a new one under the shared barrier.</param>
    Task<SimilarityRankResult> RankAsync(
        TrackSearchQuery scope, float[] vector, string identityFingerprint, Guid? excludeTrackId, int take,
        long? snapshotVisibilitySequence, DateTimeOffset? snapshotUtc, CancellationToken cancellationToken);
}

public sealed record SimilarTracksQuery(int K, Guid? CameraId, ObjectClass? ObjectClass, DateTimeOffset? FromUtc, DateTimeOffset? ToUtc, string? Snapshot);

public sealed record SimilarTracksResult(
    string State,
    string? Reason,
    SimilarityIdentityResponse? Identity,
    string? Snapshot,
    DateTimeOffset? SnapshotUtc,
    IReadOnlyList<SimilarityRankedRow> Candidates,
    bool TrackFound = true,
    string? ErrorCode = null);

public sealed record AppearanceSearchResult(
    string? ErrorCode,
    int HttpStatus,
    IReadOnlyList<SimilarityRankedRow> Rows,
    AppearanceSearchResponse? Appearance);

/// <summary>
/// "Find similar" and the appearance text query (ADR-021 §4–§5): similarity candidates ranked by cosine score
/// under the release's embedding identity, inside a signed snapshot that a replay reproduces exactly. Nothing here
/// writes a Track, an Entity or an <c>EntityId</c>.
/// </summary>
public sealed class TrackSimilarityService(
    ITrackSimilarityRepository repository,
    IEmbeddingRelease release,
    IEmbeddingLifecycle lifecycle,
    TrackCursorSigningKey signingKey,
    TimeProvider timeProvider,
    IOptions<EmbeddingOptions> options)
{
    public const string InvalidCode = "similarity_query_invalid";
    public const string AppearanceInvalidCode = "appearance_query_invalid";
    public const string AppearancePendingCode = "appearance_query_pending";
    public const string AppearanceFailedCode = "appearance_query_failed";
    public const string NotConfiguredCode = "embeddings_not_configured";
    public const string ClassNotEmbeddedReason = "class_not_embedded";
    public const string AppearanceBusyCode = "appearance_query_queue_full";

    /// <summary>
    /// At most this many requests wait for a new text's vector at once, process-wide (each holds a connection slot
    /// while it polls); the rest answer 503 at once instead of piling up (review Minor 1).
    /// </summary>
    public const int MaximumConcurrentWaiters = 8;

    private static readonly SemaphoreSlim Waiters = new(MaximumConcurrentWaiters, MaximumConcurrentWaiters);

    public async Task<SimilarTracksResult> FindSimilarAsync(Guid trackId, SimilarTracksQuery query, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(query);
        if (query.K is < 1 or > TrackSimilarityContractRules.MaximumSimilarK || (query.FromUtc is { } from && query.ToUtc is { } to && from >= to))
            return Error(InvalidCode);
        if (release.Resolution.Definition is not { } definition)
            return new SimilarTracksResult(TrackSimilarityContractRules.StateNotConfigured, null, null, null, null, []);

        var identity = definition.Identity;
        SimilaritySnapshot? pinned = null;
        if (query.Snapshot is not null)
        {
            pinned = SimilaritySnapshotCodec.TryDecode(query.Snapshot, signingKey, timeProvider.GetUtcNow());
            if (pinned is null || pinned.Kind != SimilaritySnapshotCodec.SimilarKind || pinned.IdentityFingerprint != identity.Fingerprint)
                return Error(InvalidCode);
        }

        var state = await repository.GetTrackStateAsync(trackId, identity.Fingerprint, pinned?.SnapshotVisibilitySequence, cancellationToken);
        if (state is null) return Error("track_not_found") with { TrackFound = false };

        var identityResponse = new SimilarityIdentityResponse(identity.Fingerprint, identity.ModelId, identity.ModelVersion);
        if (!definition.ObjectClasses.Contains(state.ObjectClass.ToString()))
            return new SimilarTracksResult(TrackSimilarityContractRules.StateUnavailable, ClassNotEmbeddedReason, identityResponse, null, null, []);
        if (state.State != TrackSimilarityContractRules.StateReady || state.Vector is not { } vector)
            return new SimilarTracksResult(state.State, state.Reason, identityResponse, null, null, []);

        var scope = new TrackSearchQuery(query.CameraId, null, null, query.ObjectClass ?? state.ObjectClass, query.FromUtc, query.ToUtc,
            null, null, null, query.K);
        var fingerprint = SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.SimilarKind, trackId.ToString("D"), query.K, scope,
            identity.Fingerprint, signingKey);
        if (pinned is not null && pinned.FilterFingerprint != fingerprint) return Error(InvalidCode);

        var ranked = await repository.RankAsync(scope, vector, identity.Fingerprint, trackId, query.K,
            pinned?.SnapshotVisibilitySequence, pinned?.SnapshotUtc, cancellationToken);
        var snapshot = SimilaritySnapshotCodec.Encode(new SimilaritySnapshot(SimilaritySnapshotCodec.SimilarKind, fingerprint,
            identity.Fingerprint, ranked.SnapshotVisibilitySequence, ranked.SnapshotUtc), signingKey);
        return new SimilarTracksResult(TrackSimilarityContractRules.StateReady, null, identityResponse, snapshot, ranked.SnapshotUtc, ranked.Rows);
    }

    /// <summary>
    /// Ranks the base candidates of <paramref name="scope"/> by text→image cosine. A text not yet embedded is queued
    /// and waited for a bounded time, then answered <c>appearance_query_pending</c> (503).
    /// </summary>
    public async Task<AppearanceSearchResult> SearchAppearanceAsync(
        TrackSearchQuery scope, string? text, string? snapshotToken, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(scope);
        if (release.Resolution.Definition is not { } definition)
            return new AppearanceSearchResult(NotConfiguredCode, 409, [], null);
        if (EmbeddingContractRules.NormaliseAppearanceText(text) is not { } normalised ||
            scope.Limit is < 1 or > TrackSimilarityContractRules.MaximumAppearanceLimit)
            return new AppearanceSearchResult(AppearanceInvalidCode, 400, [], null);

        var identity = definition.Identity;
        var fingerprint = SimilaritySnapshotCodec.FilterFingerprint(SimilaritySnapshotCodec.AppearanceKind, normalised, scope.Limit, scope,
            identity.Fingerprint, signingKey);
        SimilaritySnapshot? pinned = null;
        if (snapshotToken is not null)
        {
            pinned = SimilaritySnapshotCodec.TryDecode(snapshotToken, signingKey, timeProvider.GetUtcNow());
            if (pinned is null || pinned.Kind != SimilaritySnapshotCodec.AppearanceKind ||
                pinned.IdentityFingerprint != identity.Fingerprint || pinned.FilterFingerprint != fingerprint)
                return new AppearanceSearchResult(AppearanceInvalidCode, 400, [], null);
        }

        AppearanceQueryEmbedding query;
        try
        {
            query = await lifecycle.RequestTextAsync(identity.Fingerprint, normalised, cancellationToken);
        }
        catch (EmbeddingTextQueueFullException)
        {
            return new AppearanceSearchResult(AppearanceBusyCode, 503, [], null);
        }

        if (query.Status is AppearanceQueryStatus.Pending or AppearanceQueryStatus.Running && options.Value.AppearanceQueryWaitMilliseconds > 0 &&
            await Waiters.WaitAsync(0, cancellationToken))
        {
            try
            {
                var deadline = timeProvider.GetUtcNow().AddMilliseconds(options.Value.AppearanceQueryWaitMilliseconds);
                while (query.Status is AppearanceQueryStatus.Pending or AppearanceQueryStatus.Running && timeProvider.GetUtcNow() < deadline)
                {
                    await Task.Delay(TimeSpan.FromMilliseconds(200), timeProvider, cancellationToken);
                    query = await lifecycle.GetTextAsync(query.Id, cancellationToken) ?? query;
                }
            }
            finally
            {
                Waiters.Release();
            }
        }

        if (query.Status == AppearanceQueryStatus.Failed) return new AppearanceSearchResult(AppearanceFailedCode, 422, [], null);
        if (query.Status != AppearanceQueryStatus.Completed || query.Embedding is not { } vector)
            return new AppearanceSearchResult(AppearancePendingCode, 503, [], null);

        var ranked = await repository.RankAsync(scope, vector, identity.Fingerprint, null, scope.Limit,
            pinned?.SnapshotVisibilitySequence, pinned?.SnapshotUtc, cancellationToken);
        var snapshot = SimilaritySnapshotCodec.Encode(new SimilaritySnapshot(SimilaritySnapshotCodec.AppearanceKind, fingerprint,
            identity.Fingerprint, ranked.SnapshotVisibilitySequence, ranked.SnapshotUtc), signingKey);
        return new AppearanceSearchResult(null, 200, ranked.Rows, new AppearanceSearchResponse(TrackSimilarityContractRules.Label,
            identity.Fingerprint, identity.ModelId, identity.ModelVersion, snapshot, ranked.SnapshotUtc));
    }

    private static SimilarTracksResult Error(string code) => new(string.Empty, null, null, null, null, [], true, code);
}

public sealed record SimilaritySnapshot(string Kind, string FilterFingerprint, string IdentityFingerprint, long SnapshotVisibilitySequence, DateTimeOffset SnapshotUtc);

/// <summary>
/// The similarity snapshot token (ADR-021 §4): base64url of <c>HMAC-SHA-256 ‖ payload</c> under a key derived
/// from the installation's cursor signing key with its own label, verified in constant time before the payload is
/// parsed. Its filter fingerprint is keyed with a second derived key, so the appearance text cannot be recovered
/// from a token. Valid for one hour, as Track cursors are.
/// </summary>
public static class SimilaritySnapshotCodec
{
    public const string SimilarKind = "similar";
    public const string AppearanceKind = "appearance";

    /// <summary>"Find this face" (ADR-022 §7) reuses the token, under its own kind.</summary>
    public const string FaceKind = "face";
    public const string MacKeyLabel = "mavi-similarity-snapshot-v1/mac";
    public const string FingerprintKeyLabel = "mavi-similarity-snapshot-v1/filter-fingerprint";
    public const int MaximumEncodedLength = 512;
    public static readonly TimeSpan Validity = TimeSpan.FromHours(1);

    private const int Version = 1;
    private const int MacByteLength = 32;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public static string FilterFingerprint(string kind, string target, int take, TrackSearchQuery scope, string identityFingerprint, TrackCursorSigningKey key)
    {
        ArgumentNullException.ThrowIfNull(scope);
        var payload = JsonSerializer.SerializeToUtf8Bytes(new FilterPayload(kind, target, take, scope.CameraId, scope.VideoAssetId,
            scope.ProcessingRunId, scope.ObjectClass?.ToString(), scope.FromUtc?.ToUniversalTime(), scope.ToUtc?.ToUniversalTime(),
            scope.MinimumDurationMs, scope.MinimumConfidence, scope.ObjectSubclass, identityFingerprint), JsonOptions);
        return Convert.ToHexString(HMACSHA256.HashData(Derive(key, FingerprintKeyLabel), payload)).ToLowerInvariant();
    }

    public static string Encode(SimilaritySnapshot snapshot, TrackCursorSigningKey key)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        var payload = JsonSerializer.SerializeToUtf8Bytes(new SnapshotPayload(Version, snapshot.Kind, snapshot.FilterFingerprint,
            snapshot.IdentityFingerprint, snapshot.SnapshotVisibilitySequence, snapshot.SnapshotUtc.ToUniversalTime()), JsonOptions);
        var envelope = new byte[MacByteLength + payload.Length];
        HMACSHA256.HashData(Derive(key, MacKeyLabel), payload, envelope.AsSpan(0, MacByteLength));
        payload.CopyTo(envelope, MacByteLength);
        var encoded = Convert.ToBase64String(envelope).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        if (encoded.Length > MaximumEncodedLength) throw new InvalidOperationException("Similarity snapshot exceeded its size envelope.");
        return encoded;
    }

    public static SimilaritySnapshot? TryDecode(string? token, TrackCursorSigningKey key, DateTimeOffset nowUtc)
    {
        if (token is not { Length: > 0 and <= MaximumEncodedLength } ||
            !token.All(character => character is >= 'A' and <= 'Z' or >= 'a' and <= 'z' or >= '0' and <= '9' or '-' or '_'))
            return null;
        byte[] envelope;
        try
        {
            var base64 = token.Replace('-', '+').Replace('_', '/');
            envelope = Convert.FromBase64String(base64.PadRight(base64.Length + (4 - base64.Length % 4) % 4, '='));
        }
        catch (FormatException)
        {
            return null;
        }

        if (envelope.Length <= MacByteLength) return null;
        Span<byte> expected = stackalloc byte[MacByteLength];
        HMACSHA256.HashData(Derive(key, MacKeyLabel), envelope.AsSpan(MacByteLength), expected);
        if (!CryptographicOperations.FixedTimeEquals(expected, envelope.AsSpan(0, MacByteLength))) return null;
        try
        {
            var parsed = JsonSerializer.Deserialize<SnapshotPayload>(envelope.AsSpan(MacByteLength), JsonOptions);
            if (parsed is null || parsed.V != Version || parsed.K is not (SimilarKind or AppearanceKind or FaceKind) ||
                !EmbeddingContractRules.IsCanonicalSha256(parsed.F) || !EmbeddingContractRules.IsCanonicalSha256(parsed.I) ||
                parsed.Q < 1 || parsed.S.Offset != TimeSpan.Zero || parsed.S > nowUtc || parsed.S < nowUtc - Validity)
                return null;
            return new SimilaritySnapshot(parsed.K, parsed.F, parsed.I, parsed.Q, parsed.S);
        }
        catch (JsonException)
        {
            return null;
        }
    }

    private static byte[] Derive(TrackCursorSigningKey key, string label)
    {
        ArgumentNullException.ThrowIfNull(key);
        return HMACSHA256.HashData(key.Bytes, System.Text.Encoding.ASCII.GetBytes(label));
    }

    private sealed record SnapshotPayload(int V, string K, string F, string I, long Q, DateTimeOffset S);

    private sealed record FilterPayload(
        string Kind,
        string Target,
        int Take,
        Guid? CameraId,
        Guid? VideoAssetId,
        Guid? ProcessingRunId,
        string? ObjectClass,
        DateTimeOffset? FromUtc,
        DateTimeOffset? ToUtc,
        long? MinimumDurationMs,
        double? MinimumConfidence,
        string? ObjectSubclass,
        string Identity);
}
