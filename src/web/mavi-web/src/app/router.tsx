import { createBrowserRouter, type RouteObject } from 'react-router-dom';
import AppShell from './AppShell';
import CamerasPage from '../features/cameras/CamerasPage';
import OverviewPage from '../features/overview/OverviewPage';
import ProcessingPage from '../features/processing/ProcessingPage';
import ProcessingQueuePage from '../features/processing/ProcessingQueuePage';
import SceneEditorPage from '../features/scene-editor/SceneEditorPage';
import VideoImportPage from '../features/video-import/VideoImportPage';
import VideoReviewPage from '../features/video-review/VideoReviewPage';
import VideosPage from '../features/videos/VideosPage';
import VisualSearchPage from '../features/visual-search/VisualSearchPage';
import EmptyState from '../shared/components/EmptyState';
import { ButtonLink } from '../shared/components/Button';

export const appRoutes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewPage /> },
      { path: 'cameras', element: <CamerasPage /> },
      { path: 'cameras/:cameraId/scene', element: <SceneEditorPage /> },
      { path: 'videos', element: <VideosPage /> },
      { path: 'import', element: <VideoImportPage /> },
      { path: 'processing', element: <ProcessingQueuePage /> },
      { path: 'processing/:videoAssetId', element: <ProcessingPage /> },
      { path: 'search', element: <VisualSearchPage /> },
      { path: 'review/video/:videoAssetId', element: <VideoReviewPage /> },
      {
        path: '*',
        element: (
          <section className="page">
            <h1>Page not found</h1>
            <EmptyState title="The requested MAVI page does not exist." actions={<ButtonLink to="/">Go to Overview</ButtonLink>} />
          </section>
        ),
      },
    ],
  },
];

export const router = createBrowserRouter(appRoutes);
