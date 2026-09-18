using Mavi.Domain.Intelligence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class VisualAttributeConfiguration : IEntityTypeConfiguration<VisualAttribute>
{
    public void Configure(EntityTypeBuilder<VisualAttribute> builder)
    {
        builder.ToTable("visual_attributes", t => t.HasCheckConstraint("ck_visual_attributes_confidence", "confidence >= 0 AND confidence <= 1")); builder.HasKey(x => x.Id); builder.Property(x => x.Id).HasColumnName("id"); builder.Property(x => x.TrackId).HasColumnName("track_id"); builder.Property(x => x.ObservationId).HasColumnName("observation_id"); builder.Property(x => x.AttributeType).HasColumnName("attribute_type").HasMaxLength(64).IsRequired(); builder.Property(x => x.Value).HasColumnName("value").HasMaxLength(128).IsRequired(); builder.Property(x => x.Confidence).HasColumnName("confidence"); builder.Property(x => x.ModelName).HasColumnName("model_name").HasMaxLength(128); builder.Property(x => x.ModelVersion).HasColumnName("model_version").HasMaxLength(128); builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc"); builder.HasOne<Track>().WithMany().HasForeignKey(x => x.TrackId).OnDelete(DeleteBehavior.Cascade); builder.HasOne<Observation>().WithMany().HasForeignKey(x => x.ObservationId).OnDelete(DeleteBehavior.SetNull); builder.HasIndex(x => x.TrackId);
    }
}
