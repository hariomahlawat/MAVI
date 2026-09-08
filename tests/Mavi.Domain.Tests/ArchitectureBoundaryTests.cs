using System.Xml.Linq;

namespace Mavi.Domain.Tests;

public sealed class ArchitectureBoundaryTests
{
    [Fact]
    public void ProjectReferencesFollowApprovedDependencyDirection()
    {
        var root = FindRepositoryRoot();

        AssertReferences(root, "Mavi.Domain", []);
        AssertReferences(root, "Mavi.Contracts", []);
        AssertReferences(root, "Mavi.Application", ["Mavi.Domain", "Mavi.Contracts"]);
        AssertReferences(root, "Mavi.Infrastructure", ["Mavi.Application", "Mavi.Domain", "Mavi.Contracts"]);
        AssertReferences(root, "Mavi.Api", ["Mavi.Application", "Mavi.Infrastructure", "Mavi.Contracts"]);
    }

    private static void AssertReferences(string root, string projectName, string[] expected)
    {
        var projectFile = Path.Combine(root, "src", "platform", projectName, $"{projectName}.csproj");
        var doc = XDocument.Load(projectFile);
        var actual = doc.Descendants("ProjectReference")
            .Select(x => Path.GetFileNameWithoutExtension(x.Attribute("Include")?.Value ?? string.Empty))
            .OrderBy(x => x)
            .ToArray();

        Assert.Equal(expected.OrderBy(x => x), actual);
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "MAVI.sln")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        throw new DirectoryNotFoundException("Could not locate MAVI.sln from test output path.");
    }
}
