using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Api.Tracks;

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
/// <b>v4</b> is the plate cursor (Stage 4; ADR-013 §16, implemented here for the first time). It
/// is the v3 envelope — base64url of <c>mac ‖ payload</c> under the same key, verified before it is
/// parsed — around a payload that pins, besides the keyset and snapshot, a list of
/// capability-tagged derived-predicate identities (today exactly one, <c>plates</c>: the plate
/// identity fingerprint and the plate coverage counts) and, only when analytic predicates are
/// combined, the analytics identity and coverage a v3 cursor would carry. The tag is what lets a
/// later cross-camera derived predicate (visual attributes) join the list without a v5.
/// </para>
/// <para>
/// The envelopes are distinguishable only by which decoder accepts them, and each decoder
/// refuses the others': a v3 or v4 blob is not valid JSON to the v2 decoder, a v2 blob has
/// no MAC for the v3 or v4 decoder to verify, and an authenticated v3 or v4 payload carries
/// a version and a member set the other decoder refuses. Older versions keep their own
/// policy: v2 and v3 cursors are decoded only by their own paths, and a cursor of either
/// presented to a plate search is a 400, as any cursor minted for a different query is.
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

    /// <summary>
    /// The v4 envelope's bound (plan §5.4). Pinned by a worst-case contract test: the largest counts,
    /// the longest algorithm version and the analytics pin together stay inside it.
    /// </summary>
    public const int PlateMaximumEncodedLength = 1024;

    /// <summary>The capability tag of the plate identity among a v4 cursor's derived pins.</summary>
    public const string PlateCapabilityTag = "plates";

    /// <summary>The capability tag of the visual-attribute identity among a v4 cursor's derived pins (PoC S5).</summary>
    public const string AttributeCapabilityTag = "attributes";

    /// <summary>The fixed attribute coverage counts before the per-predicate Unknown counts.</summary>
    private const int AttributeCoverageFixedCountLength = 4;

    private const int MacByteLength = 32;
    private const int AnalyticVersion = 3;
    private const int PlateVersion = 4;
    private const int PlateCoverageCountLength = 6;
    private const int AnalyticsCoverageCountLength = 8;

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
        RequireNoPlate(query);
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
        if (query.Analytics is null)
            throw new ArgumentException("An analytic fingerprint needs an analytic query.", nameof(query));
        RequireNoPlate(query);

        var payload = JsonSerializer.SerializeToUtf8Bytes(AnalyticFilters(query, identity), JsonOptions);
        return Convert.ToHexString(SHA256.HashData(payload)).ToLowerInvariant();
    }

    /// <summary>The canonical analytic keys plus the pinned identity: what an analytic fingerprint covers.</summary>
    private static AnalyticFilterPayload AnalyticFilters(TrackSearchQuery query, TrackAnalyticsPinnedIdentity identity)
    {
        var canonical = TrackAnalyticsQueryRules.Canonicalise(query.Analytics!);
        return new AnalyticFilterPayload(
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
            identity.AlgorithmVersion);
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

    // --- Plate cursor (v4) ---------------------------------------------------

    /// <summary>
    /// The fingerprint of a plate search: the ordinary filters, the normalised plate text and its
    /// (defaulted) match mode, the plate identity the first page pinned and — when analytic
    /// predicates are combined — exactly what the analytic fingerprint covers. A continuation
    /// replayed with another text, another match mode, another plate identity or another analytics
    /// identity therefore fails the comparison.
    /// <para>
    /// Unlike the v2 and v3 fingerprints it is keyed — HMAC-SHA-256 under the cursor signing key, not a
    /// bare SHA-256 — because the plate text is a potentially identifying cue drawn from a small space
    /// (3–15 of 36 symbols, plan §5.5): an unkeyed digest travelling inside a base64 cursor could be
    /// reversed offline by enumerating short texts. Keyed, it reveals nothing without the key.
    /// </para>
    /// </summary>
    public static string ComputePlateFilterFingerprint(
        TrackSearchQuery query,
        string plateIdentityFingerprint,
        TrackAnalyticsPinnedIdentity? analyticsIdentity,
        TrackCursorSigningKey key)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(key);
        if (query.Plate is not { } plate)
            throw new ArgumentException("A plate fingerprint needs a plate query.", nameof(query));
        if (!IsSha256(plateIdentityFingerprint))
            throw new ArgumentException("The plate identity fingerprint must be 64 lower-case hex.", nameof(plateIdentityFingerprint));
        if (query.IsAnalytic != analyticsIdentity is not null)
            throw new ArgumentException("An analytics identity accompanies exactly an analytic query.", nameof(analyticsIdentity));

        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new PlateFilterPayload(
                BaseFilters(query),
                plate.Text,
                TrackPlateQueryRules.ToWire(plate.Match),
                plateIdentityFingerprint,
                analyticsIdentity is null ? null : AnalyticFilters(query, analyticsIdentity)),
            JsonOptions);
        return Convert.ToHexString(HMACSHA256.HashData(PlateFingerprintKey(key), payload)).ToLowerInvariant();
    }

    public static string EncodePlate(TrackPlateCursorPosition cursor, TrackCursorSigningKey key)
    {
        ArgumentNullException.ThrowIfNull(cursor);
        ArgumentNullException.ThrowIfNull(key);
        if (!IsSha256(cursor.PlateIdentityFingerprint))
            throw new ArgumentException("A plate cursor pins a 64-hex plate identity.", nameof(cursor));
        if (cursor.AnalyticsIdentity is null != cursor.AnalyticsCoverage is null)
            throw new ArgumentException("The analytics identity and coverage travel together.", nameof(cursor));

        var position = cursor.Position;
        var plates = cursor.PlateCoverage;
        AnalyticPin? analytics = null;
        if (cursor.AnalyticsIdentity is { } identity && cursor.AnalyticsCoverage is { } coverage)
        {
            analytics = new AnalyticPin(
                identity.CameraId,
                identity.SceneRevisionId,
                identity.AlgorithmVersion,
                [
                    coverage.EvaluatedRuns,
                    coverage.PendingRuns,
                    coverage.FailedRuns,
                    coverage.NotConfiguredRuns,
                    coverage.DisabledRuns,
                    coverage.StaleRuns,
                    coverage.AnalysedTracks,
                    coverage.UnavailableTracks,
                ]);
        }

        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new PlateCursorPayload(
                PlateVersion,
                position.SnapshotUtc.ToUniversalTime(),
                position.SnapshotVisibilitySequence,
                position.StartTimestampUtc.ToUniversalTime(),
                position.TrackId,
                position.FilterFingerprint,
                [
                    // Fixed order: the six counts the plate coverage record declares.
                    new DerivedPin(
                        PlateCapabilityTag,
                        cursor.PlateIdentityFingerprint,
                        [
                            plates.VehicleTracksInScope,
                            plates.Ready,
                            plates.Pending,
                            plates.Failed,
                            plates.Stale,
                            plates.NotConfigured,
                        ]),
                ],
                analytics),
            JsonOptions);

        var envelope = new byte[MacByteLength + payload.Length];
        HMACSHA256.HashData(PlateMacKey(key), payload, envelope.AsSpan(0, MacByteLength));
        payload.CopyTo(envelope, MacByteLength);

        var encoded = ToBase64Url(envelope);
        if (encoded.Length > PlateMaximumEncodedLength)
            throw new InvalidOperationException(
                "Plate Track cursor exceeded its published size envelope.");
        return encoded;
    }

    /// <summary>
    /// Decodes and authenticates a v4 cursor; as v3, the MAC is verified in constant time before any
    /// byte of the payload is interpreted. An unknown capability tag, a missing or repeated
    /// <c>plates</c> pin, or plate counts that do not partition the scope are refused.
    /// </summary>
    public static bool TryDecodePlate(
        string? cursor,
        TrackCursorSigningKey key,
        out TrackPlateCursorPosition? position)
    {
        ArgumentNullException.ThrowIfNull(key);
        position = null;
        if (!TryAuthenticate(cursor, PlateMacKey(key), PlateMaximumEncodedLength, out var payload))
            return false;

        // Authenticated: the checks below guard against a stale format rather than an attacker.
        try
        {
            var parsed = JsonSerializer.Deserialize<PlateCursorPayload>(payload, JsonOptions);
            if (parsed is null ||
                parsed.V != PlateVersion ||
                parsed.Q <= 0 ||
                parsed.I == Guid.Empty ||
                parsed.I.Version != 7 ||
                parsed.S.Offset != TimeSpan.Zero ||
                parsed.T.Offset != TimeSpan.Zero ||
                !IsSha256(parsed.F) ||
                parsed.D is not { Length: 1 } ||
                parsed.D[0] is not { K: PlateCapabilityTag } pin ||
                !IsSha256(pin.F) ||
                pin.G is not { Length: PlateCoverageCountLength } ||
                pin.G.Any(count => count < 0) ||
                (long)pin.G[1] + pin.G[2] + pin.G[3] + pin.G[4] + pin.G[5] != pin.G[0])
            {
                return false;
            }

            TrackAnalyticsPinnedIdentity? identity = null;
            TrackAnalyticsCoverage? coverage = null;
            if (parsed.A is { } analytics)
            {
                if (analytics.C == Guid.Empty ||
                    analytics.R == Guid.Empty ||
                    string.IsNullOrWhiteSpace(analytics.A) ||
                    analytics.G is not { Length: AnalyticsCoverageCountLength } ||
                    analytics.G.Any(count => count < 0))
                {
                    return false;
                }

                identity = new TrackAnalyticsPinnedIdentity(analytics.C, analytics.R, analytics.A);
                coverage = new TrackAnalyticsCoverage(
                    analytics.R,
                    analytics.A,
                    analytics.G[0],
                    analytics.G[1],
                    analytics.G[2],
                    analytics.G[3],
                    analytics.G[4],
                    analytics.G[5],
                    analytics.G[6],
                    analytics.G[7]);
            }

            position = new TrackPlateCursorPosition(
                new TrackCursorPosition(parsed.S, parsed.Q, parsed.T, parsed.I, parsed.F),
                pin.F,
                new TrackPlateCoverage(pin.F, pin.G[0], pin.G[1], pin.G[2], pin.G[3], pin.G[4], pin.G[5]),
                identity,
                coverage);
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    // --- Attribute cursor (v4, "attributes" pin) ------------------------------------------

    /// <summary>
    /// The fingerprint of an attribute search (Stage-2 plan §16; PoC S5): the ordinary filters, the canonical
    /// predicates, the attribute identity the first page pinned and, when analytic predicates are combined, what
    /// the analytic fingerprint covers. Keyed with the v4 fingerprint key, as the plate fingerprint is; the payload
    /// names its predicate member, so it can never equal a plate search's.
    /// </summary>
    public static string ComputeAttributeFilterFingerprint(
        TrackSearchQuery query,
        string attributeIdentityFingerprint,
        TrackAnalyticsPinnedIdentity? analyticsIdentity,
        TrackCursorSigningKey key)
    {
        ArgumentNullException.ThrowIfNull(query);
        ArgumentNullException.ThrowIfNull(key);
        if (query.Attributes is not { } attributes)
            throw new ArgumentException("An attribute fingerprint needs an attribute query.", nameof(query));
        if (query.Plate is not null)
            throw new ArgumentException("An attribute query carries no plate predicate.", nameof(query));
        if (!IsSha256(attributeIdentityFingerprint))
            throw new ArgumentException("The attribute identity fingerprint must be 64 lower-case hex.", nameof(attributeIdentityFingerprint));
        if (query.IsAnalytic != analyticsIdentity is not null)
            throw new ArgumentException("An analytics identity accompanies exactly an analytic query.", nameof(analyticsIdentity));

        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new AttributeFilterPayload(
                BaseFilters(query),
                [.. attributes.Wire],
                attributeIdentityFingerprint,
                analyticsIdentity is null ? null : AnalyticFilters(query, analyticsIdentity)),
            JsonOptions);
        return Convert.ToHexString(HMACSHA256.HashData(PlateFingerprintKey(key), payload)).ToLowerInvariant();
    }

    public static string EncodeAttribute(TrackAttributeCursorPosition cursor, TrackCursorSigningKey key)
    {
        ArgumentNullException.ThrowIfNull(cursor);
        ArgumentNullException.ThrowIfNull(key);
        if (!IsSha256(cursor.AttributeIdentityFingerprint))
            throw new ArgumentException("An attribute cursor pins a 64-hex attribute identity.", nameof(cursor));
        if (cursor.AnalyticsIdentity is null != cursor.AnalyticsCoverage is null)
            throw new ArgumentException("The analytics identity and coverage travel together.", nameof(cursor));
        var coverage = cursor.AttributeCoverage;
        if (coverage.Unknown.Count is < 1 or > TrackSearchContractRules.MaximumAttributePredicates)
            throw new ArgumentException("An attribute cursor pins one Unknown count per predicate.", nameof(cursor));

        var position = cursor.Position;
        var payload = JsonSerializer.SerializeToUtf8Bytes(
            new PlateCursorPayload(
                PlateVersion,
                position.SnapshotUtc.ToUniversalTime(),
                position.SnapshotVisibilitySequence,
                position.StartTimestampUtc.ToUniversalTime(),
                position.TrackId,
                position.FilterFingerprint,
                [
                    // Fixed order: scope, analysed, unavailable, not analysed, then Unknown per predicate.
                    new DerivedPin(
                        AttributeCapabilityTag,
                        cursor.AttributeIdentityFingerprint,
                        [coverage.TracksInScope, coverage.Analysed, coverage.Unavailable, coverage.NotAnalysed, .. coverage.Unknown]),
                ],
                AnalyticPinOf(cursor.AnalyticsIdentity, cursor.AnalyticsCoverage)),
            JsonOptions);

        var envelope = new byte[MacByteLength + payload.Length];
        HMACSHA256.HashData(PlateMacKey(key), payload, envelope.AsSpan(0, MacByteLength));
        payload.CopyTo(envelope, MacByteLength);

        var encoded = ToBase64Url(envelope);
        if (encoded.Length > PlateMaximumEncodedLength)
            throw new InvalidOperationException("Attribute Track cursor exceeded its published size envelope.");
        return encoded;
    }

    /// <summary>
    /// Decodes and authenticates an attribute v4 cursor (MAC first, as every signed envelope). Exactly one derived pin,
    /// tagged <c>attributes</c>, is accepted, so a plate cursor is refused here and an attribute cursor by the plate
    /// decoder; the counts must partition the scope and no Unknown count may exceed the analysed Tracks. The
    /// <paramref name="disclosure"/> is not carried: it is the release's, which cannot change for a pinned identity.
    /// </summary>
    public static bool TryDecodeAttribute(
        string? cursor,
        TrackCursorSigningKey key,
        string? disclosure,
        out TrackAttributeCursorPosition? position)
    {
        ArgumentNullException.ThrowIfNull(key);
        position = null;
        if (!TryAuthenticate(cursor, PlateMacKey(key), PlateMaximumEncodedLength, out var payload))
            return false;

        try
        {
            var parsed = JsonSerializer.Deserialize<PlateCursorPayload>(payload, JsonOptions);
            if (parsed is null ||
                parsed.V != PlateVersion ||
                parsed.Q <= 0 ||
                parsed.I == Guid.Empty ||
                parsed.I.Version != 7 ||
                parsed.S.Offset != TimeSpan.Zero ||
                parsed.T.Offset != TimeSpan.Zero ||
                !IsSha256(parsed.F) ||
                parsed.D is not { Length: 1 } ||
                parsed.D[0] is not { K: AttributeCapabilityTag } pin ||
                !IsSha256(pin.F) ||
                pin.G is not { Length: > AttributeCoverageFixedCountLength and <= AttributeCoverageFixedCountLength + TrackSearchContractRules.MaximumAttributePredicates } ||
                pin.G.Any(count => count < 0) ||
                (long)pin.G[1] + pin.G[2] + pin.G[3] != pin.G[0] ||
                pin.G.Skip(AttributeCoverageFixedCountLength).Any(unknown => unknown > pin.G[1]))
            {
                return false;
            }

            if (!TryReadAnalyticPin(parsed.A, out var identity, out var analyticsCoverage))
                return false;

            position = new TrackAttributeCursorPosition(
                new TrackCursorPosition(parsed.S, parsed.Q, parsed.T, parsed.I, parsed.F),
                pin.F,
                new TrackAttributeCoverage(pin.F, disclosure, pin.G[0], pin.G[1], pin.G[2], pin.G[3], pin.G[AttributeCoverageFixedCountLength..]),
                identity,
                analyticsCoverage);
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static AnalyticPin? AnalyticPinOf(TrackAnalyticsPinnedIdentity? identity, TrackAnalyticsCoverage? coverage) =>
        identity is null || coverage is null
            ? null
            : new AnalyticPin(
                identity.CameraId,
                identity.SceneRevisionId,
                identity.AlgorithmVersion,
                [
                    coverage.EvaluatedRuns,
                    coverage.PendingRuns,
                    coverage.FailedRuns,
                    coverage.NotConfiguredRuns,
                    coverage.DisabledRuns,
                    coverage.StaleRuns,
                    coverage.AnalysedTracks,
                    coverage.UnavailableTracks,
                ]);

    private static bool TryReadAnalyticPin(
        AnalyticPin? analytics,
        out TrackAnalyticsPinnedIdentity? identity,
        out TrackAnalyticsCoverage? coverage)
    {
        identity = null;
        coverage = null;
        if (analytics is null)
            return true;
        if (analytics.C == Guid.Empty ||
            analytics.R == Guid.Empty ||
            string.IsNullOrWhiteSpace(analytics.A) ||
            analytics.G is not { Length: AnalyticsCoverageCountLength } ||
            analytics.G.Any(count => count < 0))
        {
            return false;
        }

        identity = new TrackAnalyticsPinnedIdentity(analytics.C, analytics.R, analytics.A);
        coverage = new TrackAnalyticsCoverage(
            analytics.R,
            analytics.A,
            analytics.G[0],
            analytics.G[1],
            analytics.G[2],
            analytics.G[3],
            analytics.G[4],
            analytics.G[5],
            analytics.G[6],
            analytics.G[7]);
        return true;
    }

    /// <summary>
    /// The front half of a signed envelope: shape, length, base64url and a constant-time MAC check.
    /// On success <paramref name="payload"/> is bytes this server wrote under this key.
    /// </summary>
    private static bool TryAuthenticate(string? cursor, byte[] macKey, int maximumLength, out byte[] payload)
    {
        payload = [];
        if (string.IsNullOrWhiteSpace(cursor) ||
            cursor.Length > maximumLength ||
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

        Span<byte> expected = stackalloc byte[MacByteLength];
        HMACSHA256.HashData(macKey, envelope.AsSpan(MacByteLength), expected);
        if (!CryptographicOperations.FixedTimeEquals(expected, envelope.AsSpan(0, MacByteLength)))
            return false;

        payload = envelope[MacByteLength..];
        return true;
    }

    /// <summary>The label of the v4 envelope's authentication key (<see cref="PlateMacKey"/>).</summary>
    public const string PlateMacKeyLabel = "mavi-track-cursor-v4/mac";

    /// <summary>The label of the v4 filter-fingerprint key (<see cref="PlateFingerprintKey"/>).</summary>
    public const string PlateFingerprintKeyLabel = "mavi-track-cursor-v4/filter-fingerprint";

    /// <summary>
    /// The v4 cursor uses the configured key material for two purposes — authenticating the envelope and
    /// keying the filter fingerprint inside it — so each purpose gets its own key, derived as
    /// HMAC-SHA-256(key, label) with a distinct label (cold review P3-2). The wire format is unchanged; a v4
    /// cursor minted before this derivation no longer verifies and is refused like any stale cursor (cursors
    /// are short-lived navigation tokens, valid for an hour). v2 is unsigned and v3 uses the key for its MAC
    /// alone, so both are unchanged.
    /// </summary>
    internal static byte[] PlateMacKey(TrackCursorSigningKey key) => DeriveKey(key, PlateMacKeyLabel);

    internal static byte[] PlateFingerprintKey(TrackCursorSigningKey key) => DeriveKey(key, PlateFingerprintKeyLabel);

    private static byte[] DeriveKey(TrackCursorSigningKey key, string label)
    {
        ArgumentNullException.ThrowIfNull(key);
        return HMACSHA256.HashData(key.Bytes, System.Text.Encoding.ASCII.GetBytes(label));
    }

    private static void RequireNoPlate(TrackSearchQuery query)
    {
        // A plate query is paged only by the v4 cursor, whose fingerprint covers the predicate;
        // fingerprinting one here would silently drop the predicate from the cursor's meaning.
        if (query.Plate is not null)
            throw new ArgumentException("A plate query is fingerprinted only by the v4 cursor.", nameof(query));
        // The same for an attribute query (PoC S5).
        if (query.Attributes is not null)
            throw new ArgumentException("An attribute query is fingerprinted only by the v4 cursor.", nameof(query));
    }

    private static FilterPayload BaseFilters(TrackSearchQuery query) => new(
        query.CameraId,
        query.VideoAssetId,
        query.ProcessingRunId,
        query.ObjectClass,
        query.FromUtc?.ToUniversalTime(),
        query.ToUtc?.ToUniversalTime(),
        query.MinimumDurationMs,
        query.MinimumConfidence,
        query.ObjectSubclass);

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
        double? MinimumConfidence,
        // Omitted when null, so a search without a subclass filter fingerprints byte for
        // byte as it did before X2 and its cursors stay valid across the upgrade.
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        string? ObjectSubclass = null);

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

    private sealed record AttributeFilterPayload(
        FilterPayload Base,
        string[] Attributes,
        string PinnedAttributeIdentityFingerprint,
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        AnalyticFilterPayload? Analytics);

    private sealed record PlateFilterPayload(
        FilterPayload Base,
        string PlateText,
        string PlateMatch,
        string PinnedPlateIdentityFingerprint,
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        AnalyticFilterPayload? Analytics);

    /// <summary>
    /// The v4 payload, single-lettered for the 1024-character bound as v3 is: V version, S snapshot
    /// time, Q snapshot sequence, T keyset timestamp, I keyset Track id, F filter fingerprint,
    /// D the capability-tagged derived pins, A the analytics pin (present only when combined).
    /// </summary>
    private sealed record PlateCursorPayload(
        int V,
        DateTimeOffset S,
        long Q,
        DateTimeOffset T,
        Guid I,
        string F,
        DerivedPin[] D,
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        AnalyticPin? A = null);

    /// <summary>K capability tag, F identity fingerprint, G that capability's coverage counts.</summary>
    private sealed record DerivedPin(string K, string F, int[] G);

    /// <summary>C camera, R revision (null = never configured), A algorithm version, G the eight v3 counts.</summary>
    private sealed record AnalyticPin(Guid C, Guid? R, string A, int[] G);

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
