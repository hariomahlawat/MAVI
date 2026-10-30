using System.Text.RegularExpressions;
using Mavi.Domain.Common;
using Mavi.Domain.Intelligence;

namespace Mavi.Domain.Tests;

/// <summary>
/// ADR-023 at the domain layer: a candidate's pair is canonical and decided once; an Entity is an operator decision,
/// never an identification; and confirmation is the only code path that writes <c>Track.EntityId</c>.
/// </summary>
public sealed partial class EntityCandidateTests
{
    private static readonly DateTimeOffset T0 = new(2026, 10, 30, 12, 0, 0, TimeSpan.Zero);
    private static readonly string Fingerprint = new('a', 64);
    private static readonly EntityCandidateDecider Operator = new("S-1-5-21-1", @"HOST\operator", "windows-negotiate");

    private static EntityCandidate Candidate(Guid first, Guid second) =>
        EntityCandidate.Create(Guid.CreateVersion7(), "mavi-entity-candidates-v1", Fingerprint, first, second, ObjectClass.Person, 0.9, false, 6_000, T0);

    [Fact]
    public void ThePairIsStoredInCanonicalOrderWhicheverWayItIsGiven()
    {
        var a = Guid.CreateVersion7();
        var b = Guid.CreateVersion7();
        var forward = Candidate(a, b);
        var backward = Candidate(b, a);
        Assert.Equal((forward.LowerTrackId, forward.HigherTrackId), (backward.LowerTrackId, backward.HigherTrackId));
        Assert.True(forward.LowerTrackId.CompareTo(forward.HigherTrackId) < 0);
        Assert.Equal(EntityCandidateStatus.Open, forward.Status);
        Assert.Null(forward.EntityId);
    }

    [Fact]
    public void InvalidCandidatesAreRefused()
    {
        var a = Guid.CreateVersion7();
        Assert.Throws<DomainValidationException>(() => Candidate(a, a));
        Assert.Throws<DomainValidationException>(() => EntityCandidate.Create(Guid.CreateVersion7(), "v1", Fingerprint, a, Guid.CreateVersion7(),
            (ObjectClass)99, 0.9, false, 0, T0));
        Assert.Throws<DomainValidationException>(() => EntityCandidate.Create(Guid.CreateVersion7(), "v1", Fingerprint, a, Guid.CreateVersion7(),
            ObjectClass.Vehicle, 1.5, false, 0, T0));
        Assert.Throws<DomainValidationException>(() => EntityCandidate.Create(Guid.CreateVersion7(), "v1", "not-a-sha", a, Guid.CreateVersion7(),
            ObjectClass.Vehicle, 0.9, false, 0, T0));
    }

    [Fact]
    public void ADecisionIsAttributableAndFinal()
    {
        var candidate = Candidate(Guid.CreateVersion7(), Guid.CreateVersion7());
        var entityId = Guid.CreateVersion7();
        var auditId = Guid.CreateVersion7();
        candidate.Confirm(entityId, Operator, "  same coat  ", auditId, T0);
        Assert.Equal(EntityCandidateStatus.Confirmed, candidate.Status);
        Assert.Equal(entityId, candidate.EntityId);
        Assert.Equal("same coat", candidate.DecisionNote);
        Assert.Equal(auditId, candidate.DecisionAuditEntryId);
        Assert.Equal(Operator.OperatorId, candidate.DecidedByOperatorId);
        Assert.Equal("windows-negotiate", candidate.DecidedByIdentitySource);

        var error = Assert.Throws<DomainValidationException>(() => candidate.Dismiss(Operator, null, Guid.CreateVersion7(), T0));
        Assert.Equal("entity_candidate_already_decided", error.Code);
    }

    [Fact]
    public void ADismissalWritesNoEntityAndANoteIsBounded()
    {
        var candidate = Candidate(Guid.CreateVersion7(), Guid.CreateVersion7());
        Assert.Throws<DomainValidationException>(() => candidate.Dismiss(Operator, new string('x', 501), Guid.CreateVersion7(), T0));
        Assert.Throws<DomainValidationException>(() => candidate.Dismiss(Operator, null, Guid.Empty, T0));
        candidate.Dismiss(Operator, "   ", Guid.CreateVersion7(), T0);
        Assert.Equal(EntityCandidateStatus.Dismissed, candidate.Status);
        Assert.Null(candidate.EntityId);
        Assert.Null(candidate.DecisionNote);
    }

