using Mavi.Domain.Cameras;
using Mavi.Domain.Faces;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;
using Pgvector;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>One Person Track's outcome in one face analysis (ADR-022 §1, §4): <c>Observed</c> or <c>Unknown</c> with a reason.</summary>
public sealed class FaceTrackOutcomeRow
{
    public Guid AnalysisId { get; set; }
    public Guid TrackId { get; set; }
    public string Outcome { get; set; } = string.Empty;
    public string? Reason { get; set; }
}

/// <summary>
/// One detected face (ADR-022 §4): its evidence Observation, box and five landmarks in crop pixels, score, shorter
/// side and whether it is usable. No image bytes: the browser crops the existing evidence crop to show it.
/// </summary>
public sealed class FaceObservationRow
{
    public Guid Id { get; set; }
    public Guid AnalysisId { get; set; }
    public Guid TrackId { get; set; }
    public Guid ObservationId { get; set; }
    public float BoxX { get; set; }
    public float BoxY { get; set; }
    public float BoxWidth { get; set; }
    public float BoxHeight { get; set; }
    public float[] Landmarks { get; set; } = [];
    public float Score { get; set; }
    public float MinSide { get; set; }
    public bool Usable { get; set; }
}

/// <summary>The template of one usable face (ADR-022 §4): biometric, local only, deleted with its analysis.</summary>
public sealed class FaceEmbeddingRow
{
    public Guid FaceObservationId { get; set; }
    public Vector Embedding { get; set; } = null!;
}

/// <summary>One face of a transient query image: its vector and the worker's aligned thumbnail (usable faces only).</summary>
public sealed class FaceQueryEmbeddingRow
{
    public Guid QueryId { get; set; }
    public int FaceIndex { get; set; }
    public Vector Embedding { get; set; } = null!;
    public byte[]? Thumbnail { get; set; }
}

internal static class FaceVectorConversion
{
    public static readonly ValueConverter<float[], Vector> Converter = new(value => new Vector(value), value => value.ToArray());

    public static readonly ValueComparer<float[]> Comparer = new(
        (left, right) => left == null ? right == null : right != null && left.SequenceEqual(right),
        value => value.Aggregate(0, (hash, item) => HashCode.Combine(hash, item)),
        value => value.ToArray());
}

