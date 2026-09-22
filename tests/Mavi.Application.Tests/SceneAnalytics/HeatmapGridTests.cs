using Mavi.Application.Modules.SceneAnalytics.Aggregates;
using Mavi.Contracts.Api.Analytics;

namespace Mavi.Application.Tests.SceneAnalytics;

/// <summary>Grid mapping and accumulation fixtures (plan §5.3, §13.1).</summary>
public sealed class HeatmapGridTests
{
    [Fact]
    public void AnEmptyGridIsAllZeroWithNoMaximum()
    {
        var grid = new HeatmapGrid(64, 36);

        Assert.Equal(64 * 36, grid.Values.Count);
        Assert.All(grid.Values, value => Assert.Equal(0, value));
        Assert.Equal(0, grid.SampleCount);
        Assert.Equal(0, grid.MaxCellValue);
    }

    [Theory]
    [InlineData(16, 9)]
    [InlineData(32, 18)]
    [InlineData(64, 36)]
    [InlineData(128, 72)]
    public void EverySupportedGridHasItsSixteenByNineHeightAndExactCellCount(int width, int height)
    {
        Assert.Equal(height, AnalyticsQueryRules.GridHeightFor(width));

        var grid = new HeatmapGrid(width, AnalyticsQueryRules.GridHeightFor(width));
        Assert.Equal(width * height, grid.Values.Count);
    }

    [Fact]
    public void TheOriginLandsInTheFirstCellAndTheFarCornerInTheLast()
    {
        var grid = new HeatmapGrid(16, 9);

        grid.Add(0, 0);
        grid.Add(1, 1);

        Assert.Equal(1, grid.Values[0]);
        Assert.Equal(1, grid.Values[^1]);
        Assert.Equal(2, grid.SampleCount);
    }

    [Fact]
    public void ACoordinateOfExactlyOneIsTheLastCellNotAnOutOfRangeOne()
    {
        // The discriminating case for the mapping: x * width is exactly width here,
        // which is one past the end if it is not folded back.
        var grid = new HeatmapGrid(4, 4);

        grid.Add(1, 0);

        Assert.Equal(1, grid.Values[3]);
    }

    [Fact]
    public void ValuesAreRowMajor()
    {
        var grid = new HeatmapGrid(4, 4);

        // Second column of the third row: index = row * width + column.
        grid.Add(0.30, 0.55);

        Assert.Equal(1, grid.Values[(2 * 4) + 1]);
        Assert.Equal(1, grid.Values.Sum());
    }

    [Fact]
    public void CellBoundariesBelongToTheHigherCell()
    {
        var grid = new HeatmapGrid(4, 1);

        // 0.25 is exactly the boundary between the first and second column.
        grid.Add(0.25, 0);
        grid.Add(0.2499999, 0);

        Assert.Equal(1, grid.Values[0]);
        Assert.Equal(1, grid.Values[1]);
    }

    [Fact]
    public void RepeatedSamplesAccumulateInOneCellAndRaiseTheMaximum()
    {
        var grid = new HeatmapGrid(8, 8);

        for (var i = 0; i < 5; i++)
        {
            grid.Add(0.5, 0.5);
        }

        grid.Add(0.1, 0.1);

        Assert.Equal(6, grid.SampleCount);
        Assert.Equal(5, grid.MaxCellValue);
        Assert.Equal(6, grid.Values.Sum());
    }

    [Fact]
    public void TheMatrixTotalIsAlwaysTheSampleCount()
    {
        // Sample-count weighting: one sample, one unit, no smoothing anywhere.
        var grid = new HeatmapGrid(16, 9);
        var random = new Random(20260922);

        for (var i = 0; i < 500; i++)
        {
            grid.Add(random.NextDouble(), random.NextDouble());
        }

        Assert.Equal(500, grid.SampleCount);
        Assert.Equal(500, grid.Values.Sum());
    }

    [Theory]
    [InlineData(double.NaN, 0.5)]
    [InlineData(0.5, double.NaN)]
    [InlineData(double.PositiveInfinity, 0.5)]
    [InlineData(-0.0001, 0.5)]
    [InlineData(0.5, 1.0001)]
    public void AnOutOfContractSampleFailsVisiblyRatherThanBeingClamped(double x, double y)
    {
        var grid = new HeatmapGrid(16, 9);

        Assert.Throws<HeatmapEvidenceException>(() => grid.Add(x, y));
        // Nothing was recorded: a corrupt sample must not leave a plausible mark.
        Assert.Equal(0, grid.SampleCount);
        Assert.All(grid.Values, value => Assert.Equal(0, value));
    }

    [Fact]
    public void TheSameSamplesAlwaysProduceTheSameMatrix()
    {
        static HeatmapGrid Build()
        {
            var grid = new HeatmapGrid(32, 18);
            var random = new Random(7);
            for (var i = 0; i < 200; i++)
            {
                grid.Add(random.NextDouble(), random.NextDouble());
            }

            return grid;
        }

        Assert.Equal(Build().Values, Build().Values);
    }
}
