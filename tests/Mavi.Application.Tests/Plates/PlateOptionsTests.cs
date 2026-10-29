using Mavi.Application.Modules.Plates;

namespace Mavi.Application.Tests.Plates;

/// <summary>
/// PoC S3 (C4.2): the interim re-analysis authorisation is configured as a lowercase SHA-256 or not at all; anything
/// else is refused at start-up rather than read as "no key" or as a key.
/// </summary>
public sealed class PlateOptionsTests
{
    [Fact]
    public void ReanalysisIsUnauthorisedByDefault()
    {
        var options = new PlateOptions();

        Assert.False(options.IsReanalysisAuthorisationConfigured);
        Assert.Empty(options.Validate());
    }

    [Fact]
    public void ALowercaseSha256IsAccepted()
    {
        var options = new PlateOptions { ReanalysisOperatorKeySha256 = new string('a', 32) + new string('0', 32) };

        Assert.True(options.IsReanalysisAuthorisationConfigured);
        Assert.Empty(options.Validate());
    }

    [Theory]
    [InlineData("ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789")]
    [InlineData("abc")]
    [InlineData("an-operator-key-written-where-its-digest-belongs-0000000000000000")]
    public void AnythingElseIsRefusedAtStartUp(string configured)
    {
        var options = new PlateOptions { ReanalysisOperatorKeySha256 = configured };

        Assert.Contains(options.Validate(), problem => problem.Contains("ReanalysisOperatorKeySha256", StringComparison.Ordinal));
    }
}
