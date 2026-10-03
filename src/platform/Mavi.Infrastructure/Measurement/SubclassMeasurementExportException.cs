namespace Mavi.Infrastructure.Measurement;

/// <summary>The stable refusal codes of the read-only measurement export (S3.2 plan T1).</summary>
public static class SubclassMeasurementExportCodes
{
    public const string RunNotFound = "export_run_not_found";
    public const string RunNotTerminal = "export_run_not_terminal";
    public const string AttestationIntegrity = "export_attestation_integrity";
    public const string PipelineProfileMismatch = "export_pipeline_profile_mismatch";
    public const string PipelineProfileInvalid = "export_pipeline_profile_invalid";
    public const string ProfileNotStage3 = "export_profile_not_stage3";
    public const string TrackRunMismatch = "export_track_run_mismatch";
    public const string ObservationOrphan = "export_observation_orphan";
    public const string VideoMismatch = "export_video_mismatch";
    public const string SubclassStateInvalid = "export_subclass_state_invalid";
    public const string EvidenceChanged = "export_evidence_changed";
    public const string SourceChanged = "export_source_changed";
    public const string ProvenanceIncomplete = "export_provenance_incomplete";
    public const string OutputExists = "export_output_exists";
    public const string OutputInvalid = "export_output_invalid";
}

/// <summary>A refusal: the export cannot be produced from this run, profile or output.</summary>
public sealed class SubclassMeasurementExportException : Exception
{
    public SubclassMeasurementExportException(string code, string message)
        : base(message)
    {
        Code = code;
    }

    public SubclassMeasurementExportException(string code, string message, Exception innerException)
        : base(message, innerException)
    {
        Code = code;
    }

    public string Code { get; }
}
