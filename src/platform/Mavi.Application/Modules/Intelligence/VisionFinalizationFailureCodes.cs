using System.Collections.Frozen;
using Mavi.Domain.Processing;

namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// The closed vocabulary of finalization outcomes (F3 plan §9). Deterministic codes end the job
/// through the claim-fenced <c>FailFinalization</c>; transient codes are noted and retried within
/// the claim, attempt and deadline bounds; <see cref="Exhausted"/> is written only by platform
/// reconciliation. Every code is finalization-scoped, so status and UI never read one as a
/// detector or tracker failure.
/// </summary>
public static class VisionFinalizationFailureCodes
{
    // Deterministic (terminal)
    public const string PayloadMissing = "vision_finalization_payload_missing";
    public const string PayloadIntegrityFailed = "vision_finalization_payload_integrity_failed";
    public const string PayloadInvalid = "vision_finalization_payload_invalid";
    public const string StagingMissing = "vision_finalization_staging_missing";
    public const string StagingIntegrityFailed = "vision_finalization_staging_integrity_failed";
    public const string EvidenceConflict = "vision_finalization_evidence_conflict";
    public const string ContextInvalid = "vision_finalization_context_invalid";

    // Platform reconciliation only
    public const string Exhausted = VisionJob.FinalizationExhaustedFailureCode;

    // Transient (retried)
    public const string IoTransient = "vision_finalization_io_transient";
    public const string DbTransient = "vision_finalization_db_transient";
    public const string PublicationAmbiguous = "vision_finalization_publication_ambiguous";

    public static readonly FrozenSet<string> Deterministic = new[]
    {
        PayloadMissing, PayloadIntegrityFailed, PayloadInvalid, StagingMissing, StagingIntegrityFailed, EvidenceConflict, ContextInvalid,
    }.ToFrozenSet(StringComparer.Ordinal);

    public static readonly FrozenSet<string> Transient = new[]
    {
        IoTransient, DbTransient, PublicationAmbiguous,
    }.ToFrozenSet(StringComparer.Ordinal);

    /// <summary>Every code the finalizer or reconciliation can persist.</summary>
    public static readonly FrozenSet<string> All = Deterministic
        .Concat([Exhausted])
        .Concat(Transient)
        .ToFrozenSet(StringComparer.Ordinal);

    public static bool IsDeterministic(string code) => Deterministic.Contains(code);

    public static bool IsTransient(string code) => Transient.Contains(code);
}
