using System.Security.Cryptography;
using Mavi.Domain.Common;
using Mavi.Domain.SceneAnalytics;

namespace Mavi.Domain.Tests;

/// <summary>
/// The <see cref="SceneAnalysis"/> state machine and its fencing.
/// </summary>
/// <remarks>
/// The concurrency itself is proved against real PostgreSQL in the integration
/// suite; what is pinned here is the aggregate's own reasoning — which transitions
/// are legal, what ownership requires, and what a retry cycle resets — because those
/// are the rules every caller depends on and none of them should have to restate.
/// </remarks>
public sealed class SceneAnalysisTests
{
    private const string Algorithm = "scene-analytics-v1";
    private static readonly string Parameters = new('a', 64);
    private static readonly DateTimeOffset Now = new(2026, 9, 21, 8, 0, 0, TimeSpan.Zero);
    private static readonly TimeSpan Lease = TimeSpan.FromSeconds(900);
    private static readonly TimeSpan Grace = TimeSpan.FromSeconds(60);
    private const int MaximumAttempts = 3;

    private static SceneAnalysis Queued() =>
        SceneAnalysis.Queue(Guid.CreateVersion7(), Guid.CreateVersion7(), Algorithm, Parameters, null, Now);

    private static byte[] Token(byte seed) => [.. Enumerable.Repeat(seed, SceneAnalysis.ClaimTokenByteLength)];

    private static byte[] HashOf(byte[] token) => SHA256.HashData(token);

    /// <summary>Claims the unit and returns the plaintext token the caller would hold.</summary>
    private static byte[] Claim(SceneAnalysis analysis, byte seed, DateTimeOffset nowUtc)
    {
        var token = Token(seed);
        analysis.Claim(HashOf(token), nowUtc, Lease, MaximumAttempts, Grace);
        return token;
    }

    // --- Lifecycle ---------------------------------------------------------

    [Fact]
    public void QueuedUnitStartsWithNoAttemptsAndNoOwner()
    {
        var analysis = Queued();

        Assert.Equal(SceneAnalysisStatus.Queued, analysis.Status);
        Assert.Equal(0, analysis.AttemptCount);
        Assert.Null(analysis.ClaimTokenHash);
        Assert.Null(analysis.LeaseExpiresAtUtc);
        Assert.Null(analysis.StartedAtUtc);
        Assert.Null(analysis.CompletedAtUtc);
        Assert.False(analysis.IsFactBearing);
    }

    [Fact]
    public void ClaimTakesOwnershipAndStartsRunning()
    {
        var analysis = Queued();

        var token = Claim(analysis, 1, Now);

        Assert.Equal(SceneAnalysisStatus.Running, analysis.Status);
        Assert.Equal(1, analysis.AttemptCount);
        Assert.Equal(Now.Add(Lease), analysis.LeaseExpiresAtUtc);
        Assert.Equal(Now, analysis.StartedAtUtc);
        Assert.True(analysis.OwnedBy(1, token));
    }

    [Fact]
    public void CompletionRecordsFactsCountsAndVisibility()
    {
        var analysis = Queued();
        var token = Claim(analysis, 1, Now);

        analysis.Complete(1, token, visibilitySequence: 42, analysedTrackCount: 7, unavailableTrackCount: 2, Now);

        Assert.Equal(SceneAnalysisStatus.Completed, analysis.Status);
        Assert.Equal(42, analysis.VisibilitySequence);
        Assert.Equal(7, analysis.AnalysedTrackCount);
        Assert.Equal(2, analysis.UnavailableTrackCount);
        Assert.Equal(Now, analysis.CompletedAtUtc);
        Assert.True(analysis.IsFactBearing);
        // Ownership is released by completion: nothing owns a finished unit.
        Assert.Null(analysis.ClaimTokenHash);
        Assert.Null(analysis.LeaseExpiresAtUtc);
    }

    [Fact]
    public void AttemptFailureRequeuesWhileAttemptsRemain()
    {
        var analysis = Queued();
        var token = Claim(analysis, 1, Now);

        analysis.FailAttempt(1, token, SceneAnalyticsErrorCodes.EngineFailed, "boom", MaximumAttempts, Now);

        Assert.Equal(SceneAnalysisStatus.Queued, analysis.Status);
        Assert.Equal(1, analysis.AttemptCount);
        Assert.Equal(SceneAnalyticsErrorCodes.EngineFailed, analysis.FailureCode);
        Assert.Null(analysis.ClaimTokenHash);
    }

