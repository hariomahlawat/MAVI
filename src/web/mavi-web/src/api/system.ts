export type SystemConfig = {
  displayTimeZoneId: string;
};

// Safe runtime configuration
export async function getSystemConfig(signal?: AbortSignal): Promise<SystemConfig> {
  const response = await fetch('/api/system/config', { signal });
  if (!response.ok) throw new Error(`System configuration request failed with HTTP ${response.status}.`);
  return (await response.json()) as SystemConfig;
}
