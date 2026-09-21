using Mavi.Domain.Intelligence;
using Mavi.Domain.Processing;
using Mavi.Domain.Scene;
using Mavi.Domain.SceneAnalytics;
using Mavi.Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Metadata;

namespace Mavi.IntegrationTests;

/// <summary>
/// What the EF model says about the analytics schema, read straight off the built
/// model. No database is touched, so these run everywhere; the constraints that only
/// PostgreSQL can enforce are proved separately in <see cref="SceneAnalyticsSchemaTests"/>.
/// </summary>
public sealed class SceneAnalyticsModelTests
{
    private static readonly IModel Model = BuildModel();

    // Tables and keys
    [Theory]
    [InlineData(typeof(SceneAnalysis), "scene_analyses")]
    [InlineData(typeof(TrackAnalysisOutcome), "track_analysis_outcomes")]
    [InlineData(typeof(TrackZoneVisit), "track_zone_visits")]
    [InlineData(typeof(TrackZoneSummary), "track_zone_summaries")]
    [InlineData(typeof(TrackLineCrossing), "track_line_crossings")]
    [InlineData(typeof(TrackMotionSummary), "track_motion_summaries")]
    public void EachEntityMapsToItsFrozenTableName(Type entity, string table)
    {
        Assert.Equal(table, Entity(entity).GetTableName());
    }

    [Theory]
    [InlineData(typeof(SceneAnalysis), new[] { "id" })]
    [InlineData(typeof(TrackAnalysisOutcome), new[] { "analysis_id", "track_id" })]
    [InlineData(typeof(TrackZoneSummary), new[] { "analysis_id", "track_id", "zone_id" })]
    [InlineData(typeof(TrackMotionSummary), new[] { "analysis_id", "track_id" })]
    [InlineData(typeof(TrackZoneVisit), new[] { "id" })]
    [InlineData(typeof(TrackLineCrossing), new[] { "id" })]
    public void PrimaryKeysAreTheFrozenIdentities(Type entity, string[] columns)
    {
        var key = Entity(entity).FindPrimaryKey();
        Assert.NotNull(key);
        Assert.Equal(columns, key.Properties.Select(ColumnName));
    }

    // Relationships
    /// <summary>
    /// A unit owns its facts, so deleting it takes them with it; a same-unit rewrite
    /// relies on the same ownership.
    /// </summary>
    [Theory]
    [InlineData(typeof(TrackAnalysisOutcome))]
    [InlineData(typeof(TrackZoneVisit))]
    [InlineData(typeof(TrackZoneSummary))]
    [InlineData(typeof(TrackLineCrossing))]
    [InlineData(typeof(TrackMotionSummary))]
    public void FactsCascadeFromTheirAnalysisUnit(Type entity)
    {
        var fk = ForeignKeyTo(entity, typeof(SceneAnalysis));
        Assert.Equal(DeleteBehavior.Cascade, fk.DeleteBehavior);
        Assert.Equal(["analysis_id"], fk.Properties.Select(ColumnName));
    }

    /// <summary>
    /// Derived analytics must never become a route by which sealed detector evidence
    /// is deleted, so every fact restricts its Track.
    /// </summary>
    [Theory]
    [InlineData(typeof(TrackAnalysisOutcome))]
    [InlineData(typeof(TrackZoneVisit))]
    [InlineData(typeof(TrackZoneSummary))]
    [InlineData(typeof(TrackLineCrossing))]
    [InlineData(typeof(TrackMotionSummary))]
    public void FactsRestrictTheirTrack(Type entity)
    {
        var fk = ForeignKeyTo(entity, typeof(Track));
        Assert.Equal(DeleteBehavior.Restrict, fk.DeleteBehavior);
        Assert.Equal(["track_id"], fk.Properties.Select(ColumnName));
    }

