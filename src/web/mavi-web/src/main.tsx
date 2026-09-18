import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import AppProviders from './app/AppProviders';
import './app.css';

const root = document.getElementById('root');
if (!root) throw new Error('MAVI root element was not found.');

createRoot(root).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
);