    [Fact]
    public void AnEntityIsAnOperatorDecisionNeverAnIdentification()
    {
        var entity = Entity.CreateByConfirmation(EntityType.Vehicle, T0);
        Assert.Equal(IdentityStatus.Unknown, entity.IdentityStatus);
        Assert.Equal(ReviewStatus.Confirmed, entity.ReviewStatus);
        Assert.StartsWith("V-", entity.DisplayCode, StringComparison.Ordinal);
        Assert.Equal(Entity.DisplayCodeLength, entity.DisplayCode.Length);
        Assert.Equal(T0, entity.CreatedAtUtc);
    }

    [Fact]
    public void ATrackJoinsOneEntityOnly()
    {
        var track = Track.Create(Guid.CreateVersion7(), Guid.CreateVersion7(), 1, ObjectClass.Person, 0, 1_000, T0, 2, 0.8, 0.9, T0);
        Assert.Null(track.EntityId);
        var first = Guid.CreateVersion7();
        track.JoinEntityByConfirmation(first);
        track.JoinEntityByConfirmation(first);
        Assert.Equal(first, track.EntityId);
        Assert.Throws<DomainValidationException>(() => track.JoinEntityByConfirmation(Guid.CreateVersion7()));
        Assert.Throws<DomainValidationException>(() => track.JoinEntityByConfirmation(Guid.Empty));
    }

    /// <summary>
    /// ADR-023 §1: confirmation is the only writer of <c>Track.EntityId</c>. The domain method is called from the
    /// confirmation repository alone, nothing else assigns the property, and no SQL in the platform or the vision
    /// worker writes the column.
    /// </summary>
    [Fact]
    public void NoPathWritesTrackEntityIdExceptConfirmation()
    {
        var root = FindRepositoryRoot();
        var platform = Path.Combine(root, "src", "platform");
        var callers = Directory.EnumerateFiles(platform, "*.cs", SearchOption.AllDirectories)
            .Where(path => File.ReadAllText(path).Contains("JoinEntityByConfirmation(", StringComparison.Ordinal))
            .Select(path => Path.GetRelativePath(root, path).Replace('\\', '/'))
            .Order(StringComparer.Ordinal)
            .ToList();
        Assert.Equal(
            ["src/platform/Mavi.Domain/Intelligence/Track.cs", "src/platform/Mavi.Infrastructure/Persistence/Repositories/EntityCandidateRepository.cs"],
            callers);

        var trackSource = File.ReadAllText(Path.Combine(platform, "Mavi.Domain", "Intelligence", "Track.cs"));
        Assert.Single(AssignmentPattern().Matches(trackSource));

        var sources = Directory.EnumerateFiles(Path.Combine(root, "src"), "*.*", SearchOption.AllDirectories)
            .Where(path => path.EndsWith(".cs", StringComparison.Ordinal) || path.EndsWith(".py", StringComparison.Ordinal) ||
                           path.EndsWith(".sql", StringComparison.Ordinal))
            .Where(path => !path.Replace('\\', '/').Contains("/Migrations/", StringComparison.Ordinal) &&
                           !path.Replace('\\', '/').Contains("/obj/", StringComparison.Ordinal) &&
                           !path.Replace('\\', '/').Contains("/bin/", StringComparison.Ordinal));
        foreach (var path in sources)
            Assert.False(SqlWritePattern().IsMatch(File.ReadAllText(path)), $"{path} writes tracks.entity_id outside confirmation.");
    }

    [GeneratedRegex(@"\bEntityId\s*=\s*entityId\s*;")]
    private static partial Regex AssignmentPattern();

    [GeneratedRegex(@"(?is)\b(UPDATE\s+tracks\b[^;]*\bentity_id\b|INSERT\s+INTO\s+tracks\b[^;]*\bentity_id\b|SetProperty\(\s*\w+\s*=>\s*\w+\.EntityId)")]
    private static partial Regex SqlWritePattern();

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new InvalidOperationException("Repository root not found.");
    }
}
