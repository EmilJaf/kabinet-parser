import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
    VitePWA({
      // injectManifest = we own the SW source (src/sw.ts) and the plugin
      // injects the precache manifest into it. We need this so we can add
      // our own push / notificationclick handlers — generateSW doesn't
      // allow custom code.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'autoUpdate',
      // Off in dev — SW caching makes hot reload confusing.
      devOptions: { enabled: false },
      includeAssets: ['favicon.svg', 'apple-touch-icon.png', 'icon.svg'],
      injectManifest: {
        // Match what generateSW used to do.
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
      },
      manifest: {
        name: 'Kabinet — UNEC',
        short_name: 'Kabinet',
        description: 'Личный кабинет UNEC: расписание, оценки, экзамены',
        lang: 'ru',
        theme_color: '#000000',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        scope: '/',
        icons: [
          { src: '/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/pwa-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/pwa-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 5173 is already taken by the user's ai_shop_assistant on this machine.
    port: 5174,
    strictPort: true,
  },
})