    [Fact]
    public void AttemptFailureOnTheLastAttemptIsTerminal()
    {
        var analysis = Queued();
        byte[] token = [];
        for (var attempt = 1; attempt <= MaximumAttempts; attempt++)
        {
            token = Claim(analysis, (byte)attempt, Now);
            if (attempt < MaximumAttempts)
            {
                analysis.FailAttempt(attempt, token, SceneAnalyticsErrorCodes.EngineFailed, null, MaximumAttempts, Now);
            }
        }

        analysis.FailAttempt(MaximumAttempts, token, SceneAnalyticsErrorCodes.EngineFailed, null, MaximumAttempts, Now);

        Assert.Equal(SceneAnalysisStatus.Failed, analysis.Status);
        Assert.Equal(MaximumAttempts, analysis.AttemptCount);
        Assert.False(analysis.IsFactBearing);
    }

    [Fact]
    public void SupersedeChangesOnlyCurrency()
    {
        var analysis = Queued();
        var token = Claim(analysis, 1, Now);
        analysis.Complete(1, token, 42, 7, 2, Now);

        analysis.Supersede();

        Assert.Equal(SceneAnalysisStatus.Superseded, analysis.Status);
        // Everything that a pinned query would read is untouched.
        Assert.Equal(42, analysis.VisibilitySequence);
        Assert.Equal(7, analysis.AnalysedTrackCount);
        Assert.Equal(2, analysis.UnavailableTrackCount);
        Assert.Equal(Now, analysis.CompletedAtUtc);
        Assert.True(analysis.IsFactBearing);
    }

    [Fact]
    public void BothSuccessfulStatesAreFactBearingAndFailedIsNot()
    {
        var completed = Queued();
        var token = Claim(completed, 1, Now);
        completed.Complete(1, token, 1, 0, 0, Now);
        Assert.True(completed.IsFactBearing);

        completed.Supersede();
        Assert.True(completed.IsFactBearing);

        var failed = Queued();
        var failedToken = Claim(failed, 1, Now);
        failed.FailAttempt(1, failedToken, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, Now);
        Assert.Equal(SceneAnalysisStatus.Failed, failed.Status);
        Assert.False(failed.IsFactBearing);
    }

    [Theory]
    [InlineData(SceneAnalysisStatus.Queued)]
    [InlineData(SceneAnalysisStatus.Running)]
    [InlineData(SceneAnalysisStatus.Failed)]
    public void SupersedeIsRefusedFromEveryStateButCompleted(SceneAnalysisStatus status)
    {
        var analysis = Queued();
        if (status is SceneAnalysisStatus.Running)
        {
            Claim(analysis, 1, Now);
        }
        else if (status is SceneAnalysisStatus.Failed)
        {
            var token = Claim(analysis, 1, Now);
            analysis.FailAttempt(1, token, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, Now);
        }

        Assert.Throws<DomainValidationException>(() => analysis.Supersede());
    }

    // --- Ownership ---------------------------------------------------------

    [Fact]
    public void OwnershipRequiresRunningAttemptAndToken()
    {
        var analysis = Queued();
        var token = Claim(analysis, 1, Now);

        Assert.True(analysis.OwnedBy(1, token));
        Assert.False(analysis.OwnedBy(2, token));
        Assert.False(analysis.OwnedBy(1, Token(9)));
    }

    [Fact]
    public void ReclaimInvalidatesThePreviousAttemptPermanently()
    {
        var analysis = Queued();
        var first = Claim(analysis, 1, Now);
        var expired = Now.Add(Lease).Add(Grace).AddSeconds(1);

        analysis.Reclaim(HashOf(Token(2)), expired, Lease, MaximumAttempts, Grace);

        Assert.Equal(2, analysis.AttemptCount);
        Assert.False(analysis.OwnedBy(1, first));
        Assert.True(analysis.OwnedBy(2, Token(2)));
    }

    [Fact]
    public void StaleCompletionIsRejectedAndWritesNothing()
    {
        var analysis = Queued();
        var stale = Claim(analysis, 1, Now);
        var expired = Now.Add(Lease).Add(Grace).AddSeconds(1);
        analysis.Reclaim(HashOf(Token(2)), expired, Lease, MaximumAttempts, Grace);

        var exception = Assert.Throws<SceneAnalysisStaleAttemptException>(
            () => analysis.Complete(1, stale, 42, 7, 2, expired));

        Assert.Equal(SceneAnalyticsErrorCodes.AttemptStale, exception.Code);
        Assert.Equal(SceneAnalysisStatus.Running, analysis.Status);
        Assert.Null(analysis.VisibilitySequence);
        Assert.Equal(0, analysis.AnalysedTrackCount);
        Assert.Null(analysis.CompletedAtUtc);
    }

