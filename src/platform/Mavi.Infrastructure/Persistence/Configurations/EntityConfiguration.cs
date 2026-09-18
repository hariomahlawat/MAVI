using Mavi.Domain.Intelligence;
using Mavi.Domain.Media;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class EntityConfiguration : IEntityTypeConfiguration<Entity>
{
    public void Configure(EntityTypeBuilder<Entity> builder)
    {
        builder.ToTable("entities"); builder.HasKey(x => x.Id); builder.Property(x => x.Id).HasColumnName("id"); builder.Property(x => x.EntityType).HasColumnName("entity_type").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.DisplayCode).HasColumnName("display_code").HasMaxLength(64).IsRequired(); builder.Property(x => x.IdentityStatus).HasColumnName("identity_status").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.ReviewStatus).HasColumnName("review_status").HasConversion<string>().HasMaxLength(32); builder.Property(x => x.RepresentativeArtifactId).HasColumnName("representative_artifact_id"); builder.Property(x => x.CreatedAtUtc).HasColumnName("created_at_utc"); builder.Property(x => x.UpdatedAtUtc).HasColumnName("updated_at_utc"); builder.HasIndex(x => x.DisplayCode).IsUnique(); builder.HasOne<Artifact>().WithMany().HasForeignKey(x => x.RepresentativeArtifactId).OnDelete(DeleteBehavior.SetNull);
    }
}
