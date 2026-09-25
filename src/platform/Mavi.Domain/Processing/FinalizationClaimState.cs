namespace Mavi.Domain.Processing;

/// <summary>
/// The canonical states of a Finalizing job's finalizer-claim metadata (F3 plan §5.2). The
/// triple (token hash, expiry, extended-at) is written together by the aggregate; any other
/// combination is <see cref="Malformed"/> and fails closed.
/// </summary>
public enum FinalizationClaimState
{
    /// <summary>No claim has been taken since the hand-off: all three fields are null.</summary>
    Unclaimed,
    /// <summary>All three fields present and the expiry is in the future: exactly one owner.</summary>
    Live,
    /// <summary>All three fields present and the expiry has passed: reclaimable, or exhaustible.</summary>
    Expired,
    /// <summary>Any other combination: never claimed, exhausted, owned or repaired; reported for an operator.</summary>
    Malformed,
}