    [Fact]
    public void StaleFailureCannotFailTheCurrentOwner()
    {
        var analysis = Queued();
        var stale = Claim(analysis, 1, Now);
        var expired = Now.Add(Lease).Add(Grace).AddSeconds(1);
        analysis.Reclaim(HashOf(Token(2)), expired, Lease, MaximumAttempts, Grace);

        Assert.Throws<SceneAnalysisStaleAttemptException>(
            () => analysis.FailAttempt(1, stale, SceneAnalyticsErrorCodes.EngineFailed, null, MaximumAttempts, expired));

        Assert.Equal(SceneAnalysisStatus.Running, analysis.Status);
        Assert.Equal(2, analysis.AttemptCount);
        Assert.Null(analysis.FailureCode);
        Assert.True(analysis.OwnedBy(2, Token(2)));
    }

    [Fact]
    public void AnExpiredLeaseAloneDoesNotEndOwnership()
    {
        // ADR-011 decision 4, and the one place this aggregate deliberately differs
        // from VisionJob: expiry means reclaimable, not lost. An attempt that
        // overruns and then finishes still completes.
        var analysis = Queued();
        var token = Claim(analysis, 1, Now);
        var afterExpiry = Now.Add(Lease).AddMinutes(5);

        Assert.True(analysis.OwnedBy(1, token));
        analysis.Complete(1, token, 42, 7, 2, afterExpiry);

        Assert.Equal(SceneAnalysisStatus.Completed, analysis.Status);
    }

    // --- Claim eligibility and exhaustion ----------------------------------

    [Fact]
    public void RunningUnitIsNotReclaimableBeforeTheGraceHasPassed()
    {
        var analysis = Queued();
        Claim(analysis, 1, Now);
        var justExpired = Now.Add(Lease).AddSeconds(1);

        Assert.False(analysis.CanClaim(justExpired, MaximumAttempts, Grace));
        Assert.True(analysis.CanClaim(justExpired.Add(Grace), MaximumAttempts, Grace));
    }

    [Fact]
    public void ExhaustionClearsOwnershipSoTheOverrunningAttemptGoesStale()
    {
        var analysis = Queued();
        byte[] token = [];
        for (var attempt = 1; attempt <= MaximumAttempts; attempt++)
        {
            token = Claim(analysis, (byte)attempt, Now);
            if (attempt < MaximumAttempts)
            {
                analysis.FailAttempt(attempt, token, SceneAnalyticsErrorCodes.EngineFailed, null, MaximumAttempts, Now);
            }
        }

        var afterGrace = Now.Add(Lease).Add(Grace).AddSeconds(1);
        analysis.Exhaust(afterGrace, Grace);

        Assert.Equal(SceneAnalysisStatus.Failed, analysis.Status);
        Assert.Equal(SceneAnalyticsErrorCodes.AttemptsExhausted, analysis.FailureCode);
        Assert.Null(analysis.ClaimTokenHash);
        Assert.False(analysis.OwnedBy(MaximumAttempts, token));
    }

    [Fact]
    public void ExhaustionIsRefusedBeforeTheGraceHasPassed()
    {
        var analysis = Queued();
        Claim(analysis, 1, Now);

        Assert.Throws<DomainValidationException>(() => analysis.Exhaust(Now.Add(Lease).AddSeconds(1), Grace));
    }

    [Fact]
    public void ClaimIsRefusedOnceAttemptsAreSpent()
    {
        var analysis = Queued();
        var token = Claim(analysis, 1, Now);
        analysis.FailAttempt(1, token, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, Now);

        Assert.False(analysis.CanClaim(Now, maximumAttempts: 1, Grace));
    }

    // --- Explicit retry ----------------------------------------------------

