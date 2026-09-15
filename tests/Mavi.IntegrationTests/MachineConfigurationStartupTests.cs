using Mavi.Api.Startup;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.Hosting;

namespace Mavi.IntegrationTests;

public sealed class MachineConfigurationStartupTests
{
    [Fact]
    public void TestingEnvironmentNeverUsesMachineConfiguration()
    {
        var environment = new StubHostEnvironment
        {
            EnvironmentName = "Testing",
        };

        Assert.Null(MachineConfigurationStartup.GetDefaultPath(environment));
    }

    [Fact]
    public void ProductionAndDevelopmentPathsAreWindowsOnlyAndProfileSpecific()
    {
        var development = MachineConfigurationStartup.GetDefaultPath(
            new StubHostEnvironment { EnvironmentName = Environments.Development });
        var production = MachineConfigurationStartup.GetDefaultPath(
            new StubHostEnvironment { EnvironmentName = Environments.Production });

        if (!OperatingSystem.IsWindows())
        {
            Assert.Null(development);
            Assert.Null(production);
            return;
        }

        Assert.EndsWith(
            Path.Combine("MAVI", "Development", "config", "appsettings.development.machine.json"),
            development,
            StringComparison.OrdinalIgnoreCase);
        Assert.EndsWith(
            Path.Combine("MAVI", "config", "appsettings.machine.json"),
            production,
            StringComparison.OrdinalIgnoreCase);
        Assert.NotEqual(development, production);
    }

    private sealed class StubHostEnvironment : IHostEnvironment
    {
        public string EnvironmentName { get; set; } = Environments.Production;
        public string ApplicationName { get; set; } = "Mavi.IntegrationTests";
        public string ContentRootPath { get; set; } = AppContext.BaseDirectory;
        public IFileProvider ContentRootFileProvider { get; set; } = NullFileProvider.Instance;
    }
}
