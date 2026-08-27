import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles/global.css';

// Some older screens still call fetch('/api/...') directly instead of using
// services/api.js. Vite's dev proxy hides that locally, but a production build
// can point at a separate API origin through VITE_API_URL. Keep those legacy
// calls working until they are migrated to the shared API client.
const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/+$/, '');
if (API_BASE && typeof window !== 'undefined') {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    if (typeof input === 'string' && input.startsWith('/api/')) {
      return nativeFetch(`${API_BASE}${input}`, init);
    }
    return nativeFetch(input, init);
  };
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
