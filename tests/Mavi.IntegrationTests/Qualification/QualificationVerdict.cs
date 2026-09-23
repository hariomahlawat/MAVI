using System.Globalization;

namespace Mavi.IntegrationTests.Qualification;

/// <summary>Why a check exists, which decides when its failure is fatal.</summary>
public enum QualificationCheckScope
{
    /// <summary>
    /// The measurement did not do what it says it did. Fatal on any server, because a
    /// harness that measured the wrong thing is broken regardless of the database it
    /// was pointed at.
    /// </summary>
    Integrity,

    /// <summary>
    /// The run does not meet a prerequisite for calling itself qualification evidence —
    /// server version, corpus volume, workload shape. Fatal only on a qualifying
    /// server; elsewhere it is recorded and the run stays an engineering observation.
    /// </summary>
    Prerequisite,
}

/// <summary>One recorded expectation and whether the run met it.</summary>
public sealed record QualificationCheck(
    QualificationCheckScope Scope,
    string Name,
    bool Satisfied,
    string Detail);

/// <summary>
/// The collected expectations of one qualification measurement, and the rule that
/// decides whether it may be reported as green.
/// </summary>
/// <remarks>
/// <para>
/// This exists because the harness has already been wrong twice in the same way:
/// a measurement that executed almost nothing still produced a complete, fast,
/// entirely plausible evidence file, and the test asserted only that the file
/// existed. Patching each instance as it is found does not address the shape of
/// the mistake, so every harness now states its expectations here and every
/// expectation is written into the evidence beside the numbers it qualifies.
/// </para>
/// <para>
/// The governing rule is <em>no evidence is better than false evidence</em>: an
/// unmet expectation fails the run rather than being footnoted, and the evidence
/// file is still written so the failure can be investigated.
/// </para>
/// <para>
/// The two scopes are kept apart deliberately. An integrity failure means the
/// harness did not measure its subject, which is a defect on PostgreSQL 16 just
/// as much as on 18. A prerequisite failure means the run is real but cannot be
/// called qualification evidence, which on PostgreSQL 16 is simply the expected
/// state of affairs and must not turn the suite red.
/// </para>
/// </remarks>
public sealed class QualificationVerdict(bool qualificationGrade)
{
    private readonly List<QualificationCheck> _checks = [];

    /// <summary>Whether this run is on the server that can produce qualification evidence.</summary>
    public bool QualificationGrade { get; } = qualificationGrade;

    public IReadOnlyList<QualificationCheck> Checks => _checks;

    /// <summary>The measurement must have exercised what it claims. Fatal anywhere.</summary>
    public void RequireIntegrity(string name, bool satisfied, string detail) =>
        _checks.Add(new QualificationCheck(QualificationCheckScope.Integrity, name, satisfied, detail));

    /// <summary>The run must meet this to be called qualification evidence.</summary>
    public void RequireForQualification(string name, bool satisfied, string detail) =>
        _checks.Add(new QualificationCheck(QualificationCheckScope.Prerequisite, name, satisfied, detail));

    /// <summary>Convenience for an expected count, recording both sides of the comparison.</summary>
    public void RequireIntegrityEqual(string name, long expected, long actual) =>
        RequireIntegrity(
            name,
            expected == actual,
            string.Create(CultureInfo.InvariantCulture, $"expected {expected}, measured {actual}"));

    /// <summary>
    /// The checks whose failure must fail this run, given where it is running.
    /// </summary>
    public IReadOnlyList<QualificationCheck> BlockingFailures =>
    [
        .. _checks.Where(check => !check.Satisfied
            && (check.Scope == QualificationCheckScope.Integrity || QualificationGrade)),
    ];

    /// <summary>Everything unmet, including what is merely recorded on this server.</summary>
    public IReadOnlyList<QualificationCheck> Unmet => [.. _checks.Where(check => !check.Satisfied)];

    /// <summary>
    /// What this run may be called: qualification evidence, an engineering
    /// observation, or a failure.
    /// </summary>
    public string Status =>
        BlockingFailures.Count > 0 ? "qualification failure"
        : QualificationGrade && Unmet.Count == 0 ? "qualification evidence"
        : "engineering observation — not qualification evidence";

    /// <summary>The shape written into the evidence file.</summary>
    public object ToEvidence() => new
    {
        status = Status,
        qualificationGradeDatabase = QualificationGrade,
        checks = _checks.Select(check => new
        {
            scope = check.Scope.ToString(),
            name = check.Name,
            satisfied = check.Satisfied,
            detail = check.Detail,
        }),
    };

    /// <summary>
    /// Fails the run when an expectation that matters here was not met, naming every
    /// one and pointing at the evidence written for it.
    /// </summary>
    public void Enforce(string evidencePath)
    {
        var failures = BlockingFailures;
        if (failures.Count == 0) return;

        var detail = string.Join(
            Environment.NewLine,
            failures.Select(check => $"  - [{check.Scope}] {check.Name}: {check.Detail}"));

        throw new QualificationFailedException(
            $"The qualification measurement did not satisfy {failures.Count} expectation(s), so its "
            + $"output is not evidence:{Environment.NewLine}{detail}{Environment.NewLine}"
            + $"Diagnostic evidence: {evidencePath}");
    }
}

/// <summary>Raised when a measurement cannot be reported as having measured its subject.</summary>
public sealed class QualificationFailedException(string message) : Exception(message);
