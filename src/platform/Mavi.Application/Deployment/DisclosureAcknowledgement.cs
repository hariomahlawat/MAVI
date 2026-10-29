using Mavi.Application.Modules.Audit;

namespace Mavi.Application.Deployment;

/// <summary>
/// The S11-min sample attributable mutation (ADR-010 §8): an operator acknowledges the disclosure the
/// host serves. Its only state is its audit entry.
/// </summary>
public static class DisclosureAcknowledgement
{
    public const string Action = "deployment.disclosure-acknowledged";
    public const string SubjectType = "deployment";

    /// <summary>The text an operator acknowledges: the profile's statement, or the identity statement on an unprofiled host.</summary>
    public static string AcknowledgedText(DeploymentDisclosure disclosure)
    {
        ArgumentNullException.ThrowIfNull(disclosure);
        return disclosure.Statement ?? disclosure.Identity.Statement;
    }

    /// <summary>Records the acknowledgement, or returns <see langword="null"/> when the statement is not the one served.</summary>
    public static async Task<AuditEntryReceipt?> RecordAsync(IAuditWriter audit, DeploymentDisclosure disclosure, string? statement,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(audit);
        var expected = AcknowledgedText(disclosure);
        if (!string.Equals(statement, expected, StringComparison.Ordinal))
            return null;
        return await audit.AppendAndCommitAsync(
            new AuditRecord(Action, SubjectType, disclosure.Profile,
                new { disclosure.Profile, Statement = expected, IdentityMode = disclosure.Identity.Mode }),
            cancellationToken);
    }
}
