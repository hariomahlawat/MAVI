namespace Mavi.Application.Modules.SceneAnalytics.Aggregates;

/// <summary>
/// Raised when a trajectory sample cannot be placed on the grid.
/// </summary>
/// <remarks>
/// A sample outside the normalised contract, or one that is not a finite number, is
/// an evidence-integrity failure — the artefact says something the format forbids.
/// It is not clamped to the nearest edge: clamping would turn corrupt evidence into
/// a plausible map, which is the one outcome an analytical surface must never
/// produce (plan §5.3).
/// </remarks>
public sealed class HeatmapEvidenceException(string message) : Exception(message);

/// <summary>
/// The pure sample-density accumulator: normalised points in, one row-major integer
/// matrix out (plan §5.2, §5.3).
/// </summary>
/// <remarks>
/// Slice 6 weights by sample count only. Each valid sample contributes exactly 1 to
/// exactly one cell — no smoothing, no kernel density, no time-to-next-sample
/// weighting. A second weighting would give the heatmap a second meaning before the
/// first one has been qualified.
/// </remarks>
public sealed class HeatmapGrid
{
    private readonly int[] _cells;

    public HeatmapGrid(int width, int height)
    {
        if (width <= 0 || height <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(width), "Heatmap grid dimensions must be positive.");
        }

        Width = width;
        Height = height;
        _cells = new int[checked(width * height)];
    }

    public int Width { get; }

    public int Height { get; }

    /// <summary>How many samples were accumulated.</summary>
    public long SampleCount { get; private set; }

    /// <summary>The largest value in any cell, or 0 when nothing was accumulated.</summary>
    public int MaxCellValue { get; private set; }

    /// <summary>
    /// Adds one sample at a normalised source-frame position.
    /// </summary>
    /// <exception cref="HeatmapEvidenceException">
    /// The position is not finite or lies outside <c>[0,1]</c>.
    /// </exception>
    public void Add(double x, double y)
    {
        var column = CellIndex(x, Width, "x");
        var row = CellIndex(y, Height, "y");

        // Row-major: the response's values[row * width + column].
        var index = (row * Width) + column;
        var value = ++_cells[index];
        if (value > MaxCellValue)
        {
            MaxCellValue = value;
        }

        SampleCount++;
    }

    /// <summary>The accumulated matrix, row-major, exactly <c>Width × Height</c> entries.</summary>
    public IReadOnlyList<int> Values => _cells;

    /// <summary>
    /// Which cell a normalised coordinate falls in.
    /// </summary>
    /// <remarks>
    /// Multiplying by the extent and truncating sends 0 to the first cell and
    /// everything below 1 to its proportional cell. Exactly 1 would land one past the
    /// end, so it is folded back into the last cell rather than rejected: the
    /// contract says 1 is the far edge of the frame, which is inside it.
    /// </remarks>
    private static int CellIndex(double value, int extent, string axis)
    {
        if (!double.IsFinite(value) || value < 0 || value > 1)
        {
            throw new HeatmapEvidenceException(
                $"A trajectory sample's {axis} coordinate is outside the normalised contract.");
        }

        var index = (int)(value * extent);
        return index >= extent ? extent - 1 : index;
    }
}
