using System.Collections.Concurrent;
using System.Diagnostics;
using Mavi.Application.Modules.Intelligence;
using Mavi.Infrastructure.Persistence.Repositories;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>
/// A test-only decorator of the real <see cref="IVisionFinalizationLifecycle"/> that timestamps
/// every call on the same monotonic clock as <see cref="PublicationTimelineRecorder"/> and marks
/// <c>PublishAsync</c>'s async flow with a <see cref="PublicationScope"/>. It changes no argument,
/// result or exception: the executor and the hosted finalizer run exactly as they ship.
/// </summary>
internal sealed class FinalizationTimingDecorator(IVisionFinalizationLifecycle inner, LifecycleCallLog log) : IVisionFinalizationLifecycle
{
    /// <summary>Registers the decorator around the real lifecycle for one test host.</summary>
    public static void Register(IServiceCollection services, LifecycleCallLog log)
    {
        services.RemoveAll<IVisionFinalizationLifecycle>();
        services.AddScoped<VisionFinalizationLifecycle>();
        services.AddScoped<IVisionFinalizationLifecycle>(provider => new FinalizationTimingDecorator(provider.GetRequiredService<VisionFinalizationLifecycle>(), log));
    }

    private async Task<T> TimeAsync<T>(string method, Guid? jobId, Func<Task<T>> call, Func<T, (Guid? Job, string Result)> describe)
    {
        var enter = Stopwatch.GetTimestamp();
        var enterUtc = DateTimeOffset.UtcNow;
        try
        {
            var result = await call();
            var (job, text) = describe(result);
            log.Add(new LifecycleCall(method, job ?? jobId, enter, Stopwatch.GetTimestamp(), enterUtc, DateTimeOffset.UtcNow, text));
            return result;
        }
        catch (Exception exception)
        {
            log.Add(new LifecycleCall(method, jobId, enter, Stopwatch.GetTimestamp(), enterUtc, DateTimeOffset.UtcNow, "threw " + exception.GetType().Name));
            throw;
        }
    }

    public Task<VisionFinalizationClaim?> ClaimNextAsync(VisionFinalizationPolicy policy, CancellationToken cancellationToken) =>
        TimeAsync(nameof(ClaimNextAsync), null, () => inner.ClaimNextAsync(policy, cancellationToken), r => (r?.JobId, r is null ? "none" : "claimed"));

    public Task<VisionFinalizationExtension> ExtendClaimAsync(VisionFinalizationClaim claim, VisionFinalizationPolicy policy, CancellationToken cancellationToken) =>
        TimeAsync(nameof(ExtendClaimAsync), claim.JobId, () => inner.ExtendClaimAsync(claim, policy, cancellationToken), r => (claim.JobId, r.Status.ToString()));

    public Task<VisionFinalizationInputs?> LoadInputsAsync(VisionFinalizationClaim claim, CancellationToken cancellationToken) =>
        TimeAsync(nameof(LoadInputsAsync), claim.JobId, () => inner.LoadInputsAsync(claim, cancellationToken), r => (claim.JobId, r is null ? "none" : "loaded"));

    public async Task<VisionFinalizationTransition> PublishAsync(VisionFinalizationClaim claim, ValidatedVisionResult result, FinalizationGraphPlan graph, CancellationToken cancellationToken)
    {
        PublicationScope.Enter();
        try
        {
            return await TimeAsync(nameof(PublishAsync), claim.JobId, () => inner.PublishAsync(claim, result, graph, cancellationToken), r => (claim.JobId, r.Kind.ToString()));
        }
        finally
        {
            PublicationScope.Exit();
        }
    }

    public Task<VisionFinalizationTransition> FailAsync(VisionFinalizationClaim claim, string code, string? details, CancellationToken cancellationToken) =>
        TimeAsync(nameof(FailAsync), claim.JobId, () => inner.FailAsync(claim, code, details, cancellationToken), r => (claim.JobId, r.Kind.ToString()));

    public Task<VisionFinalizationTransition> NoteTransientAsync(VisionFinalizationClaim claim, string code, bool releaseClaim, CancellationToken cancellationToken) =>
        TimeAsync(nameof(NoteTransientAsync), claim.JobId, () => inner.NoteTransientAsync(claim, code, releaseClaim, cancellationToken), r => (claim.JobId, r.Kind.ToString()));

    public Task<VisionFinalizationReconciliation> ExhaustAbandonedAsync(VisionFinalizationPolicy policy, int batchSize, CancellationToken cancellationToken) =>
        TimeAsync(nameof(ExhaustAbandonedAsync), null, () => inner.ExhaustAbandonedAsync(policy, batchSize, cancellationToken), r => (null, r.Exhausted.ToString(System.Globalization.CultureInfo.InvariantCulture)));

    public Task<int> CleanUpPayloadsAsync(int batchSize, TimeSpan grace, CancellationToken cancellationToken) =>
        TimeAsync(nameof(CleanUpPayloadsAsync), null, () => inner.CleanUpPayloadsAsync(batchSize, grace, cancellationToken), r => (null, r.ToString(System.Globalization.CultureInfo.InvariantCulture)));

    public Task<VisionFinalizationCounts> CountAsync(CancellationToken cancellationToken) =>
        TimeAsync(nameof(CountAsync), null, () => inner.CountAsync(cancellationToken), _ => (null, "counted"));
}

internal sealed record LifecycleCall(string Method, Guid? JobId, long EnterTicks, long ExitTicks, DateTimeOffset EnterUtc, DateTimeOffset ExitUtc, string Result);

internal sealed class LifecycleCallLog
{
    private readonly ConcurrentQueue<LifecycleCall> _calls = new();

    public void Add(LifecycleCall call) => _calls.Enqueue(call);

    public IReadOnlyList<LifecycleCall> Calls => [.. _calls.OrderBy(c => c.EnterTicks)];

    public IReadOnlyList<LifecycleCall> For(Guid jobId) => [.. Calls.Where(c => c.JobId == jobId)];

    public void Clear() => _calls.Clear();
}