    [Fact]
    public void TheUnitRestrictsBothItsRunAndItsRevision()
    {
        Assert.Equal(DeleteBehavior.Restrict, ForeignKeyTo(typeof(SceneAnalysis), typeof(ProcessingRun)).DeleteBehavior);
        Assert.Equal(
            DeleteBehavior.Restrict,
            ForeignKeyTo(typeof(SceneAnalysis), typeof(SceneConfigurationRevision)).DeleteBehavior);
    }

    // Column mapping
    [Fact]
    public void LifecycleStateIsStoredAsItsName()
    {
        var status = Entity(typeof(SceneAnalysis)).GetProperty(nameof(SceneAnalysis.Status));
        Assert.Equal("status", ColumnName(status));
        Assert.Equal(typeof(string), status.GetProviderClrType());
        Assert.Equal(32, status.GetMaxLength());
        Assert.False(status.IsNullable);
    }

    [Fact]
    public void OutcomeKindIsStoredAsItsName()
    {
        var outcome = Entity(typeof(TrackAnalysisOutcome)).GetProperty(nameof(TrackAnalysisOutcome.Outcome));
        Assert.Equal(typeof(string), outcome.GetProviderClrType());
        Assert.Equal(32, outcome.GetMaxLength());
    }

    /// <summary>Vocabulary columns are sized from the vocabulary, not guessed.</summary>
    [Theory]
    [InlineData(typeof(TrackZoneVisit), nameof(TrackZoneVisit.EntryHeading))]
    [InlineData(typeof(TrackZoneVisit), nameof(TrackZoneVisit.ExitHeading))]
    [InlineData(typeof(TrackMotionSummary), nameof(TrackMotionSummary.Heading))]
    [InlineData(typeof(TrackLineCrossing), nameof(TrackLineCrossing.Direction))]
    [InlineData(typeof(TrackAnalysisOutcome), nameof(TrackAnalysisOutcome.ReferencePoint))]
    public void VocabularyColumnsAreSizedFromTheVocabulary(Type entity, string property)
    {
        Assert.Equal(SceneAnalyticsVocabulary.MaximumLength, Entity(entity).GetProperty(property).GetMaxLength());
    }

    [Fact]
    public void TheClaimTokenHashIsBytesAndOptional()
    {
        var hash = Entity(typeof(SceneAnalysis)).GetProperty(nameof(SceneAnalysis.ClaimTokenHash));
        Assert.Equal("claim_token_hash", ColumnName(hash));
        Assert.Equal(typeof(byte[]), hash.ClrType);
        Assert.True(hash.IsNullable);
    }

    [Theory]
    [InlineData(nameof(TrackMotionSummary.StationaryIntervals), "stationary_intervals")]
    [InlineData(nameof(TrackMotionSummary.StationaryZoneIds), "stationary_zone_ids")]
    public void MotionCollectionsArePersistedAsJsonb(string property, string column)
    {
        var mapped = Entity(typeof(TrackMotionSummary)).GetProperty(property);
        Assert.Equal(column, ColumnName(mapped));
        Assert.Equal("jsonb", mapped.GetColumnType());
        Assert.False(mapped.IsNullable);
    }

    // Indexes
    [Fact]
    public void TheUnitIdentityIsUniqueOnRunRevisionAndAlgorithmVersion()
    {
        var index = Index(typeof(SceneAnalysis), "ux_scene_analyses_identity");
        Assert.True(index.IsUnique);
        Assert.Equal(["processing_run_id", "revision_id", "algorithm_version"], index.Properties.Select(ColumnName));
        Assert.Null(index.GetFilter());
    }

    /// <summary>
    /// Many units have no sequence yet, so the uniqueness has to be partial; PostgreSQL
    /// treats NULLs as distinct, but the filter keeps the index the size of the
    /// completed set rather than of history.
    /// </summary>
    [Fact]
    public void TheVisibilitySequenceIsUniqueOnlyWhereAllocated()
    {
        var index = Index(typeof(SceneAnalysis), "ux_scene_analyses_visibility_sequence");
        Assert.True(index.IsUnique);
        Assert.Equal("visibility_sequence IS NOT NULL", index.GetFilter());
    }

