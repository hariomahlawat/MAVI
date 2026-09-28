using Mavi.Application.Modules.VisualAttributes.Completion;
using Mavi.Contracts.Worker.Attributes;

namespace Mavi.Api.Endpoints;

/// <summary><c>POST /api/attributes/analyses/{id}/complete</c>: the three-phase publication (S2b plan §13).</summary>
public static class VisualAttributeCompletionEndpoint
{
    public static async Task<IResult> CompleteAsync(
        Guid id,
        HttpContext context,
        VisualAttributeCompleteRequest request,
        IVisualAttributeCompletionService completion,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(context);
        ArgumentNullException.ThrowIfNull(completion);
        if (VisualAttributeEndpoints.Capability(context) is not { } capability) return VisualAttributeEndpoints.CapabilityProblem();
        if (request.SchemaVersion != VisualAttributeContractRules.SchemaVersion) return VisualAttributeEndpoints.VersionProblem();

        var result = await completion.CompleteAsync(id, capability, request, cancellationToken);
        if (result.Status == VisualAttributeCompletionStatus.Refused)
            return VisualAttributeEndpoints.Problem(result.HttpStatus, result.Code!, "The visual attribute completion was rejected.");

        return Results.Ok(new VisualAttributeCompleteResponse(
            VisualAttributeContractRules.SchemaVersion,
            id,
            result.ProcessingRunId!.Value,
            result.Status == VisualAttributeCompletionStatus.Completed ? "completed" : "superseded",
            result.CompletedAtUtc!.Value,
            result.TracksAnalysed,
            result.TracksUnavailable));
    }
}
