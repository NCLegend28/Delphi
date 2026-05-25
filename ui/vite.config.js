import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Where the Delphi backend is running locally. Set VITE_DELPHI_PROXY_TARGET
  // in .env.local to override (e.g. when nginx already owns :8080 and you
  // moved Delphi to :8090).
  const target = env.VITE_DELPHI_PROXY_TARGET || 'http://localhost:8090'

  return {
    plugins: [react(), tailwindcss()],
    // Force a single React instance — without this, Vite pre-bundles a second
    // copy alongside zustand (and other React consumers) and components mount
    // with mismatched dispatchers, triggering "Invalid hook call" warnings.
    resolve: {
      dedupe: ['react', 'react-dom'],
    },
    optimizeDeps: {
      include: ['react', 'react-dom', 'react-dom/client', 'zustand'],
    },
    server: {
      proxy: {
        '/v1': target,
        '/healthz': target,
        '/readyz': target,
      },
    },
  }
})
