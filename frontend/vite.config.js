import {defineConfig} from 'vite';

// Dev: the API runs on :8000 (uvicorn); in production FastAPI serves this build on the same origin.
export default defineConfig({
  server: {proxy: {'/api': process.env.VITE_PROXY_TARGET || 'http://localhost:8000'}},
  preview: {proxy: {'/api': process.env.VITE_PROXY_TARGET || 'http://localhost:8000'}},
});
