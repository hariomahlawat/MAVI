using System.Text.Json;
using System.Text.Json.Serialization;
using Mavi.Contracts.Worker;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// Canonical platform-owned payload retained after an asynchronous (3.1 or 3.2)
/// completion hand-off. It contains only the semantic completion data required for
/// deterministic re-validation/finalization. Worker authentication capabilities are
/// excluded. The document keeps the completion version the worker spoke: the entity
/// has no schema column, so replay selects the digest domain from this version and
/// never from the platform's current default (S2a plan §4.5).
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

        if (!WorkerContractRules.IsAsynchronousCompletionSchemaVersion(request.SchemaVersion) ||
            request.JobId is not { } jobId ||
            request.AttemptCount is not { } attemptCount ||
            request.FramesProcessed is not { } framesProcessed ||
            request.ProcessingDurationMs is not { } processingDurationMs ||
            request.Provenance is null ||
            request.Tracks is null)
            throw new VisionResultValidationException("finalization_payload_source_invalid");

        var document = new Document(
            request.SchemaVersion!,
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

        if (!WorkerContractRules.IsAsynchronousCompletionSchemaVersion(document.SchemaVersion))
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
