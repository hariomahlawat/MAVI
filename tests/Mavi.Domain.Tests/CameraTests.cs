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
}
