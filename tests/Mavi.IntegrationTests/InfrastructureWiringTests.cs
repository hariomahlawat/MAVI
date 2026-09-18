using Mavi.Application.Abstractions.Storage;
using Mavi.Application.Modules.Media;
using Mavi.Infrastructure.Storage;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

public sealed class InfrastructureWiringTests
{
    [Fact]
    public void MetadataReaderResolvesAndStorageInterfacesShareSingleton()
    {
        using var factory = new ApiTestFactory();

        var reader = factory.Services.GetRequiredService<IVideoMetadataReader>();
        var mediaStore = factory.Services.GetRequiredService<IMediaStore>();
        var concreteStore = factory.Services.GetRequiredService<LocalMediaStore>();

        Assert.NotNull(reader);
        Assert.Same(concreteStore, mediaStore);
    }
}