public sealed class FaceAnalysisConfiguration : IEntityTypeConfiguration<FaceAnalysis>
{
    public void Configure(EntityTypeBuilder<FaceAnalysis> builder)
    {
        builder.ToTable("face_analyses", table =>
        {
            table.HasCheckConstraint("ck_face_analyses_status", "status IN ('Queued', 'Running', 'Completed', 'Failed', 'Superseded')");
            table.HasCheckConstraint("ck_face_analyses_attempt_count", "attempt_count >= 0");
            table.HasCheckConstraint("ck_face_analyses_counts", "tracks_observed >= 0 AND tracks_unknown >= 0");
            table.HasCheckConstraint("ck_face_analyses_dimension", "dimension BETWEEN 1 AND 4096");
            table.HasCheckConstraint("ck_face_analyses_token_hashes",
                "(lease_token_hash IS NULL OR octet_length(lease_token_hash) = 32) AND " +
                "(last_failed_token_hash IS NULL OR octet_length(last_failed_token_hash) = 32)");
            table.HasCheckConstraint("ck_face_analyses_sha256",
                "identity_fingerprint ~ '^[0-9a-f]{64}$' AND manifest_sha256 ~ '^[0-9a-f]{64}$' AND " +
                "pipeline_sha256 ~ '^[0-9a-f]{64}$' AND (completion_digest IS NULL OR completion_digest ~ '^[0-9a-f]{64}$')");
            table.HasCheckConstraint("ck_face_analyses_running_lease",
                "status <> 'Running' OR (lease_owner IS NOT NULL AND lease_token_hash IS NOT NULL AND " +
                "lease_expires_at_utc IS NOT NULL AND first_claimed_at_utc IS NOT NULL AND attempt_count > 0)");
            table.HasCheckConstraint("ck_face_analyses_fact_bearing",
                "status NOT IN ('Completed', 'Superseded') OR (completion_digest IS NOT NULL AND " +
                "visibility_sequence IS NOT NULL AND provenance_json IS NOT NULL AND completed_at_utc IS NOT NULL)");
            table.HasCheckConstraint("ck_face_analyses_unpublished", "status IN ('Completed', 'Superseded') OR visibility_sequence IS NULL");
            table.HasCheckConstraint("ck_face_analyses_failed", "status <> 'Failed' OR (failure_code IS NOT NULL AND completed_at_utc IS NOT NULL)");
        });

        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.ProcessingRunId).HasColumnName("processing_run_id");
        builder.Property(x => x.CameraId).HasColumnName("camera_id");
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.ModelId).HasColumnName("model_id").HasMaxLength(128).IsRequired();
        builder.Property(x => x.ModelVersion).HasColumnName("model_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.ManifestSha256).HasColumnName("manifest_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Dimension).HasColumnName("dimension");
        builder.Property(x => x.PipelineId).HasColumnName("pipeline_id").HasMaxLength(64).IsRequired();
        builder.Property(x => x.PipelineVersion).HasColumnName("pipeline_version").HasMaxLength(64).IsRequired();
        builder.Property(x => x.PipelineSha256).HasColumnName("pipeline_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.AttemptCount).HasColumnName("attempt_count");
        builder.Property(x => x.LeaseOwner).HasColumnName("lease_owner").HasMaxLength(128);
        builder.Property(x => x.LeaseTokenHash).HasColumnName("lease_token_hash");
        builder.Property(x => x.LeaseExpiresAtUtc).HasColumnName("lease_expires_at_utc");
        builder.Property(x => x.LastHeartbeatUtc).HasColumnName("last_heartbeat_utc");
        builder.Property(x => x.QueuedAtUtc).HasColumnName("queued_at_utc");
        builder.Property(x => x.FirstClaimedAtUtc).HasColumnName("first_claimed_at_utc");
        builder.Property(x => x.CompletedAtUtc).HasColumnName("completed_at_utc");
        builder.Property(x => x.FailureCode).HasColumnName("failure_code").HasMaxLength(64);
        builder.Property(x => x.FailureDetails).HasColumnName("failure_details").HasMaxLength(FaceAnalysis.MaximumFailureDetailsLength);
        builder.Property(x => x.LastFailedWorkerId).HasColumnName("last_failed_worker_id").HasMaxLength(128);
        builder.Property(x => x.LastFailedAttempt).HasColumnName("last_failed_attempt");
        builder.Property(x => x.LastFailedTokenHash).HasColumnName("last_failed_token_hash");
        builder.Property(x => x.LastFailedCode).HasColumnName("last_failed_code").HasMaxLength(64);
        builder.Property(x => x.LastFailedDetails).HasColumnName("last_failed_details").HasMaxLength(FaceAnalysis.MaximumFailureDetailsLength);
        builder.Property(x => x.LastFailedOutcome).HasColumnName("last_failed_outcome").HasConversion<string>().HasMaxLength(16);
        builder.Property(x => x.CompletionDigest).HasColumnName("completion_digest").HasMaxLength(64).IsFixedLength();
        builder.Property(x => x.ProvenanceJson).HasColumnName("provenance_json").HasColumnType("jsonb");
        builder.Property(x => x.TracksObserved).HasColumnName("tracks_observed");
        builder.Property(x => x.TracksUnknown).HasColumnName("tracks_unknown");
        builder.Property(x => x.VisibilitySequence).HasColumnName("visibility_sequence");
        builder.Ignore(x => x.Identity);
        builder.Ignore(x => x.IsFactBearing);

        // Face rows go with their run, and with their camera when it is opted out (ADR-022 §5).
        builder.HasOne<ProcessingRun>().WithMany().HasForeignKey(x => x.ProcessingRunId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Camera>().WithMany().HasForeignKey(x => x.CameraId).OnDelete(DeleteBehavior.Cascade);

        builder.HasIndex(x => new { x.ProcessingRunId, x.IdentityFingerprint }).IsUnique().HasDatabaseName("ux_face_analyses_identity");
        builder.HasIndex(x => new { x.IdentityFingerprint, x.Status, x.QueuedAtUtc })
            .HasDatabaseName("ix_face_analyses_claim")
            .HasFilter("status IN ('Queued', 'Running')");
        builder.HasIndex(x => x.CameraId).HasDatabaseName("ix_face_analyses_camera");
        builder.HasIndex(x => x.VisibilitySequence)
            .IsUnique()
            .HasDatabaseName("ux_face_analyses_visibility_sequence")
            .HasFilter("visibility_sequence IS NOT NULL");
    }
}

public sealed class FaceTrackOutcomeRowConfiguration : IEntityTypeConfiguration<FaceTrackOutcomeRow>
{
    public void Configure(EntityTypeBuilder<FaceTrackOutcomeRow> builder)
    {
        builder.ToTable("face_track_outcomes", table => table.HasCheckConstraint("ck_face_track_outcomes_outcome",
            "(outcome = 'Observed' AND reason IS NULL) OR " +
            "(outcome = 'Unknown' AND reason IN ('no_evidence', 'evidence_unavailable', 'no_face_detected', 'face_too_small'))"));
        builder.HasKey(x => new { x.AnalysisId, x.TrackId });
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.Outcome).HasColumnName("outcome").HasMaxLength(16).IsRequired();
        builder.Property(x => x.Reason).HasColumnName("reason").HasMaxLength(32);
        builder.HasOne<FaceAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Cascade);
        builder.HasIndex(x => x.TrackId).HasDatabaseName("ix_face_track_outcomes_track");
    }
}

