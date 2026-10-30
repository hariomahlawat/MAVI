using Mavi.Domain.Cameras;
using Mavi.Domain.Common;

namespace Mavi.Domain.Tests;

public sealed class CameraTests
{
    [Fact]
    public void CreateProducesUuidV7AndNormalizedCode()
    {
        var camera = Camera.Create(" cam-0001 ", "Main Gate", "Asia/Kolkata");

        Assert.Equal(7, camera.Id.Version);
        Assert.Equal("CAM-0001", camera.Code);
        Assert.Equal("Main Gate", camera.Name);
        Assert.True(camera.IsActive);
    }

    [Fact]
    public void CreateRejectsBlankCode()
    {
        var ex = Assert.Throws<DomainValidationException>(
            () => Camera.Create(" ", "Main Gate", "Asia/Kolkata"));

        Assert.Equal("camera_code_required", ex.Code);
    }

    [Fact]
    public void ASiteCodeIsAnOptionalLowerCaseTokenFixedAtCreation()
    {
        var at = new DateTimeOffset(2026, 10, 30, 0, 0, 0, TimeSpan.Zero);
        Assert.Null(Camera.Create("CAM-1", "Gate", "UTC", at).SiteCode);
        Assert.Equal("meva-2018-03-11-1620", Camera.Create("CAM-2", "Hall", "UTC", at, " MEVA-2018-03-11-1620 ").SiteCode);
        foreach (var invalid in new[] { "", " ", "-site", "site a", "site/a", new string('a', 65) })
            Assert.Equal("camera_site_code_invalid",
                Assert.Throws<Mavi.Domain.Common.DomainValidationException>(() => Camera.Create("CAM-3", "X", "UTC", at, invalid)).Code);
    }
}