    [Theory]
    [InlineData(typeof(TrackZoneVisit), "ux_track_zone_visits_identity",
        new[] { "analysis_id", "track_id", "zone_id", "visit_index" })]
    [InlineData(typeof(TrackLineCrossing), "ux_track_line_crossings_identity",
        new[] { "analysis_id", "track_id", "line_id", "crossing_index" })]
    public void OrdinalFactsAreUniquePerUnitTrackAndGeometry(Type entity, string name, string[] columns)
    {
        var index = Index(entity, name);
        Assert.True(index.IsUnique);
        Assert.Equal(columns, index.Properties.Select(ColumnName));
    }

    // Check constraints
    [Theory]
    [InlineData(typeof(SceneAnalysis), "ck_scene_analyses_attempt_count")]
    [InlineData(typeof(SceneAnalysis), "ck_scene_analyses_claim_token_hash")]
    [InlineData(typeof(SceneAnalysis), "ck_scene_analyses_parameters_sha256")]
    [InlineData(typeof(SceneAnalysis), "ck_scene_analyses_status")]
    [InlineData(typeof(SceneAnalysis), "ck_scene_analyses_track_counts")]
    [InlineData(typeof(SceneAnalysis), "ck_scene_analyses_visibility_sequence")]
    [InlineData(typeof(TrackAnalysisOutcome), "ck_track_analysis_outcomes_outcome")]
    [InlineData(typeof(TrackAnalysisOutcome), "ck_track_analysis_outcomes_reason")]
    [InlineData(typeof(TrackAnalysisOutcome), "ck_track_analysis_outcomes_reference_point")]
    [InlineData(typeof(TrackAnalysisOutcome), "ck_track_analysis_outcomes_shape")]
    [InlineData(typeof(TrackZoneVisit), "ck_track_zone_visits_dwell")]
    [InlineData(typeof(TrackZoneVisit), "ck_track_zone_visits_headings")]
    [InlineData(typeof(TrackZoneVisit), "ck_track_zone_visits_offsets")]
    [InlineData(typeof(TrackZoneVisit), "ck_track_zone_visits_timestamps")]
    [InlineData(typeof(TrackZoneSummary), "ck_track_zone_summaries_counts")]
    [InlineData(typeof(TrackZoneSummary), "ck_track_zone_summaries_timestamps")]
    [InlineData(typeof(TrackLineCrossing), "ck_track_line_crossings_direction")]
    [InlineData(typeof(TrackLineCrossing), "ck_track_line_crossings_point")]
    [InlineData(typeof(TrackMotionSummary), "ck_track_motion_summaries_durations")]
    [InlineData(typeof(TrackMotionSummary), "ck_track_motion_summaries_heading")]
    [InlineData(typeof(TrackMotionSummary), "ck_track_motion_summaries_json_shape")]
    public void EachFrozenCheckConstraintIsDeclared(Type entity, string name)
    {
        Assert.Contains(Entity(entity).GetCheckConstraints(), c => c.Name == name);
    }

    /// <summary>
    /// The SQL the database enforces is generated from the same vocabulary lists the
    /// entities validate against, so a value the Domain accepts cannot be one the
    /// database rejects.
    /// </summary>
    [Fact]
    public void VocabularyConstraintsAreGeneratedFromTheVocabulary()
    {
        Assert.All(
            SceneAnalyticsVocabulary.Headings,
            heading => Assert.Contains($"'{heading}'", Constraint(typeof(TrackMotionSummary), "ck_track_motion_summaries_heading")));
        Assert.All(
            SceneAnalyticsVocabulary.CrossingDirections,
            direction => Assert.Contains($"'{direction}'", Constraint(typeof(TrackLineCrossing), "ck_track_line_crossings_direction")));
        Assert.All(
            SceneAnalyticsVocabulary.ReferencePoints,
            point => Assert.Contains($"'{point}'", Constraint(typeof(TrackAnalysisOutcome), "ck_track_analysis_outcomes_reference_point")));
        Assert.All(
            SceneAnalyticsErrorCodes.TrackUnavailableReasons,
            reason => Assert.Contains($"'{reason}'", Constraint(typeof(TrackAnalysisOutcome), "ck_track_analysis_outcomes_reason")));
        Assert.All(
            Enum.GetNames<SceneAnalysisStatus>(),
            status => Assert.Contains($"'{status}'", Constraint(typeof(SceneAnalysis), "ck_scene_analyses_status")));
    }

