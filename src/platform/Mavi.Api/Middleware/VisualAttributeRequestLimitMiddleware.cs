using Mavi.Contracts.Worker.Attributes;
using Microsoft.AspNetCore.Http.Features;

namespace Mavi.Api.Middleware;

/// <summary>
/// Gives every attribute route its own intentional request-body limit (S2b plan §15). None
/// of them inherits the video-import limit the host otherwise configures (≈3 GiB).
/// </summary>
/// <remarks>
/// A declared <c>Content-Length</c> over the limit is refused with 413 before any byte is
/// read; an undeclared (chunked) body is capped by the server's per-request maximum, which
/// fails the read with 413 at the limit + 1 byte.
/// </remarks>
public static class VisualAttributeRequestLimitMiddleware
{
    /// <summary>A route not listed below takes no body at all.</summary>
    public const long DefaultLimitBytes = 0;

    public static IApplicationBuilder UseVisualAttributeRequestLimits(this IApplicationBuilder app)
    {
        ArgumentNullException.ThrowIfNull(app);
        return app.Use(async (context, next) =>
        {
            if (LimitFor(context.Request.Path) is { } limit)
            {
                var feature = context.Features.Get<IHttpMaxRequestBodySizeFeature>();
                if (feature is { IsReadOnly: false })
                    feature.MaxRequestBodySize = limit;
                if (context.Request.ContentLength is { } length && length > limit)
                {
                    context.Response.StatusCode = StatusCodes.Status413PayloadTooLarge;
                    return;
                }
            }

            await next();
        });
    }

    /// <summary>The limit of an attribute route, or <see langword="null"/> for any other path.</summary>
    public static long? LimitFor(PathString path)
    {
        var value = path.Value;
        if (value is null || !value.StartsWith(VisualAttributeContractRules.RoutePrefix + "/", StringComparison.OrdinalIgnoreCase))
            return null;
        var segments = value[(VisualAttributeContractRules.RoutePrefix.Length + 1)..].Split('/');
        return segments switch
        {
            ["lease"] => VisualAttributeContractRules.MaximumLeaseRequestBodyBytes,
            [_, "heartbeat"] => VisualAttributeContractRules.MaximumHeartbeatRequestBodyBytes,
            [_, "fail"] => VisualAttributeContractRules.MaximumFailRequestBodyBytes,
            [_, "complete"] => VisualAttributeContractRules.MaximumCompletionRequestBodyBytes,
            [_, "predictions"] => VisualAttributeContractRules.MaximumPredictionArtifactBytes,
            _ => DefaultLimitBytes,
        };
    }
}
