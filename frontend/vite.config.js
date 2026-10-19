import {defineConfig} from 'vite';
import {pwa} from './build/pwa.js';

// Dev: the API runs on :8000 (uvicorn); in production FastAPI serves this build on the same origin.
export default defineConfig({
  plugins:[pwa()],
  server: {proxy: {'/api': process.env.VITE_PROXY_TARGET || 'http://localhost:8000'}},
  preview: {proxy: {'/api': process.env.VITE_PROXY_TARGET || 'http://localhost:8000'}},
});
