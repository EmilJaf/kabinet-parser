import { onMounted, ref } from 'vue'
import { useRegisterSW } from 'virtual:pwa-register/vue'

/**
 * Wraps the bits of the PWA lifecycle the UI needs:
 *  - install prompt (Android Chrome / desktop): captured via `beforeinstallprompt`
 *  - update toast: emitted when a new SW takes over
 *  - iOS detection: there's no install prompt on iOS, but we can guide the user
 *    to "Share → Add to Home Screen"
 */

interface BeforeInstallPromptEvent extends Event {
  readonly platforms: readonly string[]
  prompt(): Promise<void>
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

const DISMISS_KEY = 'kabinet:pwa-install-dismissed-at'
const DISMISS_TTL_MS = 1000 * 60 * 60 * 24 * 14 // 14 days

function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    // iOS-specific
    (navigator as unknown as { standalone?: boolean }).standalone === true
  )
}

function isIos(): boolean {
  const ua = navigator.userAgent
  return /iphone|ipad|ipod/i.test(ua) && !/crios|fxios/i.test(ua)
}

function recentlyDismissed(): boolean {
  const raw = localStorage.getItem(DISMISS_KEY)
  if (!raw) return false
  const ts = Number(raw)
  return Number.isFinite(ts) && Date.now() - ts < DISMISS_TTL_MS
}

export function usePwa() {
  const installEvent = ref<BeforeInstallPromptEvent | null>(null)
  const canInstall = ref(false)
  const showIosHint = ref(false)
  const installed = ref(false)

  const { needRefresh, updateServiceWorker } = useRegisterSW({
    immediate: true,
    onRegisteredSW(swUrl, registration) {
      // Periodic background check — picks up new deploys without a reload.
      setInterval(() => {
        navigator.serviceWorker?.getRegistration(swUrl).then((reg) => reg?.update())
      }, 60 * 60 * 1000)

      // iOS PWA: every time the app becomes visible (user reopens icon,
      // unlocks phone, switches back from another app) check for a new
      // SW immediately. Without this iOS won't poll until ~24h.
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          void registration?.update()
        }
      })

      // When a fresh SW takes control, reload so the user sees new assets
      // right away. But ONLY when this is a real update — if there was no
      // controller before (first SW install for this page), reloading is
      // pointless and can blank the screen mid-load. Capture the initial
      // controller state before attaching the listener.
      const hadController = !!navigator.serviceWorker?.controller
      let reloading = false
      navigator.serviceWorker?.addEventListener('controllerchange', () => {
        if (reloading || !hadController) return
        reloading = true
        window.location.reload()
      })
    },
  })

  onMounted(() => {
    if (isStandalone()) {
      installed.value = true
      return
    }

    if (recentlyDismissed()) return

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault()
      installEvent.value = e as BeforeInstallPromptEvent
      canInstall.value = true
    })

    window.addEventListener('appinstalled', () => {
      installEvent.value = null
      canInstall.value = false
      installed.value = true
    })

    // iOS doesn't fire beforeinstallprompt; show a manual hint on Safari.
    if (isIos()) showIosHint.value = true
  })

  async function promptInstall() {
    if (!installEvent.value) return
    await installEvent.value.prompt()
    const { outcome } = await installEvent.value.userChoice
    installEvent.value = null
    canInstall.value = false
    if (outcome === 'dismissed') localStorage.setItem(DISMISS_KEY, String(Date.now()))
  }

  function dismissInstall() {
    canInstall.value = false
    showIosHint.value = false
    localStorage.setItem(DISMISS_KEY, String(Date.now()))
  }

  function applyUpdate() {
    void updateServiceWorker(true)
  }

  return {
    canInstall,
    showIosHint,
    installed,
    promptInstall,
    dismissInstall,
    needRefresh,
    applyUpdate,
  }
}