public sealed class FaceObservationRowConfiguration : IEntityTypeConfiguration<FaceObservationRow>
{
    public void Configure(EntityTypeBuilder<FaceObservationRow> builder)
    {
        builder.ToTable("face_observations", table =>
        {
            table.HasCheckConstraint("ck_face_observations_box", "box_x >= 0 AND box_y >= 0 AND box_w > 0 AND box_h > 0");
            table.HasCheckConstraint("ck_face_observations_landmarks", "cardinality(landmarks) = 10");
            table.HasCheckConstraint("ck_face_observations_score", "score > 0 AND score <= 1");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.AnalysisId).HasColumnName("analysis_id");
        builder.Property(x => x.TrackId).HasColumnName("track_id");
        builder.Property(x => x.ObservationId).HasColumnName("observation_id");
        builder.Property(x => x.BoxX).HasColumnName("box_x");
        builder.Property(x => x.BoxY).HasColumnName("box_y");
        builder.Property(x => x.BoxWidth).HasColumnName("box_w");
        builder.Property(x => x.BoxHeight).HasColumnName("box_h");
        builder.Property(x => x.Landmarks).HasColumnName("landmarks").IsRequired();
        builder.Property(x => x.Score).HasColumnName("score");
        builder.Property(x => x.MinSide).HasColumnName("min_side");
        builder.Property(x => x.Usable).HasColumnName("usable");
        builder.HasOne<FaceAnalysis>().WithMany().HasForeignKey(x => x.AnalysisId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Cascade);
        builder.HasOne<Observation>().WithMany().HasForeignKey(x => x.ObservationId).OnDelete(DeleteBehavior.Cascade);
        builder.HasIndex(x => new { x.AnalysisId, x.TrackId }).HasDatabaseName("ix_face_observations_analysis_track");
        builder.HasIndex(x => x.TrackId).HasDatabaseName("ix_face_observations_track");
        builder.HasIndex(x => x.ObservationId).HasDatabaseName("ix_face_observations_observation");
    }
}

public sealed class FaceEmbeddingRowConfiguration : IEntityTypeConfiguration<FaceEmbeddingRow>
{
    public void Configure(EntityTypeBuilder<FaceEmbeddingRow> builder)
    {
        builder.ToTable("face_embeddings");
        builder.HasKey(x => x.FaceObservationId);
        builder.Property(x => x.FaceObservationId).HasColumnName("face_observation_id");
        // Dimension-free, as track_embeddings: each analysis records its dimension; search compares one identity only.
        builder.Property(x => x.Embedding).HasColumnName("embedding").HasColumnType("vector").IsRequired();
        builder.HasOne<FaceObservationRow>().WithOne().HasForeignKey<FaceEmbeddingRow>(x => x.FaceObservationId).OnDelete(DeleteBehavior.Cascade);
    }
}

public sealed class FaceQueryConfiguration : IEntityTypeConfiguration<FaceQuery>
{
    public void Configure(EntityTypeBuilder<FaceQuery> builder)
    {
        builder.ToTable("face_queries", table =>
        {
            table.HasCheckConstraint("ck_face_queries_status", "status IN ('Pending', 'Running', 'Completed', 'Failed')");
            table.HasCheckConstraint("ck_face_queries_finished_image_erased", "status IN ('Pending', 'Running') OR image IS NULL");
            table.HasCheckConstraint("ck_face_queries_completed", "(status = 'Completed') = (faces IS NOT NULL)");
            table.HasCheckConstraint("ck_face_queries_size", "size_bytes BETWEEN 1 AND 2097152");
            table.HasCheckConstraint("ck_face_queries_mime", "mime_type IN ('image/jpeg', 'image/png')");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Image).HasColumnName("image");
        builder.Property(x => x.ImageSha256).HasColumnName("image_sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.MimeType).HasColumnName("mime_type").HasMaxLength(16).IsRequired();
        builder.Property(x => x.SizeBytes).HasColumnName("size_bytes");
        builder.Property(x => x.Status).HasColumnName("status").HasConversion<string>().HasMaxLength(16).IsRequired();
        builder.Property(x => x.AttemptCount).HasColumnName("attempt_count");
        builder.Property(x => x.LeaseOwner).HasColumnName("lease_owner").HasMaxLength(128);
        builder.Property(x => x.LeaseTokenHash).HasColumnName("lease_token_hash");
        builder.Property(x => x.LeaseExpiresAtUtc).HasColumnName("lease_expires_at_utc");
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.Property(x => x.CompletedAtUtc).HasColumnName("completed_at_utc");
        builder.Property(x => x.PurgeAfterUtc).HasColumnName("purge_after_utc");
        builder.Property(x => x.FailureCode).HasColumnName("failure_code").HasMaxLength(64);
        builder.Property(x => x.FacesJson).HasColumnName("faces").HasColumnType("jsonb");
        builder.Property(x => x.CompletionDigest).HasColumnName("completion_digest").HasMaxLength(64).IsFixedLength();
        builder.HasIndex(x => new { x.IdentityFingerprint, x.Status, x.CreatedAtUtc })
            .HasDatabaseName("ix_face_queries_claim")
            .HasFilter("status IN ('Pending', 'Running')");
        builder.HasIndex(x => x.PurgeAfterUtc).HasDatabaseName("ix_face_queries_purge");
    }
}

public sealed class FaceQueryEmbeddingRowConfiguration : IEntityTypeConfiguration<FaceQueryEmbeddingRow>
{
    public void Configure(EntityTypeBuilder<FaceQueryEmbeddingRow> builder)
    {
        builder.ToTable("face_query_embeddings");
        builder.HasKey(x => new { x.QueryId, x.FaceIndex });
        builder.Property(x => x.QueryId).HasColumnName("query_id");
        builder.Property(x => x.FaceIndex).HasColumnName("face_index");
        builder.Property(x => x.Embedding).HasColumnName("embedding").HasColumnType("vector").IsRequired();
        builder.Property(x => x.Thumbnail).HasColumnName("thumbnail");
        builder.HasOne<FaceQuery>().WithMany().HasForeignKey(x => x.QueryId).OnDelete(DeleteBehavior.Cascade);
    }
}

public sealed class EnrolledPersonConfiguration : IEntityTypeConfiguration<EnrolledPerson>
{
    public void Configure(EntityTypeBuilder<EnrolledPerson> builder)
    {
        builder.ToTable("enrolled_persons", table =>
        {
            table.HasCheckConstraint("ck_enrolled_persons_label", "char_length(label) BETWEEN 1 AND 100");
            table.HasCheckConstraint("ck_enrolled_persons_note", "note IS NULL OR char_length(note) <= 500");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.Label).HasColumnName("label").HasMaxLength(EnrolledPerson.MaximumLabelLength).IsRequired();
        builder.Property(x => x.Note).HasColumnName("note").HasMaxLength(EnrolledPerson.MaximumNoteLength);
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.Property(x => x.UpdatedAtUtc).HasColumnName("updated_at_utc");
    }
}

public sealed class EnrolledPersonFaceConfiguration : IEntityTypeConfiguration<EnrolledPersonFace>
{
    public void Configure(EntityTypeBuilder<EnrolledPersonFace> builder)
    {
        builder.ToTable("enrolled_person_faces", table =>
        {
            table.HasCheckConstraint("ck_enrolled_person_faces_source",
                "(source_kind = 'Evidence' AND source_face_observation_id IS NOT NULL AND thumbnail IS NULL) OR " +
                "(source_kind = 'Query' AND source_face_observation_id IS NULL)");
            table.HasCheckConstraint("ck_enrolled_person_faces_fingerprint", "identity_fingerprint ~ '^[0-9a-f]{64}$'");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.EnrolledPersonId).HasColumnName("enrolled_person_id");
        builder.Property(x => x.IdentityFingerprint).HasColumnName("identity_fingerprint").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.Embedding).HasColumnName("embedding").HasColumnType("vector").IsRequired()
            .HasConversion(FaceVectorConversion.Converter, FaceVectorConversion.Comparer);
        builder.Property(x => x.SourceKind).HasColumnName("source_kind").HasConversion<string>().HasMaxLength(16).IsRequired();
        // No foreign key: a gallery template outlives the run its evidence came from (ADR-022 §4).
        builder.Property(x => x.SourceFaceObservationId).HasColumnName("source_face_observation_id");
        builder.Property(x => x.Thumbnail).HasColumnName("thumbnail");
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.HasOne<EnrolledPerson>().WithMany().HasForeignKey(x => x.EnrolledPersonId).OnDelete(DeleteBehavior.Cascade);
        builder.HasIndex(x => x.EnrolledPersonId).HasDatabaseName("ix_enrolled_person_faces_person");
    }
}
