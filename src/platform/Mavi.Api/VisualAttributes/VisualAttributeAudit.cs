using Mavi.Application.Modules.VisualAttributes;

namespace Mavi.Api.VisualAttributes;

/// <summary>
/// The audit trail of executor access to accepted evidence (ADR-013 §10: every read is logged
/// with unit, attempt, Observation, bytes and outcome). Never carries a capability.
/// </summary>
public sealed partial class VisualAttributeAudit(
    ILogger<VisualAttributeAudit> logger,
    VisualAttributeIntegrityMonitor integrity,
    TimeProvider clock)
{
    public void EvidenceServed(Guid analysisId, int attempt, Guid observationId, long bytes) =>
        LogEvidenceServed(logger, analysisId, attempt, observationId, bytes);

    public void EvidenceRefused(Guid analysisId, int attempt, Guid observationId, string code) =>
        LogEvidenceRefused(logger, analysisId, attempt, observationId, code);

    /// <summary>An authoritative integrity condition: an Error, and the health counter.</summary>
    public void EvidenceIntegrityIncident(Guid analysisId, int attempt, Guid observationId, string reason)
    {
        integrity.RecordEvidenceReadIncident(analysisId, clock.GetUtcNow());
        LogEvidenceIntegrityIncident(logger, analysisId, attempt, observationId, reason);
    }

    public void UploadHandled(Guid analysisId, int attempt, long bytes, string outcome) =>
        LogUpload(logger, analysisId, attempt, bytes, outcome);

    [LoggerMessage(EventId = 2000, EventName = "visual_attribute_evidence_read", Level = LogLevel.Information,
        Message = "Evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, {Bytes} bytes, served.")]
    private static partial void LogEvidenceServed(ILogger logger, Guid analysisId, int attempt, Guid observationId, long bytes);

    [LoggerMessage(EventId = 2001, EventName = "visual_attribute_evidence_read_refused", Level = LogLevel.Warning,
        Message = "Evidence read: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId}, refused ({Code}).")]
    private static partial void LogEvidenceRefused(ILogger logger, Guid analysisId, int attempt, Guid observationId, string code);

    [LoggerMessage(EventId = 2002, EventName = "visual_attribute_evidence_integrity_incident", Level = LogLevel.Error,
        Message = "Accepted evidence integrity incident: analysis {AnalysisId} attempt {Attempt} Observation {ObservationId} ({Reason}).")]
    private static partial void LogEvidenceIntegrityIncident(ILogger logger, Guid analysisId, int attempt, Guid observationId, string reason);

    [LoggerMessage(EventId = 2003, EventName = "visual_attribute_upload", Level = LogLevel.Information,
        Message = "Prediction upload: analysis {AnalysisId} attempt {Attempt}, {Bytes} bytes, {Outcome}.")]
    private static partial void LogUpload(ILogger logger, Guid analysisId, int attempt, long bytes, string outcome);
}
