using Mavi.Api.Middleware;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;

namespace Mavi.IntegrationTests;

public sealed class RequestCancellationMiddlewareTests
{
    [Fact]
    public async Task RequestAbortCancellationIsHandledAsNormalControlFlow()
    {
        using var services = new ServiceCollection().BuildServiceProvider();
        var builder = new ApplicationBuilder(services);
        builder.UseMaviRequestCancellationHandling();
        builder.Run(_ => throw new OperationCanceledException("request aborted"));

        var pipeline = builder.Build();
        using var abort = new CancellationTokenSource();
        abort.Cancel();

        var context = new DefaultHttpContext
        {
            RequestServices = services,
            RequestAborted = abort.Token,
        };

        await pipeline(context);
    }

    [Fact]
    public async Task OperationCanceledExceptionPropagatesWhenRequestWasNotAborted()
    {
        using var services = new ServiceCollection().BuildServiceProvider();
        var builder = new ApplicationBuilder(services);
        builder.UseMaviRequestCancellationHandling();
        builder.Run(_ => throw new OperationCanceledException("not request cancellation"));

        var pipeline = builder.Build();
        var context = new DefaultHttpContext
        {
            RequestServices = services,
            RequestAborted = CancellationToken.None,
        };

        var exception = await Assert.ThrowsAsync<OperationCanceledException>(() => pipeline(context));
        Assert.Equal("not request cancellation", exception.Message);
    }

    [Fact]
    public async Task NonCancellationExceptionsAreNeverSuppressed()
    {
        using var services = new ServiceCollection().BuildServiceProvider();
        var builder = new ApplicationBuilder(services);
        builder.UseMaviRequestCancellationHandling();
        builder.Run(_ => throw new InvalidOperationException("boom"));

        var pipeline = builder.Build();
        var context = new DefaultHttpContext
        {
            RequestServices = services,
        };

        var exception = await Assert.ThrowsAsync<InvalidOperationException>(() => pipeline(context));
        Assert.Equal("boom", exception.Message);
    }
}
