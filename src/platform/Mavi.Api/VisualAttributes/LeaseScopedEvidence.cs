using Mavi.Application.Abstractions.Storage;

namespace Mavi.Api.VisualAttributes;

/// <summary>The audit a lease-scoped evidence read writes (ADR-013 §10). Never carries a capability.</summary>
public interface ILeaseEvidenceAudit
{
    void EvidenceServed(Guid analysisId, int attempt, Guid observationId, long bytes);
    void EvidenceRefused(Guid analysisId, int attempt, Guid observationId, string code);
    void EvidenceIntegrityIncident(Guid analysisId, int attempt, Guid observationId, string reason);
    void EvidenceLeaseLost(Guid analysisId, int attempt, Guid observationId);
}

/// <summary>What an authorised read may serve: the accepted object and the lease it was granted under.</summary>
public sealed record LeaseEvidenceGrant(string StorageKey, string MimeType, long SizeBytes, DateTimeOffset LeaseExpiresAtUtc);

/// <summary>
/// The plane a lease-scoped evidence read serves: its error-code prefix, its lease-lost exception and its
/// refusal for a lost lease. Everything else about serving the bytes is identical across planes.
/// </summary>
public sealed record LeaseEvidencePlane(
    string CodePrefix,
    Func<LeaseLostException> LeaseLost,
    Func<HttpContext, Task> WriteLeaseInvalid);

/// <summary>
/// The lease-scoped evidence-read handler shared by the attribute and plate planes (ADR-013 §10;
/// implementation amendment 2026-10-13, item 11: generalised by parameter, semantics unchanged). After
/// the plane has authorised the read: open through <see cref="IAcceptedEvidenceReader"/>, refuse a
/// missing or size-mismatched object as an authoritative integrity incident before any byte, and stream
/// it fenced for its whole lifetime — a lease lost before the first byte is a 409, after it the
/// connection is aborted, never a short 200.
/// </summary>
public static class LeaseScopedEvidence
{
    public static async Task<IResult> ServeAsync(
        Guid analysisId,
        int attempt,
        Guid observationId,
        LeaseEvidenceGrant grant,
        DateTimeOffset verifiedAtUtc,
        Func<CancellationToken, Task<DateTimeOffset?>> revalidate,
        IAcceptedEvidenceReader evidenceReader,
        ILeaseEvidenceAudit audit,
        TimeProvider clock,
        LeaseEvidencePlane plane,
        Func<int, string, string, IResult> problem,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(grant);
        ArgumentNullException.ThrowIfNull(evidenceReader);
        ArgumentNullException.ThrowIfNull(audit);
        ArgumentNullException.ThrowIfNull(plane);
        ArgumentNullException.ThrowIfNull(problem);
        Stream? stream;
        try
        {
            stream = await evidenceReader.OpenReadAsync(grant.StorageKey, cancellationToken);
        }
        catch (Exception exception) when (exception is FileNotFoundException or DirectoryNotFoundException)
        {
            audit.EvidenceIntegrityIncident(analysisId, attempt, observationId, "evidence_missing");
            return problem(422, $"{plane.CodePrefix}_evidence_missing", "The accepted evidence object is missing.");
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or ArgumentException)
        {
            // Not an authoritative statement about the object: the worker retries within its lease.
            audit.EvidenceRefused(analysisId, attempt, observationId, "evidence_unreadable");
            return problem(503, $"{plane.CodePrefix}_evidence_unreadable", "The accepted evidence object could not be read now.");
        }

        // The at-rest size is checked before any response header: a short or long object is an
        // explicit, authoritative integrity failure — never a truncated 200.
        if (!stream.CanSeek || stream.Length != grant.SizeBytes)
        {
            await stream.DisposeAsync();
            audit.EvidenceIntegrityIncident(analysisId, attempt, observationId, "evidence_integrity_failed");
            return problem(422, $"{plane.CodePrefix}_evidence_integrity_failed", "The accepted evidence object does not match its record.");
        }

        var fenced = new LeaseFencedStream(stream, revalidate, clock, grant.LeaseExpiresAtUtc, verifiedAtUtc, plane.LeaseLost);
        return new FencedEvidenceResult(fenced, grant, plane, () => audit.EvidenceLeaseLost(analysisId, attempt, observationId),
            () => audit.EvidenceServed(analysisId, attempt, observationId, grant.SizeBytes));
    }

    private sealed class FencedEvidenceResult(
        LeaseFencedStream stream, LeaseEvidenceGrant grant, LeaseEvidencePlane plane, Action leaseLost, Action served) : IResult
    {
        public async Task ExecuteAsync(HttpContext httpContext)
        {
            await using var source = stream;
            var response = httpContext.Response;
            response.ContentType = grant.MimeType;
            response.ContentLength = grant.SizeBytes;
            response.Headers.CacheControl = "no-store";
            var buffer = new byte[81_920];
            try
            {
                int read;
                while ((read = await source.ReadAsync(buffer, httpContext.RequestAborted)) > 0)
                    await response.Body.WriteAsync(buffer.AsMemory(0, read), httpContext.RequestAborted);
            }
            catch (LeaseLostException)
            {
                leaseLost();
                if (response.HasStarted)
                {
                    httpContext.Abort();
                    return;
                }

                response.ContentLength = null;
                response.Headers.CacheControl = default;
                await plane.WriteLeaseInvalid(httpContext);
                return;
            }

            served();
        }
    }
}
