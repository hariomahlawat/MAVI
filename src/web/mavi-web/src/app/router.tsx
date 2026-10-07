import { createBrowserRouter, type RouteObject } from 'react-router-dom';
import AppShell from './AppShell';
import AnalyticsPage from '../features/analytics/AnalyticsPage';
import CamerasPage from '../features/cameras/CamerasPage';
import OverviewPage from '../features/overview/OverviewPage';
import ProcessingPage from '../features/processing/ProcessingPage';
import ProcessingQueuePage from '../features/processing/ProcessingQueuePage';
import SceneEditorPage from '../features/scene-editor/SceneEditorPage';
import VideoImportPage from '../features/video-import/VideoImportPage';
import VideoReviewPage from '../features/video-review/VideoReviewPage';
import VideosPage from '../features/videos/VideosPage';
import VisualSearchPage from '../features/visual-search/VisualSearchPage';
import NotFoundPage from './NotFoundPage';

/**
 * Route paths live here; what each route *is* lives in the IA map
 * (`shared/workspace/ia.ts`). Each route names its §5 surface in `handle`, and
 * the shell reads that to decide the rail highlight, the fallback crumb and the
 * document title — so there is no second table keyed on paths.
 */
export const appRoutes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewPage />, handle: { surface: 'overview' } },
      { path: 'cameras', element: <CamerasPage />, handle: { surface: 'cameras' } },
      { path: 'cameras/:cameraId/scene', element: <SceneEditorPage />, handle: { surface: 'scene' } },
      { path: 'cameras/:cameraId/analytics', element: <AnalyticsPage />, handle: { surface: 'analytics' } },
      { path: 'videos', element: <VideosPage />, handle: { surface: 'videos' } },
      { path: 'import', element: <VideoImportPage />, handle: { surface: 'import' } },
      { path: 'processing', element: <ProcessingQueuePage />, handle: { surface: 'processing' } },
      { path: 'processing/:videoAssetId', element: <ProcessingPage />, handle: { surface: 'processing-detail' } },
      { path: 'search', element: <VisualSearchPage />, handle: { surface: 'search' } },
      { path: 'review/video/:videoAssetId', element: <VideoReviewPage />, handle: { surface: 'review' } },
      { path: '*', element: <NotFoundPage />, handle: { surface: 'not-found' } },
    ],
  },
];

export const router = createBrowserRouter(appRoutes);
