using System.Linq.Expressions;
using Mavi.Domain.Intelligence;
using Mavi.Domain.SceneAnalytics;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// The two foreign keys every derived-fact table carries, declared once.
/// </summary>
/// <remarks>
/// <para>
/// Both directions are frozen in §Y and both are load-bearing, so they are declared
/// in one place rather than repeated five times where one copy could quietly differ:
/// </para>
/// <list type="bullet">
/// <item><b>→ analysis: Cascade.</b> A fact has no meaning without its unit, so
/// deleting the unit must take its facts with it.</item>
/// <item><b>→ Track: Restrict.</b> Never let an analytics row hold a Track hostage
/// the other way. Track deletion is already cascade-from-run, and a fact must not
/// redefine that; the existing run-deletion path does not delete runs today, and this
/// keeps the invariant explicit rather than accidental.</item>
/// </list>
/// </remarks>
internal static class SceneAnalyticsFactRelationships
{
    public static void Configure<TFact>(
        EntityTypeBuilder<TFact> builder,
        Expression<Func<TFact, object?>> analysisId,
        Expression<Func<TFact, object?>> trackId)
        where TFact : class
    {
        builder.HasOne<SceneAnalysis>()
            .WithMany()
            .HasForeignKey(analysisId)
            .OnDelete(DeleteBehavior.Cascade);

        builder.HasOne<Track>()
            .WithMany()
            .HasForeignKey(trackId)
            .OnDelete(DeleteBehavior.Restrict);
    }
}
