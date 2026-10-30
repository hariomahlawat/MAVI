using Mavi.Application.Modules.Entities;
using Mavi.Domain.Intelligence;

namespace Mavi.Application.Tests.Entities;

/// <summary>
/// The candidate catalogue, the plausibility model and the confirmation rule of ADR-023 (§3, §4, §6), without a database.
/// </summary>
public sealed class EntityCandidateRuleTests
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 30, 9, 40, 0, TimeSpan.Zero);
    private static readonly Guid CameraA = Guid.Parse("00000000-0000-7000-8000-00000000000a");
    private static readonly Guid CameraB = Guid.Parse("00000000-0000-7000-8000-00000000000b");
    private static readonly EntityCandidateCatalogueDefinition Catalogue = EntityCandidateCatalogue.Current;

    private static PlausibilityTrack Track(Guid camera, double start, double end, int id = 0) =>
        new(id == 0 ? Guid.CreateVersion7() : new Guid(id, 0, 0, new byte[8]), camera, T0.AddSeconds(start), T0.AddSeconds(end));

    [Fact]
    public void TheCatalogueNamesASourceForEveryParameterAndHasAStableDigest()
    {
        Assert.Equal("mavi-entity-candidates-v2", Catalogue.CatalogueVersion);
        Assert.True(Catalogue.CrossCameraOnly);
        Assert.True(Catalogue.RequireSharedSite);
        Assert.Equal(0.85, Catalogue.AppearanceFloor);
        Assert.Equal(2_000, Catalogue.ConcurrencyToleranceMs);
        Assert.All(Catalogue.Parameters, parameter =>
        {
            Assert.Contains(parameter.Source, new[] { EntityCandidateCatalogue.SourceCatalogue, EntityCandidateCatalogue.SourceOwnerDecision });
            Assert.False(string.IsNullOrWhiteSpace(parameter.Rationale));
        });
        Assert.Equal(["appearanceFloor", "cameras", "site", "concurrencyToleranceMs", "minimumTravelMs", "perTrackBound"],
            Catalogue.Parameters.Where(item => item.Source == EntityCandidateCatalogue.SourceOwnerDecision).Select(item => item.Name));
        Assert.Matches("^[0-9a-f]{64}$", Catalogue.Sha256);
        Assert.Equal(Catalogue.Sha256, (Catalogue with { }).Sha256);
        Assert.NotEqual(Catalogue.Sha256, (Catalogue with { AppearanceFloor = 0.9 }).Sha256);
        Assert.NotEqual(Catalogue.Sha256, (Catalogue with { RequireSharedSite = false }).Sha256);
        Assert.NotEqual(EntityCandidateCatalogue.V1.Sha256, Catalogue.Sha256);
    }

    [Theory]
    [InlineData(false, "site-a", "site-a", true)]
    [InlineData(true, "site-a", "site-a", false)]
    [InlineData(false, "site-a", "site-b", false)]
    [InlineData(false, null, null, false)]
    [InlineData(false, "site-a", null, false)]
    public void VersionTwoProposesOnlyDifferentCamerasOfOneDeclaredSite(bool sameCamera, string? firstSite, string? secondSite, bool inScope)
    {
        var first = Track(CameraA, 0, 10) with { SiteCode = firstSite };
        var second = Track(sameCamera ? CameraA : CameraB, 20, 30) with { SiteCode = secondSite };
        Assert.Equal(inScope, EntityCandidatePlausibility.InScope(first, second, Catalogue));
        Assert.Equal(inScope, EntityCandidatePlausibility.InScope(second, first, Catalogue));
        // Version 1 had no scope rule.
        Assert.True(EntityCandidatePlausibility.InScope(first, second, EntityCandidateCatalogue.V1));
    }

    [Theory]
    // Same camera: any overlap is two objects; touching or later is a plausible revisit.
    [InlineData(true, 0, 10, 5, 15, false, "same_camera_concurrent", -5_000)]
    [InlineData(true, 0, 10, 10, 15, true, null, 0)]
    [InlineData(true, 0, 10, 40, 50, true, null, 30_000)]
    // Another camera: overlap up to the 2 s tolerance is plausible, beyond it the object would be in two places.
    [InlineData(false, 0, 10, 8, 20, true, null, -2_000)]
    [InlineData(false, 0, 10, 7.9, 20, false, "concurrent_elsewhere", -2_100)]
    [InlineData(false, 0, 10, 2, 5, false, "concurrent_elsewhere", -3_000)]
    [InlineData(false, 30, 40, 0, 10, true, null, 20_000)]
    public void ThePlausibilityModelUsesOnlyCamerasAndIntervals(
        bool sameCamera, double firstStart, double firstEnd, double secondStart, double secondEnd, bool plausible, string? reason, long gapMs)
    {
        var first = Track(CameraA, firstStart, firstEnd);
        var second = Track(sameCamera ? CameraA : CameraB, secondStart, secondEnd);
        var verdict = EntityCandidatePlausibility.Evaluate(first, second, Catalogue);
        Assert.Equal(plausible, verdict.Plausible);
        Assert.Equal(reason, verdict.Reason);
        Assert.Equal(gapMs, verdict.GapMs);
        Assert.Equal(sameCamera, verdict.SameCamera);
        // Symmetric: the order of the pair never changes the verdict.
        Assert.Equal(verdict, EntityCandidatePlausibility.Evaluate(second, first, Catalogue));
    }

    [Fact]
    public void TwoFreeTracksCreateAnEntity()
    {
        var plan = EntityConfirmationRules.Plan(Track(CameraA, 0, 10), null, Track(CameraB, 20, 30), null, null, Catalogue);
        Assert.Equal(EntityConfirmationKind.CreateEntity, plan.Kind);
    }

    [Fact]
    public void ATrackJoinsAnEntityOnlyWhenPlausibleAgainstEveryMember()
    {
        var entityId = Guid.CreateVersion7();
        var member1 = Track(CameraA, 0, 10, 1);
        var member2 = Track(CameraB, 100, 110, 2);
        var members = new EntityMembers(entityId, EntityType.Person, [member1, member2]);

        var joining = Track(CameraB, 50, 60, 3);
        var extend = EntityConfirmationRules.Plan(member1, entityId, joining, null, members, Catalogue);
        Assert.Equal(EntityConfirmationKind.ExtendEntity, extend.Kind);
        Assert.Equal(joining.TrackId, extend.JoiningTrackId);

        // Plausible with the member it was paired with, but at the same time as another member elsewhere.
        var clash = Track(CameraA, 95, 105, 4);
        var refused = EntityConfirmationRules.Plan(member1, entityId, clash, null, members, Catalogue);
        Assert.Equal(EntityConfirmationKind.Refused, refused.Kind);
        Assert.Equal(EntityConfirmationRules.ExtensionImplausible, refused.RefusalCode);
        Assert.Equal(member2.TrackId, refused.ConflictingTrackId);
    }

    [Fact]
    public void TwoEntitiesAreNeverMergedAndOneEntityIsAlreadyLinked()
    {
        var a = Guid.CreateVersion7();
        var b = Guid.CreateVersion7();
        var merge = EntityConfirmationRules.Plan(Track(CameraA, 0, 10), a, Track(CameraB, 20, 30), b, null, Catalogue);
        Assert.Equal(EntityConfirmationRules.MergeUnsupported, merge.RefusalCode);
        var linked = EntityConfirmationRules.Plan(Track(CameraA, 0, 10), a, Track(CameraB, 20, 30), a, null, Catalogue);
        Assert.Equal(EntityConfirmationKind.AlreadyLinked, linked.Kind);
        Assert.Equal(a, linked.EntityId);
    }
}
