import type { AnalyticsReadiness } from '../../api/videos';

/**
 * The readiness vocabulary in operator words (UI/UX §14, plan §S "Processing
 * readiness presentation"). One place, so the Queue's column and the Detail's
 * panel cannot disagree, and no fourth state vocabulary appears beside the
 * readiness the server already derives.
 */
export const ANALYTICS_READINESS_TEXT: Record<AnalyticsReadiness, string> = {
  NotConfigured: 'No scene configured',
  Disabled: 'Disabled by scene',
  Pending: 'Not analysed yet',
  Ready: 'Analysed',
  Failed: 'Analysis failed',
  Stale: 'Stale',
};

export function analyticsReadinessText(readiness: AnalyticsReadiness | undefined): string {
  return readiness ? ANALYTICS_READINESS_TEXT[readiness] ?? readiness : '—';
}
