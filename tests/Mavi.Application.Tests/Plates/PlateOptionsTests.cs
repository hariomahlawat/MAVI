using Mavi.Application.Modules.Plates;

namespace Mavi.Application.Tests.Plates;

/// <summary>Plate options validate at start-up; re-analysis authorisation is ADR-010 operator identity, not an option.</summary>
public sealed class PlateOptionsTests
{
    [Fact]
    public void TheDefaultsAreValid() => Assert.Empty(new PlateOptions().Validate());

    [Theory]
    [InlineData(0)]
    [InlineData(PlateOptions.MaximumReanalysisRunsCeiling + 1)]
    public void AReanalysisBoundOutsideItsRangeIsRefused(int maximum) =>
        Assert.Contains(new PlateOptions { MaximumRunsPerReanalysisRequest = maximum }.Validate(),
            problem => problem.Contains("MaximumRunsPerReanalysisRequest", StringComparison.Ordinal));
}