    // Non-goal: lease expiry is not ownership loss (ADR-011 decision 4)
    /// <summary>
    /// An expired lease makes a unit *reclaimable*, never unowned. Persistence must not
    /// short-circuit that: ownership changes only in the reclaim or exhaustion
    /// transaction, under a row lock, which a later phase writes.
    /// </summary>
    /// <remarks>
    /// This is a negative test on purpose. The convenient version of this schema — a
    /// query filter, a computed column or a partial index keyed on the lease clock —
    /// is exactly the defect the ADR forbids, and it would look like an optimisation
    /// in review rather than like a behaviour change.
    /// </remarks>
    [Fact]
    public void NothingInPersistenceTreatsAnExpiredLeaseAsLossOfOwnership()
    {
        var unit = Entity(typeof(SceneAnalysis));

        Assert.Empty(unit.GetDeclaredQueryFilters());

        var lease = unit.GetProperty(nameof(SceneAnalysis.LeaseExpiresAtUtc));
        Assert.Equal(ValueGenerated.Never, lease.ValueGenerated);
        Assert.Null(lease.GetComputedColumnSql());
        Assert.Null(lease.GetDefaultValueSql());

        string[] clockColumns = ["lease_expires_at_utc", "claim_token_hash"];
        foreach (var constraint in unit.GetCheckConstraints())
        {
            // The hash *length* check is about the hash being a hash, not about who owns
            // the unit, so it is the one permitted mention.
            if (constraint.Name == "ck_scene_analyses_claim_token_hash") continue;
            Assert.DoesNotContain(clockColumns, column => constraint.Sql.Contains(column, StringComparison.Ordinal));
        }

        foreach (var index in unit.GetIndexes())
        {
            var filter = index.GetFilter();
            if (filter is null) continue;
            Assert.DoesNotContain(clockColumns, column => filter.Contains(column, StringComparison.Ordinal));
        }

        // The claimer's working set is selected by lifecycle state alone.
        Assert.Equal("status IN ('Queued', 'Running')", Index(typeof(SceneAnalysis), "ix_scene_analyses_pending").GetFilter());
    }

    // Helpers
    private static IModel BuildModel()
    {
        var options = new DbContextOptionsBuilder<MaviDbContext>()
            .UseNpgsql("Host=model-only;Database=mavi_test", npgsql => npgsql.UseVector())
            .Options;
        using var db = new MaviDbContext(options);
        // The design-time model, not the runtime one: check constraints and index
        // filters are stripped from the read-optimised model, and they are precisely
        // what these tests are about.
        return db.GetService<IDesignTimeModel>().Model;
    }

    private static IEntityType Entity(Type clrType) =>
        Model.FindEntityType(clrType) ?? throw new InvalidOperationException($"{clrType.Name} is not mapped.");

    private static IForeignKey ForeignKeyTo(Type entity, Type principal) =>
        Entity(entity).GetForeignKeys().Single(fk => fk.PrincipalEntityType.ClrType == principal);

    private static IIndex Index(Type entity, string name) =>
        Entity(entity).GetIndexes().Single(index => index.GetDatabaseName() == name);

    private static string Constraint(Type entity, string name) =>
        Entity(entity).GetCheckConstraints().Single(c => c.Name == name).Sql;

    private static string ColumnName(IReadOnlyProperty property) =>
        property.GetColumnName() ?? throw new InvalidOperationException($"{property.Name} has no column.");
}
