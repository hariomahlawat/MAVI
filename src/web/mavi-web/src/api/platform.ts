export type PlatformHealth = {
  status: string;
  component: string;
  version: string;
};

export async function getPlatformHealth(signal?: AbortSignal): Promise<PlatformHealth> {
  const response = await fetch('/api/health', { signal });
  if (!response.ok) {
    throw new Error(`Platform health request failed with HTTP ${response.status}.`);
  }

  return (await response.json()) as PlatformHealth;
}
