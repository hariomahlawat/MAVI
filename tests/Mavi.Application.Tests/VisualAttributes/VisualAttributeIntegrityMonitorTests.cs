using Mavi.Application.Modules.VisualAttributes;

namespace Mavi.Application.Tests.VisualAttributes;

public sealed class VisualAttributeIntegrityMonitorTests
{
    private static readonly DateTimeOffset Now = new(2026, 9, 28, 12, 0, 0, TimeSpan.Zero);

    [Fact]
    public void EachReportedCropIsOneIncidentHoweverOftenItIsReported()
    {
        var monitor = new VisualAttributeIntegrityMonitor();
        var analysis = Guid.NewGuid();
        Guid[] crops = [Guid.NewGuid(), Guid.NewGuid()];

        Assert.Equal(2, monitor.RecordCompletionIncidents(analysis, crops, Now));
        // The retry of an ambiguous commit, or a later attempt, reports the same crops again.
        Assert.Equal(0, monitor.RecordCompletionIncidents(Guid.NewGuid(), crops, Now.AddMinutes(1)));
        Assert.Equal(1, monitor.RecordCompletionIncidents(analysis, [crops[0], Guid.NewGuid()], Now.AddMinutes(2)));

        var health = monitor.Current;
        Assert.Equal(3, health.CompletionIncidents);
        Assert.Equal(Now.AddMinutes(2), health.LastIncidentUtc);
        Assert.Equal(analysis, health.LastIncidentAnalysisId);
    }

    [Fact]
    public void AReportThatAddsNothingLeavesTheLastIncidentAlone()
    {
        var monitor = new VisualAttributeIntegrityMonitor();
        var first = Guid.NewGuid();
        var crop = Guid.NewGuid();
        monitor.RecordCompletionIncidents(first, [crop], Now);
        monitor.RecordCompletionIncidents(Guid.NewGuid(), [crop], Now.AddMinutes(1));

        Assert.Equal(first, monitor.Current.LastIncidentAnalysisId);
        Assert.Equal(Now, monitor.Current.LastIncidentUtc);
    }

    [Fact]
    public void TheRememberedCropsAreBoundedAndTheOldestIsForgottenFirst()
    {
        var monitor = new VisualAttributeIntegrityMonitor();
        var oldest = Guid.NewGuid();
        monitor.RecordCompletionIncidents(Guid.NewGuid(), [oldest], Now);
        var newest = Guid.NewGuid();
        monitor.RecordCompletionIncidents(Guid.NewGuid(),
            Enumerable.Range(0, VisualAttributeIntegrityMonitor.MaximumRememberedCrops - 1).Select(_ => Guid.NewGuid()).Append(newest).ToList(), Now);

        // At the bound the oldest was evicted: seen again, it counts again; the newest does not.
        Assert.Equal(0, monitor.RecordCompletionIncidents(Guid.NewGuid(), [newest], Now));
        Assert.Equal(1, monitor.RecordCompletionIncidents(Guid.NewGuid(), [oldest], Now));
        Assert.Equal(VisualAttributeIntegrityMonitor.MaximumRememberedCrops + 2, monitor.Current.CompletionIncidents);
    }
}
