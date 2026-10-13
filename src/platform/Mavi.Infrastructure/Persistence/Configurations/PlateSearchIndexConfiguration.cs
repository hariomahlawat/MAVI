using Mavi.Domain.Plates;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;

namespace Mavi.Infrastructure.Persistence.Configurations;

/// <summary>
/// The plate search indexes on <c>plate_track_texts.normalised_text</c> (Stage 4 PR-4, plan §2.8; migration
/// <c>AddPlateSearchIndexes</c>). Kept apart from PR-3's fact configuration, which owns the table, so
/// the lifecycle's integrity schema and the search's access paths evolve separately.
/// </summary>
/// <remarks>
/// <para>
/// <b>contains</b> is <c>LIKE '%T%'</c>, which only a trigram index serves: a GIN index with the
/// <c>pg_trgm</c> contrib extension's <c>gin_trgm_ops</c>. The query text is at least three characters
/// (the shortest a trigram can be), so every contains search has at least one whole trigram.
/// </para>
/// <para>
/// <b>prefix</b> is <c>LIKE 'T%'</c> and <b>exact</b> is equality, both served by a b-tree with
/// <c>text_pattern_ops</c>, which compares bytes and so supports a left-anchored <c>LIKE</c> whatever the
/// database collation is.
/// </para>
/// <para>
/// The predicate itself uses no <c>pg_trgm</c> operator or function: without the trigram index a contains
/// search is still exact, only slower. The extension is therefore an access-path dependency, never a
/// semantic one.
/// </para>
/// </remarks>
public sealed class PlateSearchIndexConfiguration : IEntityTypeConfiguration<PlateTrackText>
{
    public const string TrigramIndexName = "ix_plate_track_texts_normalised_text_trgm";
    public const string PatternIndexName = "ix_plate_track_texts_normalised_text_pattern";

    public void Configure(EntityTypeBuilder<PlateTrackText> builder)
    {
        builder.HasIndex(x => x.NormalisedText, TrigramIndexName)
            .HasMethod("gin")
            .HasOperators("gin_trgm_ops");
        builder.HasIndex(x => x.NormalisedText, PatternIndexName)
            .HasOperators("text_pattern_ops");
    }
}
