import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),

    // Progressive Web App shell. Lets phones install the site from the browser
    // ("Add to Home Screen") and open it full-screen without browser chrome.
    //
    // Caching policy — the service worker precaches ONLY the built shell
    // (index.html, hashed JS/CSS, icons). It never caches /api/*: job polling,
    // audit rows, and dashboard summaries must always come from the server, or
    // a finished execute could be shown as still running. No runtimeCaching
    // rules are defined, so every non-precached request goes to the network
    // exactly as it does today in a normal browser tab.
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        name: 'Quill & Arrow Clio Data Management',
        short_name: 'QA Clio',
        description: 'Bulk Clio updates, audit log, and billing / firm dashboards.',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'any',
        background_color: '#f0f4f8',
        theme_color: '#0f172a',
        icons: [
          { src: '/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/pwa-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        // SPA fallback for client routes (/billing, /audit, ...) when offline
        // or when the shell is already cached. Never for API or FastAPI docs.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/docs/, /^\/openapi\.json$/, /^\/redoc/],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
