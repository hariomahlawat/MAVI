using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// Opaque pagination cursors for Track search.
/// </summary>
/// <remarks>
/// <para>
/// Two envelopes share this codec and nothing else. <b>v2</b> is the ordinary cursor:
/// base64url of a small JSON payload, unsigned, because everything in it is either
/// public (the keyset position) or an equality check the server recomputes anyway (the
/// filter fingerprint). It is byte-for-byte what Task 14 shipped and Slice 4 does not
/// touch it.
/// </para>
/// <para>
/// <b>v3</b> is the analytic cursor. It carries state the server derived and must trust
/// on the way back — the pinned scene identity and the coverage snapshot — so its
/// payload is authenticated with HMAC-SHA-256 under the installation's
/// <see cref="TrackCursorSigningKey"/>. The envelope is base64url of
/// <c>mac(32 bytes) ‖ payload</c>, and decoding verifies the MAC in constant time
/// <i>before</i> the payload is parsed: nothing an attacker controls is deserialised
/// until it has been proven to be something this server produced.
/// </para>
/// <para>
/// The two are distinguishable only by which decoder accepts them, and each decoder
/// refuses the other's envelope: a v3 blob is not valid JSON to the v2 decoder, and a
/// v2 blob has no MAC for the v3 decoder to verify.
/// </para>
/// </remarks>
public static class TrackCursorCodec
{
    public const int MaximumEncodedLength = 512;

    /// <summary>
    /// The v3 envelope's own bound (plan §S). Pinned by a worst-case contract test so the
    /// coverage snapshot cannot grow without review.
    /// </summary>
    public const int AnalyticMaximumEncodedLength = 768;

    private const int MacByteLength = 32;
    private const int AnalyticVersion = 3;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public static string Encode(TrackCursorPosition position)
    {
        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new CursorPayload(
                2,
                position.SnapshotUtc.ToUniversalTime(),
                position.SnapshotVisibilitySequence,
                position.StartTimestampUtc.ToUniversalTime(),
                position.TrackId,
                position.FilterFingerprint),
            JsonOptions);

