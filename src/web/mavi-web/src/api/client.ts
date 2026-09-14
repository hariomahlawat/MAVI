export type ApiErrorShape = {
  status: number;
  code: string;
  detail: string;
  videoAssetId?: string;
};

const genericDetail = 'The request could not be completed.';

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

  constructor(shape: ApiErrorShape) {
    super(shape.detail);
    this.name = 'ApiError';
    this.status = shape.status;
    this.code = shape.code;
    this.detail = shape.detail;
    this.videoAssetId = shape.videoAssetId;
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

  return new ApiError({ status: response.status, code, detail, videoAssetId });
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) throw await readError(response);

  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) return undefined as T;
  return (await response.json()) as T;
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
