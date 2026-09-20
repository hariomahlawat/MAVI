using Mavi.Domain.Scene;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

public sealed class TripLineConfiguration : IEntityTypeConfiguration<TripLine>
{
    public void Configure(EntityTypeBuilder<TripLine> builder)
    {
        builder.ToTable("trip_lines", table =>
            table.HasCheckConstraint(
                "ck_trip_lines_range",
                "ax BETWEEN 0 AND 1 AND ay BETWEEN 0 AND 1 AND bx BETWEEN 0 AND 1 AND by BETWEEN 0 AND 1"));
        builder.HasKey(x => new { x.RevisionId, x.LineId });
        builder.Property(x => x.RevisionId).HasColumnName("revision_id");
        builder.Property(x => x.LineId).HasColumnName("line_id");
        builder.Property(x => x.Name).HasColumnName("name").HasMaxLength(64).IsRequired();
        builder.Property(x => x.Enabled).HasColumnName("enabled");
        builder.Property(x => x.Directed).HasColumnName("directed");
        builder.Property(x => x.AToBLabel).HasColumnName("a_to_b_label").HasMaxLength(32).IsRequired();
        builder.Property(x => x.BToALabel).HasColumnName("b_to_a_label").HasMaxLength(32).IsRequired();

        // The endpoints are stored as plain columns rather than json so the database
        // can range-check every coordinate itself.
        builder.ComplexProperty(x => x.A, point =>
        {
            point.Property(p => p.X).HasColumnName("ax");
            point.Property(p => p.Y).HasColumnName("ay");
        });
        builder.ComplexProperty(x => x.B, point =>
        {
            point.Property(p => p.X).HasColumnName("bx");
            point.Property(p => p.Y).HasColumnName("by");
        });

        builder.HasIndex(x => x.LineId).HasDatabaseName("ix_trip_lines_line");
    }
}
