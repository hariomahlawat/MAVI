using Mavi.Domain.Media;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class ArtifactConfiguration : IEntityTypeConfiguration<Artifact>
{
    public void Configure(EntityTypeBuilder<Artifact> builder)
    {
        builder.ToTable("artifacts", table => table.HasCheckConstraint("ck_artifacts_size", "size_bytes >= 0")); builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.ArtifactType).HasColumnName("artifact_type").HasConversion<string>().HasMaxLength(32);
        builder.Property(x => x.StorageKey).HasColumnName("storage_key").HasMaxLength(512).IsRequired();
        builder.Property(x => x.MimeType).HasColumnName("mime_type").HasMaxLength(128).IsRequired();
        builder.Property(x => x.SizeBytes).HasColumnName("size_bytes");
        builder.Property(x => x.Sha256).HasColumnName("sha256").HasMaxLength(64).IsFixedLength().IsRequired();
        builder.Property(x => x.MetadataJson).HasColumnName("metadata_json").HasColumnType("jsonb");
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.HasIndex(x => x.StorageKey).IsUnique();
        builder.HasIndex(x => x.Sha256)
            .HasDatabaseName("ux_artifacts_source_video_sha256")
            .HasFilter("artifact_type = 'SourceVideo'")
            .IsUnique();
    }
}
