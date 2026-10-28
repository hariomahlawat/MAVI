using Mavi.Application.Deployment;
using Microsoft.Extensions.Options;

namespace Mavi.Api.Deployment;

/// <summary>
/// The deployment disclosure (ADR-020 §3): profile, Production-qualification status,
/// evidence class, resolved device and reason, and every bound pack's identity and
/// verification status. Read per request, so a worker relaunch is reflected without
/// restarting the platform.
/// </summary>
public static class DeploymentEndpoints
{
    public static IEndpointRouteBuilder MapDeploymentEndpoints(this IEndpointRouteBuilder endpoints)
    {
        endpoints.MapGet("/api/system/deployment",
            (IOptions<DeploymentOptions> options) => Results.Ok(DeploymentDisclosureReader.Read(options.Value)));
        return endpoints;
    }

    /// <summary>
    /// Refuses to start a host whose declared profile is unknown, or a PoC host whose
    /// release metadata is missing or claims anything other than the fixed disclosure.
    /// </summary>
    public static void VerifyDeploymentDisclosure(this WebApplication app)
    {
        ArgumentNullException.ThrowIfNull(app);
        DeploymentDisclosureReader.Verify(app.Services.GetRequiredService<IOptions<DeploymentOptions>>().Value);
    }
}