    [Fact]
    public void ExplicitRetryResetsTheCycleOnTheSameUnit()
    {
        var analysis = Queued();
        var identity = analysis.Id;
        byte[] token = [];
        for (var attempt = 1; attempt <= MaximumAttempts; attempt++)
        {
            token = Claim(analysis, (byte)attempt, Now);
            analysis.FailAttempt(attempt, token, SceneAnalyticsErrorCodes.EngineFailed, "boom", MaximumAttempts, Now);
        }

        Assert.Equal(SceneAnalysisStatus.Failed, analysis.Status);
        var retriedAt = Now.AddHours(1);

        analysis.Retry(retriedAt);

        Assert.Equal(identity, analysis.Id);
        Assert.Equal(SceneAnalysisStatus.Queued, analysis.Status);
        Assert.Equal(0, analysis.AttemptCount);
        Assert.Null(analysis.ClaimTokenHash);
        Assert.Null(analysis.LeaseExpiresAtUtc);
        Assert.Null(analysis.FailureCode);
        Assert.Null(analysis.FailureDetails);
        Assert.Equal(retriedAt, analysis.QueuedAtUtc);
        Assert.Null(analysis.StartedAtUtc);
        Assert.Null(analysis.CompletedAtUtc);
    }

    [Fact]
    public void ExhaustedUnitIsRetryableAndClaimableAgain()
    {
        var analysis = Queued();
        Claim(analysis, 1, Now);
        var afterGrace = Now.Add(Lease).Add(Grace).AddSeconds(1);
        analysis.Exhaust(afterGrace, Grace);

        analysis.Retry(afterGrace);

        Assert.True(analysis.CanClaim(afterGrace, MaximumAttempts, Grace));
    }

    [Theory]
    [InlineData(SceneAnalysisStatus.Queued)]
    [InlineData(SceneAnalysisStatus.Running)]
    [InlineData(SceneAnalysisStatus.Completed)]
    [InlineData(SceneAnalysisStatus.Superseded)]
    public void ExplicitRetryIsRefusedFromEveryStateButFailed(SceneAnalysisStatus status)
    {
        var analysis = Queued();
        if (status is not SceneAnalysisStatus.Queued)
        {
            var token = Claim(analysis, 1, Now);
            if (status is not SceneAnalysisStatus.Running)
            {
                analysis.Complete(1, token, 1, 0, 0, Now);
                if (status is SceneAnalysisStatus.Superseded)
                {
                    analysis.Supersede();
                }
            }
        }

        Assert.Throws<DomainValidationException>(() => analysis.Retry(Now));
    }

    [Fact]
    public void AfterARetryResetAColllidingAttemptNumberIsStillRejectedOnTheToken()
    {
        // The reason RequireOwnership checks both halves. A retry resets the attempt
        // to 0, so the next claim takes 1 — the same number a stale attempt from the
        // previous cycle may hold. Only the token separates them.
        var analysis = Queued();
        var stale = Claim(analysis, 1, Now);
        analysis.FailAttempt(1, stale, SceneAnalyticsErrorCodes.EngineFailed, null, maximumAttempts: 1, Now);
        analysis.Retry(Now.AddHours(1));

        var fresh = Claim(analysis, 2, Now.AddHours(1));

        Assert.Equal(1, analysis.AttemptCount);
        Assert.False(analysis.OwnedBy(1, stale));
        Assert.True(analysis.OwnedBy(1, fresh));
        Assert.Throws<SceneAnalysisStaleAttemptException>(
            () => analysis.Complete(1, stale, 42, 1, 0, Now.AddHours(1)));
    }

    // --- Identity ----------------------------------------------------------

    [Fact]
    public void IdentityFieldsAreRecordedAndValidated()
    {
        var run = Guid.CreateVersion7();
        var revision = Guid.CreateVersion7();

        var analysis = SceneAnalysis.Queue(run, revision, Algorithm, Parameters, "abc1234", Now);

        Assert.Equal(run, analysis.ProcessingRunId);
        Assert.Equal(revision, analysis.RevisionId);
        Assert.Equal(Algorithm, analysis.AlgorithmVersion);
        Assert.Equal(Parameters, analysis.ParametersSha256);
        Assert.Equal("abc1234", analysis.SourceCommit);
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("NOTHEX")]
    public void QueueRefusesAParameterHashThatIsNotCanonicalSha256(string parameters)
    {
        Assert.Throws<DomainValidationException>(
            () => SceneAnalysis.Queue(Guid.CreateVersion7(), Guid.CreateVersion7(), Algorithm, parameters, null, Now));
    }

    [Fact]
    public void QueueRefusesEmptyIdentifiers()
    {
        Assert.Throws<DomainValidationException>(
            () => SceneAnalysis.Queue(Guid.Empty, Guid.CreateVersion7(), Algorithm, Parameters, null, Now));
        Assert.Throws<DomainValidationException>(
            () => SceneAnalysis.Queue(Guid.CreateVersion7(), Guid.Empty, Algorithm, Parameters, null, Now));
    }
}
