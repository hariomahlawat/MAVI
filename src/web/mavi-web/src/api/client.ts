export type ApiErrorShape = {
  status: number;
  code: string;
  detail: string;
  videoAssetId?: string;
  /**
   * The problem's non-standard members, verbatim. RFC 7807 lets a problem carry
   * typed data alongside its code, and some refusals are only actionable with it
   * — a rejected scope says which bound fired and what it is, which is what lets
   * a surface tell the operator how to narrow the request instead of only that
   * it was refused. Read through a narrowing accessor; the wire is not trusted
   * to have the shape a caller hopes for.
   */
  extensions?: Readonly<Record<string, unknown>>;
};

const standardProblemMembers = new Set(['type', 'title', 'status', 'detail', 'instance', 'code']);

/** One extension as a number, or undefined if the wire did not carry one. */
export function problemNumber(error: unknown, key: string): number | undefined {
  const value = error instanceof ApiError ? error.extensions[key] : undefined;
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** One extension as a non-empty string, or undefined. */
export function problemText(error: unknown, key: string): string | undefined {
  const value = error instanceof ApiError ? error.extensions[key] : undefined;
  return typeof value === 'string' && value.trim() ? value : undefined;
}

const genericDetail = 'The request could not be completed.';

/**
 * Local read calls must not remain pending forever. MAVI is an offline-first
 * application, so a temporarily unavailable local API must become an explicit
 * recoverable error rather than an indefinite loading state.
 *
 * Mutating requests are deliberately not given this default: uploads and other
 * writes can legitimately take longer and have their own operation semantics.
 */
export const DEFAULT_API_READ_TIMEOUT_MS = 10_000;


function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function isGuid(value: unknown): value is string {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export class ApiError extends Error implements ApiErrorShape {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly videoAssetId?: string;
  readonly extensions: Readonly<Record<string, unknown>>;

  constructor(shape: ApiErrorShape) {
    super(shape.detail);
    this.name = 'ApiError';
    this.status = shape.status;
    this.code = shape.code;
    this.detail = shape.detail;
    this.videoAssetId = shape.videoAssetId;
    this.extensions = shape.extensions ?? {};
  }
}

async function readError(response: Response): Promise<ApiError> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const body = isRecord(payload) ? payload : {};
  const code = typeof body.code === 'string' && body.code.trim() ? body.code : 'api_error';
  const detail = typeof body.detail === 'string' && body.detail.trim() ? body.detail : genericDetail;
  const videoAssetId = code === 'video_duplicate' && isGuid(body.videoAssetId) ? body.videoAssetId : undefined;

  const extensions: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(body)) {
    if (!standardProblemMembers.has(key)) extensions[key] = value;
  }

  return new ApiError({ status: response.status, code, detail, videoAssetId, extensions });
}

function isReadRequest(init: RequestInit): boolean {
  const method = (init.method ?? 'GET').toUpperCase();
  return method === 'GET' || method === 'HEAD';
}

function boundedReadSignal(
  callerSignal: AbortSignal | null | undefined,
  timeoutMs: number,
): { signal: AbortSignal; dispose: () => void } {
  const controller = new AbortController();
  let timeoutId: ReturnType<typeof setTimeout> | undefined;

  const forwardAbort = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) {
    forwardAbort();
  } else {
    callerSignal?.addEventListener('abort', forwardAbort, { once: true });
    timeoutId = setTimeout(() => {
      controller.abort(new DOMException(
        `Local API read did not respond within ${timeoutMs} ms.`,
        'TimeoutError',
      ));
    }, timeoutMs);
  }

  return {
    signal: controller.signal,
    dispose: () => {
      if (timeoutId !== undefined) clearTimeout(timeoutId);
      callerSignal?.removeEventListener('abort', forwardAbort);
    },
  };
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const bounded = isReadRequest(init)
    ? boundedReadSignal(init.signal, DEFAULT_API_READ_TIMEOUT_MS)
    : null;

  try {
    const response = await fetch(path, bounded ? { ...init, signal: bounded.signal } : init);
    if (!response.ok) throw await readError(response);

    if (response.status === 204) return undefined as T;
    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('json')) return undefined as T;
    return (await response.json()) as T;
  } finally {
    bounded?.dispose();
  }
}

export async function apiJson<T>(
  path: string,
  method: 'POST' | 'PUT' | 'PATCH',
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return apiRequest<T>(path, {
    method,
    signal,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
