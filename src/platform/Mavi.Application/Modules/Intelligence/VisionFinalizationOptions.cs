namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// The activation gate of asynchronous finalization (S1.4 B3 asynchronous finalization plan
/// §15.2, F2 deployment note). It is one release decision that switches the whole externally
/// visible boundary together: which completion versions <c>GET /api/vision/contract</c>
/// advertises, which <c>POST …/complete</c> accepts, and whether a job can enter
/// <c>Finalizing</c> at all.
/// </summary>
/// <remarks>
/// <para>
/// <see cref="Enabled"/> = <c>false</c> (the default, and the only supported state until the
/// F3 finalizer exists): the platform advertises and accepts completion 2.0 and 3.0, both
/// synchronous, and refuses 3.1. No job can become Finalizing, so none can be stranded
/// without a finalizer to consume it.
/// </para>
/// <para>
/// <see cref="Enabled"/> = <c>true</c> (set by the F3 release, together with the worker's
/// <c>MAVI_COMPLETION_SCHEMA_VERSION=3.1</c>): the platform advertises and accepts 2.0 and
/// 3.1, 3.0 is retired, and 3.1 is the durable hand-off consumed by the hosted finalizer.
/// There is no fallback in either direction: a worker whose version the platform does not
/// advertise fails closed at its capability probe and leases nothing.
/// </para>
/// </remarks>
public sealed class VisionFinalizationOptions
{
    public const string SectionName = "VisionFinalization";

    public bool Enabled { get; init; }
}
