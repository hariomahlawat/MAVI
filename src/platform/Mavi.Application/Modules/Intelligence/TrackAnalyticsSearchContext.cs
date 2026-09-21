namespace Mavi.Application.Modules.Intelligence;

/// <summary>
/// The identity an analytic search was resolved to and is pinned to for the life of its
/// cursor chain (plan §S "Revision-pinned cursors", ADR-011 decision 6).
/// </summary>
/// <remarks>
/// <para>
/// <paramref name="CameraId"/> is the single camera every supplied scope resolved to.
/// <paramref name="SceneRevisionId"/> is the revision whose facts are evaluated: the
/// explicit one, else the camera's active revision at the instant of the first page.
/// It is null for exactly one case — a camera that has never been configured. A camera
/// whose active revision deliberately disables analytics still has a revision, and that
/// revision's real id is pinned so that a later enabled revision cannot change what a
/// continuation page means.
/// </para>
/// <para>
/// <paramref name="AlgorithmVersion"/> is the explicit historical version, else the
/// engine version current when the first page was resolved.
/// </para>
/// </remarks>
public sealed record TrackAnalyticsPinnedIdentity(
    Guid CameraId,
    Guid? SceneRevisionId,
    string AlgorithmVersion);

/// <summary>
/// Everything a continuation page of an analytic search needs from its first page: the
/// keyset position and snapshot, the pinned identity, and the coverage block as it was
/// first computed. Carried inside the authenticated v3 cursor and never recomputed.
/// </summary>
public sealed record TrackAnalyticsCursorPosition(
    TrackCursorPosition Position,
    TrackAnalyticsPinnedIdentity Identity,
    TrackAnalyticsCoverage Coverage);
