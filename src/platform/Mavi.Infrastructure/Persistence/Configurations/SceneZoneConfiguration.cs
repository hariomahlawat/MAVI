using Mavi.Domain.Scene;
using Mavi.Domain.Scene.Geometry;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class SceneZoneConfiguration : IEntityTypeConfiguration<SceneZone>
{
    private static readonly ValueConverter<IReadOnlyList<NormalizedPoint>, string> VerticesConverter =
        new(vertices => SceneGeometryJson.Write(vertices), json => SceneGeometryJson.Read(json));

    private static readonly ValueComparer<IReadOnlyList<NormalizedPoint>> VerticesComparer =
        new(
            (left, right) => left != null && right != null && left.SequenceEqual(right),
            vertices => vertices.Aggregate(0, (hash, point) => HashCode.Combine(hash, point)),
            vertices => SceneGeometryJson.Read(SceneGeometryJson.Write(vertices)));

    public void Configure(EntityTypeBuilder<SceneZone> builder)
    {
        builder.ToTable("scene_zones", table =>
        {
            table.HasCheckConstraint(
                "ck_scene_zones_vertex_count",
                "jsonb_array_length(vertices) BETWEEN 3 AND 64");
            table.HasCheckConstraint(
                "ck_scene_zones_loitering_threshold",
                "loitering_threshold_seconds IS NULL OR " +
                "(loitering_threshold_seconds > 0 AND loitering_threshold_seconds <= 86400)");
        });
        builder.HasKey(x => new { x.RevisionId, x.ZoneId });
        builder.Property(x => x.RevisionId).HasColumnName("revision_id");
        builder.Property(x => x.ZoneId).HasColumnName("zone_id");
        builder.Property(x => x.Name).HasColumnName("name").HasMaxLength(64).IsRequired();
        builder.Property(x => x.Kind).HasColumnName("kind").HasConversion<string>().HasMaxLength(32).IsRequired();
        builder.Property(x => x.Enabled).HasColumnName("enabled");
        builder.Property(x => x.LoiteringThresholdSeconds).HasColumnName("loitering_threshold_seconds");
        builder.Property(x => x.Vertices)
            .HasField("_vertices")
            .UsePropertyAccessMode(PropertyAccessMode.Field)
            .HasColumnName("vertices")
            .HasColumnType("jsonb")
            .HasConversion(VerticesConverter, VerticesComparer)
            .IsRequired();

        builder.HasIndex(x => x.ZoneId).HasDatabaseName("ix_scene_zones_zone");
    }
}
