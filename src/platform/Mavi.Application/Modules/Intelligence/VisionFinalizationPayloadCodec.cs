using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// Canonical platform-owned payload retained after a completion 3.1 hand-off.
/// It contains only the semantic completion data required for deterministic
/// re-validation/finalization. Worker authentication capabilities are excluded.
/// </summary>
public static class VisionFinalizationPayloadCodec
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    [JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
    private sealed record Document(
        string SchemaVersion,
        Guid JobId,
        int AttemptCount,
        long FramesProcessed,
        long ProcessingDurationMs,
        VisionRuntimeProvenanceContract Provenance,
        IReadOnlyList<VisionTrackResultContract> Tracks,
        VisionEvidenceAccountingContract? EvidenceAccounting);

    /// <summary>
    /// Serialize the semantic completion payload. The authenticated HTTP envelope
    /// (<c>workerId</c>, <c>leaseToken</c>) is deliberately not persisted.
    /// </summary>
    public static byte[] Encode(VisionJobCompleteRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (request.SchemaVersion != WorkerContractRules.CompletionSchemaVersionV31 ||
            request.JobId is not { } jobId ||
            request.AttemptCount is not { } attemptCount ||
            request.FramesProcessed is not { } framesProcessed ||
            request.ProcessingDurationMs is not { } processingDurationMs ||
            request.Provenance is null ||
            request.Tracks is null)
            throw new VisionResultValidationException("finalization_payload_source_invalid");

        var document = new Document(
            WorkerContractRules.CompletionSchemaVersionV31,
            jobId,
            attemptCount,
            framesProcessed,
            processingDurationMs,
            request.Provenance,
            request.Tracks,
            request.EvidenceAccounting);

        return JsonSerializer.SerializeToUtf8Bytes(document, Json);
    }

    /// <summary>
    /// Reconstruct a completion request suitable for semantic re-validation.
    /// Authentication fields remain absent by design and are never needed by
    /// <see cref="VisionResultValidator"/>.
    /// </summary>
    public static VisionJobCompleteRequest Decode(ReadOnlySpan<byte> payload)
    {
        if (payload.IsEmpty)
            throw new VisionResultValidationException("finalization_payload_invalid");

        Document document;
        try
        {
            document = JsonSerializer.Deserialize<Document>(payload, Json)
                ?? throw new JsonException("Payload deserialized to null.");
        }
        catch (JsonException)
        {
            throw new VisionResultValidationException("finalization_payload_invalid");
        }

        if (document.SchemaVersion != WorkerContractRules.CompletionSchemaVersionV31)
            throw new VisionResultValidationException("finalization_payload_version_invalid");

        return new VisionJobCompleteRequest(
            document.SchemaVersion,
            document.JobId,
            WorkerId: null,
            LeaseToken: null,
            document.AttemptCount,
            document.FramesProcessed,
            document.ProcessingDurationMs,
            document.Provenance,
            document.Tracks,
            document.EvidenceAccounting);
    }
}
