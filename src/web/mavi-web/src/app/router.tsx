import { Navigate, createBrowserRouter, type RouteObject } from 'react-router-dom';
import AppShell from './AppShell';
import CamerasPage from '../features/cameras/CamerasPage';
import VideoImportPage from '../features/video-import/VideoImportPage';
import ProcessingPage from '../features/processing/ProcessingPage';
import VisualSearchPage from '../features/visual-search/VisualSearchPage';
import VideoReviewPage from '../features/video-review/VideoReviewPage';

export const appRoutes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/cameras" replace /> },
      { path: 'cameras', element: <CamerasPage /> },
      { path: 'import', element: <VideoImportPage /> },
      { path: 'processing/:videoAssetId', element: <ProcessingPage /> },
      { path: 'search', element: <VisualSearchPage /> },
      { path: 'review/video/:videoAssetId', element: <VideoReviewPage /> },
      {
        path: '*',
        element: (
          <section className="panel">
            <h1>Page not found</h1>
            <p>The requested MAVI page does not exist.</p>
          </section>
        ),
      },
    ],
  },
];

export const router = createBrowserRouter(appRoutes);
