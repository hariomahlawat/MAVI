using System.Security.Cryptography;
using Mavi.Domain.Common;

namespace Mavi.Domain.Processing;

/// <summary>
/// The exact completion body the platform accepted for one <see cref="VisionJob"/> attempt,
/// retained in PostgreSQL until the job is terminal (S1.4 B3 asynchronous finalization plan §4).
/// </summary>
/// <remarks>
/// <para>
/// It is written in the same transaction as <c>Leased → Finalizing</c>, so a Finalizing row
/// and its payload exist together or not at all. The finalizer re-reads these bytes, re-runs the
/// validator and requires the recomputed digest to equal the job's before sealing anything.
/// </para>
/// <para>
/// The row is deliberately not a navigation of <see cref="VisionJob"/>: the bytes are up to the
/// completion request-body limit and must never ride along with a status or lease query.
/// </para>
/// </remarks>
public sealed class VisionFinalizationPayload
{
    private VisionFinalizationPayload() { }

    public static VisionFinalizationPayload Create(
        Guid jobId,
        int attemptCount,
        byte[] payload,
        string completionDigest,
        DateTimeOffset acceptedAtUtc,
        long maximumPayloadBytes)
    {
        if (jobId == Guid.Empty) throw Invalid("vision_finalization_payload_job_required");
        if (attemptCount < 1) throw Invalid("vision_finalization_payload_attempt_invalid");
        if (maximumPayloadBytes < 1) throw Invalid("vision_finalization_payload_bound_invalid");
        if (payload is null || payload.Length < 1 || payload.LongLength > maximumPayloadBytes)
            throw Invalid("vision_finalization_payload_size_invalid");
        if (!VisionJob.IsCanonicalSha256(completionDigest))
            throw Invalid("vision_finalization_payload_digest_invalid");

        return new VisionFinalizationPayload
        {
            JobId = jobId,
            AttemptCount = attemptCount,
            Payload = [.. payload],
            PayloadLength = payload.LongLength,
            PayloadSha256 = Convert.ToHexStringLower(SHA256.HashData(payload)),
            CompletionDigest = completionDigest,
            AcceptedAtUtc = acceptedAtUtc.ToUniversalTime(),
        };
    }

    /// <summary>Whether <paramref name="bytes"/> are exactly the retained payload.</summary>
    public bool Matches(ReadOnlySpan<byte> bytes) =>
        bytes.Length == PayloadLength &&
        string.Equals(Convert.ToHexStringLower(SHA256.HashData(bytes)), PayloadSha256, StringComparison.Ordinal);

    public Guid JobId { get; private set; }
    public int AttemptCount { get; private set; }
    public byte[] Payload { get; private set; } = [];
    public long PayloadLength { get; private set; }
    public string PayloadSha256 { get; private set; } = string.Empty;
    public string CompletionDigest { get; private set; } = string.Empty;
    public DateTimeOffset AcceptedAtUtc { get; private set; }

    private static DomainValidationException Invalid(string code) =>
        new(code, "The finalization payload is invalid.");
}
