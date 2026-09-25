namespace Mavi.Domain.Processing;

/// <summary>
/// <c>Queued → Leased → Finalizing → Completed | Failed</c> (S1.4 B3 asynchronous
/// finalization plan §3). <see cref="Finalizing"/> is the durable hand-off: the worker's
/// completion is accepted and retained, the worker lease is over, and the platform
/// finalizer owns the job until it publishes or fails it. Persisted as its name.
/// </summary>
public enum VisionJobStatus { Queued, Leased, Finalizing, Completed, Failed, Cancelled }