        var encoded = Convert.ToBase64String(payload)
            .TrimEnd('=')
            .Replace('+', '-')
            .Replace('/', '_');
        if (encoded.Length > MaximumEncodedLength)
            throw new InvalidOperationException(
                "Task 14 cursor exceeded its published size envelope.");
        return encoded;
    }

    public static bool TryDecode(string? cursor, out TrackCursorPosition? position)
    {
        position = null;
        if (string.IsNullOrWhiteSpace(cursor) ||
            cursor.Length > MaximumEncodedLength ||
            cursor.Any(character =>
                !(character is >= 'A' and <= 'Z' or
                  >= 'a' and <= 'z' or
                  >= '0' and <= '9' or '-' or '_')))
        {
            return false;
        }

        try
        {
            var base64 = cursor.Replace('-', '+').Replace('_', '/');
            var padding = base64.Length % 4;
            if (padding == 1)
                return false;
            if (padding != 0)
                base64 = base64.PadRight(base64.Length + (4 - padding), '=');

            var bytes = Convert.FromBase64String(base64);
            if (bytes.Length > MaximumEncodedLength)
                return false;

            var payload = JsonSerializer.Deserialize<CursorPayload>(bytes, JsonOptions);
            if (payload is null ||
                payload.Version != 2 ||
                payload.SnapshotVisibilitySequence <= 0 ||
                payload.TrackId == Guid.Empty ||
                payload.TrackId.Version != 7 ||
                payload.SnapshotUtc.Offset != TimeSpan.Zero ||
                payload.StartTimestampUtc.Offset != TimeSpan.Zero ||
                !IsSha256(payload.FilterFingerprint))
            {
                return false;
            }

            position = new TrackCursorPosition(
                payload.SnapshotUtc,
                payload.SnapshotVisibilitySequence,
                payload.StartTimestampUtc,
                payload.TrackId,
                payload.FilterFingerprint);
            return true;
        }
        catch (Exception exception) when (
            exception is FormatException or JsonException or ArgumentException)
        {
            return false;
        }
    }

    public static string ComputeFilterFingerprint(TrackSearchQuery query)
    {
        ArgumentNullException.ThrowIfNull(query);
        var payload = JsonSerializer.SerializeToUtf8Bytes(BaseFilters(query), JsonOptions);
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }

    // --- Analytic cursor (v3) ------------------------------------------------

    /// <summary>
    /// The fingerprint of an analytic search: the ordinary filters, the canonical
    /// analytic keys and the identity the first page resolved. Including the pinned pair
    /// is what lets a continuation detect that it is being replayed against a different
    /// revision or engine than the one it was minted for.
    /// </summary>
    public static string ComputeAnalyticFilterFingerprint(
        TrackSearchQuery query,
        TrackAnalyticsPinnedIdentity identity)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(identity);
        if (query.Analytics is not { } analytics)
            throw new ArgumentException("An analytic fingerprint needs an analytic query.", nameof(query));

        var canonical = TrackAnalyticsQueryRules.Canonicalise(analytics);
        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new AnalyticFilterPayload(
                BaseFilters(query),
                canonical.SceneRevisionId,
                canonical.AnalyticsAlgorithmVersion,
                canonical.ZoneId,
                canonical.ZoneRelation?.ToString(),
                canonical.MinDwellMs,
                canonical.LineId,
                canonical.CrossingDirection?.ToString(),
                canonical.MotionDirection,
                canonical.MinStationaryMs,
                canonical.Loitering,
                identity.CameraId,
                identity.SceneRevisionId,
                identity.AlgorithmVersion),
            JsonOptions);
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }

    public static string EncodeAnalytic(TrackAnalyticsCursorPosition cursor, TrackCursorSigningKey key)
    {
        ArgumentNullException.ThrowIfNull(cursor);
        ArgumentNullException.ThrowIfNull(key);

        var position = cursor.Position;
        var coverage = cursor.Coverage;
        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new AnalyticCursorPayload(
                AnalyticVersion,
                position.SnapshotUtc.ToUniversalTime(),
                position.SnapshotVisibilitySequence,
                position.StartTimestampUtc.ToUniversalTime(),
                position.TrackId,
                position.FilterFingerprint,
                cursor.Identity.CameraId,
                cursor.Identity.SceneRevisionId,
                cursor.Identity.AlgorithmVersion,
                // Fixed order, fixed length: the same eight counts the coverage record
                // declares, in declaration order. Names would cost half the envelope.
                [
                    coverage.EvaluatedRuns,
                    coverage.PendingRuns,
                    coverage.FailedRuns,
                    coverage.NotConfiguredRuns,
                    coverage.DisabledRuns,
                    coverage.StaleRuns,
                    coverage.AnalysedTracks,
                    coverage.UnavailableTracks,
                ]),
            JsonOptions);

        var envelope = new byte[MacByteLength + payload.Length];
        HMACSHA256.HashData(key.Bytes, payload, envelope.AsSpan(0, MacByteLength));
        payload.CopyTo(envelope, MacByteLength);

        var encoded = ToBase64Url(envelope);
        if (encoded.Length > AnalyticMaximumEncodedLength)
            throw new InvalidOperationException(
                "Analytic Track cursor exceeded its published size envelope.");
        return encoded;
    }

    /// <summary>
    /// Decodes and authenticates a v3 cursor. The MAC is verified in constant time
    /// before any byte of the payload is interpreted; a forged, tampered or foreign-key
    /// cursor is refused without its contents ever being parsed.
    /// </summary>
    public static bool TryDecodeAnalytic(
        string? cursor,
        TrackCursorSigningKey key,
        out TrackAnalyticsCursorPosition? position)
    {
        ArgumentNullException.ThrowIfNull(key);
        position = null;
        if (string.IsNullOrWhiteSpace(cursor) ||
            cursor.Length > AnalyticMaximumEncodedLength ||
            !IsBase64Url(cursor))
        {
            return false;
        }

        byte[] envelope;
        try
        {
            envelope = FromBase64Url(cursor);
        }
        catch (FormatException)
        {
            return false;
        }

        if (envelope.Length <= MacByteLength)
            return false;

        var payload = envelope.AsSpan(MacByteLength);
        Span<byte> expected = stackalloc byte[MacByteLength];
        HMACSHA256.HashData(key.Bytes, payload, expected);
        if (!CryptographicOperations.FixedTimeEquals(expected, envelope.AsSpan(0, MacByteLength)))
            return false;

        // Authenticated: from here on the payload is something this server wrote, and
        // the checks below guard against a stale format rather than an attacker.
        try
        {
            var parsed = JsonSerializer.Deserialize<AnalyticCursorPayload>(payload, JsonOptions);
            if (parsed is null ||
                parsed.V != AnalyticVersion ||
                parsed.Q <= 0 ||
                parsed.I == Guid.Empty ||
                parsed.I.Version != 7 ||
                parsed.S.Offset != TimeSpan.Zero ||
                parsed.T.Offset != TimeSpan.Zero ||
                !IsSha256(parsed.F) ||
                parsed.C == Guid.Empty ||
                parsed.R == Guid.Empty ||
                string.IsNullOrWhiteSpace(parsed.A) ||
                parsed.G is not { Length: 8 } ||
                parsed.G.Any(count => count < 0))
            {
                return false;
            }

            position = new TrackAnalyticsCursorPosition(
                new TrackCursorPosition(parsed.S, parsed.Q, parsed.T, parsed.I, parsed.F),
                new TrackAnalyticsPinnedIdentity(parsed.C, parsed.R, parsed.A),
                new TrackAnalyticsCoverage(
                    parsed.R,
                    parsed.A,
                    parsed.G[0],
                    parsed.G[1],
                    parsed.G[2],
                    parsed.G[3],
                    parsed.G[4],
                    parsed.G[5],
                    parsed.G[6],
                    parsed.G[7]));
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static FilterPayload BaseFilters(TrackSearchQuery query) => new(
        query.CameraId,
        query.VideoAssetId,
        query.ProcessingRunId,
        query.ObjectClass,
        query.FromUtc?.ToUniversalTime(),
        query.ToUtc?.ToUniversalTime(),
        query.MinimumDurationMs,
        query.MinimumConfidence);

    private static bool IsBase64Url(string value) =>
        value.All(character =>
            character is >= 'A' and <= 'Z' or
            >= 'a' and <= 'z' or
            >= '0' and <= '9' or '-' or '_');

    private static string ToBase64Url(byte[] bytes) =>
        Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private static byte[] FromBase64Url(string value)
    {
        var base64 = value.Replace('-', '+').Replace('_', '/');
        var padding = base64.Length % 4;
        if (padding == 1)
            throw new FormatException("Invalid base64url length.");
        if (padding != 0)
            base64 = base64.PadRight(base64.Length + (4 - padding), '=');
        return Convert.FromBase64String(base64);
    }

    private static bool IsSha256(string? value) =>
        value is { Length: 64 } &&
        value.All(character =>
            character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private sealed record CursorPayload(
        int Version,
        DateTimeOffset SnapshotUtc,
        long SnapshotVisibilitySequence,
        DateTimeOffset StartTimestampUtc,
        Guid TrackId,
        string FilterFingerprint);

    private sealed record FilterPayload(
        Guid? CameraId,
        Guid? VideoAssetId,
        Guid? ProcessingRunId,
        Mavi.Domain.Intelligence.ObjectClass? ObjectClass,
        DateTimeOffset? FromUtc,
        DateTimeOffset? ToUtc,
        long? MinimumDurationMs,
        double? MinimumConfidence);

    private sealed record AnalyticFilterPayload(
        FilterPayload Base,
        Guid? SceneRevisionId,
        string? AnalyticsAlgorithmVersion,
        Guid? ZoneId,
        string? ZoneRelation,
        long? MinDwellMs,
        Guid? LineId,
        string? CrossingDirection,
        string? MotionDirection,
        long? MinStationaryMs,
        bool Loitering,
        Guid PinnedCameraId,
        Guid? PinnedSceneRevisionId,
        string PinnedAlgorithmVersion);

    /// <summary>
    /// The v3 payload. Single-letter members because the envelope has a 768-character
    /// bound and the names are never read by anything but this codec: V version,
    /// S snapshot time, Q snapshot sequence, T keyset timestamp, I keyset Track id,
    /// F filter fingerprint, C camera, R revision (null = never configured),
    /// A algorithm version, G the eight coverage counts in declaration order.
    /// </summary>
    private sealed record AnalyticCursorPayload(
        int V,
        DateTimeOffset S,
        long Q,
        DateTimeOffset T,
        Guid I,
        string F,
        Guid C,
        Guid? R,
        string A,
        int[] G);
}
