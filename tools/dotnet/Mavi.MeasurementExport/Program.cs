namespace Mavi.MeasurementExport;

internal static class Program
{
    public static async Task<int> Main(string[] args)
    {
        using var cancellation = new CancellationTokenSource();
        Console.CancelKeyPress += (_, eventArgs) =>
        {
            eventArgs.Cancel = true;
            cancellation.Cancel();
        };

        try
        {
            return await MeasurementExportProgram.RunAsync(args, Console.Out, Console.Error, cancellation.Token);
        }
        catch (OperationCanceledException)
        {
            await Console.Error.WriteLineAsync("refused export_cancelled: the export was cancelled; nothing was written.");
            return MeasurementExportCommand.Refused;
        }
    }
}
