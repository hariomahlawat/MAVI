namespace Mavi.Domain.Events;

/// <summary>Stable codes for analytic events (ADR-025).</summary>
public static class AnalyticEventErrorCodes
{
    public const string EventInvalid = "analytic_event_invalid";
    public const string DerivationInvalid = "analytic_event_derivation_invalid";
}
