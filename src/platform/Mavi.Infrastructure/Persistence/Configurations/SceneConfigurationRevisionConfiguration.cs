using Mavi.Domain.Media;
using Mavi.Domain.Scene;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class SceneConfigurationRevisionConfiguration : IEntityTypeConfiguration<SceneConfigurationRevision>
{
    public void Configure(EntityTypeBuilder<SceneConfigurationRevision> builder)
    {
        builder.ToTable("scene_configuration_revisions", table =>
        {
            table.HasCheckConstraint("ck_scene_revisions_number", "revision_number >= 1");
            table.HasCheckConstraint(
                "ck_scene_revisions_reference_frame",
                "(reference_frame_video_asset_id IS NULL AND reference_frame_offset_ms IS NULL) OR " +
                "(reference_frame_video_asset_id IS NOT NULL AND reference_frame_offset_ms IS NOT NULL " +
                "AND reference_frame_offset_ms >= 0)");
        });
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.SceneConfigurationId).HasColumnName("scene_configuration_id");
        builder.Property(x => x.RevisionNumber).HasColumnName("revision_number");
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.Property(x => x.CreatedBy).HasColumnName("created_by").HasMaxLength(64).IsRequired();
        builder.Property(x => x.Note).HasColumnName("note").HasMaxLength(500);
        builder.Property(x => x.ReferenceFrameVideoAssetId).HasColumnName("reference_frame_video_asset_id");
        builder.Property(x => x.ReferenceFrameOffsetMs).HasColumnName("reference_frame_offset_ms");

        // Revisions are never deleted in this increment, and the constraint says so:
        // a configuration cannot be removed while its history exists.
        builder.HasOne<SceneConfiguration>().WithMany()
            .HasForeignKey(x => x.SceneConfigurationId).OnDelete(DeleteBehavior.Restrict);
        builder.HasOne<VideoAsset>().WithMany()
            .HasForeignKey(x => x.ReferenceFrameVideoAssetId).OnDelete(DeleteBehavior.Restrict);

        // Geometry has no meaning apart from the revision that owns it, so it is
        // deleted with the revision; nothing deletes a revision in this increment.
        builder.HasMany(x => x.Zones).WithOne()
            .HasForeignKey(zone => zone.RevisionId).OnDelete(DeleteBehavior.Cascade);
        builder.HasMany(x => x.TripLines).WithOne()
            .HasForeignKey(line => line.RevisionId).OnDelete(DeleteBehavior.Cascade);
        builder.Navigation(x => x.Zones).HasField("_zones").UsePropertyAccessMode(PropertyAccessMode.Field);
        builder.Navigation(x => x.TripLines).HasField("_tripLines").UsePropertyAccessMode(PropertyAccessMode.Field);
        builder.Ignore(x => x.AnalyticsEnabled);

        builder.HasIndex(x => new { x.SceneConfigurationId, x.RevisionNumber })
            .IsUnique().HasDatabaseName("ux_scene_revisions_configuration_number");

        // Referenced by the deferred composite foreign key that pins a configuration's
        // active revision to the configuration itself.
        builder.HasIndex(x => new { x.Id, x.SceneConfigurationId })
            .IsUnique().HasDatabaseName("ux_scene_revisions_id_configuration");
    }
}
