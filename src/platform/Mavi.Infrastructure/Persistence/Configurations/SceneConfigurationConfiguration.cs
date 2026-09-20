using Mavi.Domain.Cameras;
using Mavi.Domain.Scene;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class SceneConfigurationConfiguration : IEntityTypeConfiguration<SceneConfiguration>
{
    public void Configure(EntityTypeBuilder<SceneConfiguration> builder)
    {
        builder.ToTable("scene_configurations");
        builder.HasKey(x => x.Id);
        builder.Property(x => x.Id).HasColumnName("id");
        builder.Property(x => x.CameraId).HasColumnName("camera_id");
        builder.Property(x => x.ActiveRevisionId).HasColumnName("active_revision_id");
        builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc");
        builder.Property(x => x.UpdatedAtUtc).HasColumnName("updated_at_utc");

        // A camera's scene must outlive nothing: deleting a camera that still has a
        // scene is refused rather than silently discarding its revision history.
        builder.HasOne<Camera>().WithMany().HasForeignKey(x => x.CameraId).OnDelete(DeleteBehavior.Restrict);

        builder.HasIndex(x => x.CameraId).IsUnique().HasDatabaseName("ux_scene_configurations_camera");

        // The foreign key from active_revision_id back to the revision table is
        // deliberately not modelled here: it would close a cycle that EF cannot order
        // its inserts around. The migration adds it as a deferred composite constraint
        // instead, which also pins the revision to this configuration.
        builder.HasIndex(x => x.ActiveRevisionId).HasDatabaseName("ix_scene_configurations_active_revision");
    }
}
