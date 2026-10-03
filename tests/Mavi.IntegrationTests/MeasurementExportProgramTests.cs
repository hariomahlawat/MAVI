using Mavi.Api.Startup;
using Mavi.Infrastructure.Configuration;
using Mavi.MeasurementExport;
using Microsoft.AspNetCore.Builder;

namespace Mavi.IntegrationTests;

/// <summary>
/// The measurement tool's entry boundary: it resolves the environment and machine file
/// exactly as the web host does, and an unloadable machine file is a refusal, not a crash.
/// </summary>
/// <remarks>
/// These tests change process environment variables, so they run in the serialized
/// collection and restore every variable they touch.
/// </remarks>
[Collection(DatabaseIntegrationGroup.Name)]
public sealed class MeasurementExportProgramTests
{
    [Theory]
    [InlineData("Development", "Production")]
    [InlineData("Production", "Development")]
    public void EnvironmentAndMachinePathMatchTheWebHostWhenBothVariablesDisagree(string dotnet, string aspNetCore)
    {
        using var environment = new EnvironmentScope(
            (MeasurementExportProgram.DotnetEnvironmentVariable, dotnet),
            (MeasurementExportProgram.AspNetCoreEnvironmentVariable, aspNetCore),
            (MachineConfigurationPath.EnvironmentVariable, null));

        var host = WebApplication.CreateBuilder().Environment;
        var tool = MeasurementExportProgram.ResolveEnvironmentName();

        Assert.Equal(dotnet, host.EnvironmentName);
        Assert.Equal(host.EnvironmentName, tool);
        Assert.Equal(MachineConfigurationStartup.GetDefaultPath(host), MachineConfigurationPath.Resolve(tool));
    }

    [Fact]
    public void NeitherVariableDefaultsToProductionLikeTheWebHost()
    {
        using var environment = new EnvironmentScope(
            (MeasurementExportProgram.DotnetEnvironmentVariable, null),
            (MeasurementExportProgram.AspNetCoreEnvironmentVariable, null));

        Assert.Equal(WebApplication.CreateBuilder().Environment.EnvironmentName, MeasurementExportProgram.ResolveEnvironmentName());
        Assert.Equal("Production", MeasurementExportProgram.ResolveEnvironmentName());
    }

    [Fact]
    public async Task MalformedMachineConfigurationIsAConfigurationRefusal()
    {
        var scratch = Scratch();
        try
        {
            var machineFile = Path.Combine(scratch, "appsettings.machine.json");
            await File.WriteAllTextAsync(machineFile, "{ \"ConnectionStrings\": { \"Mavi\": ");
            await AssertConfigurationRefusalAsync(scratch, machineFile);
        }
        finally
        {
            Directory.Delete(scratch, recursive: true);
        }
    }

    [Fact]
    public async Task ExplicitMachineConfigurationThatDoesNotExistIsAConfigurationRefusal()
    {
        var scratch = Scratch();
        try
        {
            await AssertConfigurationRefusalAsync(scratch, Path.Combine(scratch, "absent.machine.json"));
        }
        finally
        {
            Directory.Delete(scratch, recursive: true);
        }
    }

    private static async Task AssertConfigurationRefusalAsync(string scratch, string machineFile)
    {
        using var environment = new EnvironmentScope((MachineConfigurationPath.EnvironmentVariable, machineFile));
        var output = Path.Combine(scratch, "export");
        using var stdout = new StringWriter();
        using var stderr = new StringWriter();

        var exitCode = await MeasurementExportProgram.RunAsync(
            ["--run", Guid.NewGuid().ToString("D"), "--pipeline-profile", Path.Combine(scratch, "profile.json"), "--out", output],
            stdout,
            stderr,
            CancellationToken.None);

        Assert.Equal(MeasurementExportCommand.Refused, exitCode);
        Assert.StartsWith($"refused {MeasurementExportCommand.ConfigurationInvalid}:", stderr.ToString(), StringComparison.Ordinal);
        Assert.False(Directory.Exists(output));
        Assert.Empty(Directory.GetDirectories(scratch));
    }

    private static string Scratch()
    {
        var path = Path.Combine(Path.GetTempPath(), $"mavi-s32-program-{Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        return path;
    }

    private sealed class EnvironmentScope : IDisposable
    {
        private readonly (string Name, string? Value)[] _previous;

        public EnvironmentScope(params (string Name, string? Value)[] values)
        {
            _previous = values.Select(x => (x.Name, Environment.GetEnvironmentVariable(x.Name))).ToArray();
            foreach (var (name, value) in values)
                Environment.SetEnvironmentVariable(name, value);
        }

        public void Dispose()
        {
            foreach (var (name, value) in _previous)
                Environment.SetEnvironmentVariable(name, value);
        }
    }
}
