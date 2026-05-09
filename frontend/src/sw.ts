/// <reference lib="webworker" />
/* eslint-disable no-restricted-globals */

import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { CacheFirst, NetworkFirst, StaleWhileRevalidate } from 'workbox-strategies'
import { CacheableResponsePlugin } from 'workbox-cacheable-response'
import { ExpirationPlugin } from 'workbox-expiration'

declare const self: ServiceWorkerGlobalScope

// Inject the precache manifest produced by vite-plugin-pwa.
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// SPA navigation fallback (HTML5 history mode), excluding API + docs.
const navHandler = new NetworkFirst({ cacheName: 'pages' })
registerRoute(
  new NavigationRoute(navHandler, {
    denylist: [/^\/v1\//, /^\/docs/, /^\/openapi\.json/],
  }),
)

// Google Fonts — same recipe as the previous generateSW config.
registerRoute(
  ({ url }) => url.origin === 'https://fonts.googleapis.com',
  new StaleWhileRevalidate({ cacheName: 'google-fonts-stylesheets' }),
)
registerRoute(
  ({ url }) => url.origin === 'https://fonts.gstatic.com',
  new CacheFirst({
    cacheName: 'google-fonts-webfonts',
    plugins: [
      new CacheableResponsePlugin({ statuses: [0, 200] }),
      new ExpirationPlugin({ maxEntries: 30, maxAgeSeconds: 60 * 60 * 24 * 365 }),
    ],
  }),
)

// Read-only API GETs — fresh-first, fall back to cache when offline.
registerRoute(
  ({ url, request }) =>
    request.method === 'GET' &&
    /\/v1\/(schedule|grades|exams|unec\/credentials)/.test(url.pathname),
  new NetworkFirst({
    cacheName: 'api-reads',
    networkTimeoutSeconds: 4,
    plugins: [
      new CacheableResponsePlugin({ statuses: [200] }),
      new ExpirationPlugin({ maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 }),
    ],
  }),
)

// ─── Web Push handlers ─────────────────────────────────────────────────────

interface PushPayload {
  title: string
  body: string
  url?: string
  tag?: string
}

self.addEventListener('push', (event: PushEvent) => {
  if (!event.data) return
  let data: PushPayload
  try {
    data = event.data.json() as PushPayload
  } catch {
    data = { title: 'Kabinet', body: event.data.text() }
  }

  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      tag: data.tag,
      icon: '/pwa-192.png',
      badge: '/pwa-192.png',
      data: { url: data.url ?? '/dashboard' },
    }),
  )
})

self.addEventListener('notificationclick', (event: NotificationEvent) => {
  event.notification.close()
  const targetUrl = (event.notification.data as { url?: string } | null)?.url ?? '/dashboard'

  event.waitUntil(
    (async () => {
      // If a tab is already open on this origin, focus it; else open a new one.
      const allClients = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true,
      })
      for (const c of allClients) {
        const url = new URL(c.url)
        if (url.origin === self.location.origin) {
          await c.focus()
          if ('navigate' in c) await c.navigate(targetUrl)
          return
        }
      }
      await self.clients.openWindow(targetUrl)
    })(),
  )
})

// ─── Update lifecycle ──────────────────────────────────────────────────────
//
// iOS Safari is lazy about checking for SW updates — by spec it does so at
// most once per 24h. The combo below makes new versions take effect ASAP
// without forcing the user to delete & re-add the PWA from the home screen:
//
//   install  → skipWaiting()      Don't sit in 'waiting' — activate now.
//   activate → clients.claim()    Take control of already-open tabs.
//   message  → skipWaiting()      Honour the explicit nudge from the
//                                 vite-plugin-pwa register script.
self.addEventListener('install', () => {
  void self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting()
})
