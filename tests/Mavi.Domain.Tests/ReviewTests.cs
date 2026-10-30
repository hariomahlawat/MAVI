using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;
using Mavi.Domain.Review;

namespace Mavi.Domain.Tests;

/// <summary>ADR-027 §1–§2 domain rules: decisions project the review status; case items record removal once.</summary>
public sealed class ReviewTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 31, 9, 0, 0, TimeSpan.Zero);
    private static readonly string Hash = new('a', 64);

    [Theory]
    [InlineData(TrackReviewDecisionKind.Confirmed, ReviewStatus.Confirmed)]
    [InlineData(TrackReviewDecisionKind.Rejected, ReviewStatus.Rejected)]
    [InlineData(TrackReviewDecisionKind.Cleared, ReviewStatus.Unreviewed)]
    public void ADecisionProjectsItsResultOntoTheTrack(TrackReviewDecisionKind kind, ReviewStatus expected)
    {
        var track = NewTrack();
        if (kind == TrackReviewDecisionKind.Cleared)
            track.ApplyReviewDecision(Decide(track, TrackReviewDecisionKind.Confirmed));

        track.ApplyReviewDecision(Decide(track, kind));

        Assert.Equal(expected, track.ReviewStatus);
        Assert.Null(track.EntityId);
    }

    [Fact]
    public void ADecisionThatDoesNotFollowTheCurrentStatusOrTrackIsRefused()
    {
        var track = NewTrack();
        var other = NewTrack();
        var confirmed = Decide(track, TrackReviewDecisionKind.Confirmed);
        track.ApplyReviewDecision(confirmed);

        Assert.Throws<DomainValidationException>(() => track.ApplyReviewDecision(confirmed));
        Assert.Throws<DomainValidationException>(() => other.ApplyReviewDecision(Decide(track, TrackReviewDecisionKind.Rejected)));
    }

    [Fact]
    public void ClearingAnUnreviewedTrackAndAnOverlongNoteAreRefused()
    {
        var track = NewTrack();
        var cleared = Assert.Throws<DomainValidationException>(() => Decide(track, TrackReviewDecisionKind.Cleared));
        Assert.Equal("track_review_nothing_to_clear", cleared.Code);
        var tooLong = Assert.Throws<DomainValidationException>(() => TrackReviewDecision.NormaliseNote(new string('n', 1001)));
        Assert.Equal("track_review_note_too_long", tooLong.Code);
        Assert.Null(TrackReviewDecision.NormaliseNote("   "));
    }

    [Fact]
    public void ADecisionNeedsServerUtcTimeAnOperatorAndAnAuditEntry()
    {
        var track = NewTrack();
        Assert.Throws<DomainValidationException>(() => TrackReviewDecision.Create(Guid.CreateVersion7(), track.Id,
            TrackReviewDecisionKind.Confirmed, track.ReviewStatus, null, "op", "Op", "windows-negotiate", Now.ToOffset(TimeSpan.FromHours(5)),
            Hash, Guid.CreateVersion7()));
        Assert.Throws<DomainValidationException>(() => TrackReviewDecision.Create(Guid.CreateVersion7(), track.Id,
            TrackReviewDecisionKind.Confirmed, track.ReviewStatus, null, " ", "Op", "windows-negotiate", Now, Hash, Guid.CreateVersion7()));
        Assert.Throws<DomainValidationException>(() => TrackReviewDecision.Create(Guid.CreateVersion7(), track.Id,
            TrackReviewDecisionKind.Confirmed, track.ReviewStatus, null, "op", "Op", "windows-negotiate", Now, Hash, Guid.Empty));
    }

    [Fact]
    public void ACaseItemIsRemovedOnceAndKeepsWhatItWasAddedWith()
    {
        var item = CaseItem.Add(Guid.CreateVersion7(), Guid.CreateVersion7(), CaseItemKind.Track, Guid.CreateVersion7(), " first ", Actor(Now));

        item.Remove("wrong clip", Actor(Now.AddMinutes(1)));

        Assert.Equal("first", item.Note);
        Assert.Equal(Now, item.AddedAtUtc);
        Assert.Equal(Now.AddMinutes(1), item.RemovedAtUtc);
        Assert.Equal("wrong clip", item.RemovalNote);
        var again = Assert.Throws<DomainValidationException>(() => item.Remove(null, Actor(Now.AddMinutes(2))));
        Assert.Equal("case_item_already_removed", again.Code);
    }

    [Fact]
    public void ACaseNeedsATitleAndANoteNeedsABody()
    {
        Assert.Equal("case_title_invalid",
            Assert.Throws<DomainValidationException>(() => InvestigationCase.Create(Guid.CreateVersion7(), " ", null, Actor(Now))).Code);
        Assert.Equal("case_note_invalid",
            Assert.Throws<DomainValidationException>(() => CaseNote.Add(Guid.CreateVersion7(), Guid.CreateVersion7(), "", Actor(Now))).Code);
        Assert.Contains("not asserted to show the same person or vehicle", InvestigationCase.Statement, StringComparison.Ordinal);
    }

    private static Track NewTrack() => Track.Create(Guid.CreateVersion7(), Guid.CreateVersion7(), 1, ObjectClass.Person, 0, 1_000, Now, 3,
        0.6, 0.8, Now);

    private static TrackReviewDecision Decide(Track track, TrackReviewDecisionKind kind) => TrackReviewDecision.Create(Guid.CreateVersion7(),
        track.Id, kind, track.ReviewStatus, null, "S-1-5-21-1", @"HOST\op", "windows-negotiate", Now, Hash, Guid.CreateVersion7());

    private static CaseActor Actor(DateTimeOffset at) => new("S-1-5-21-1", @"HOST\op", "windows-negotiate", at, Guid.CreateVersion7());
}
