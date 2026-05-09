import { ref, computed, onMounted } from 'vue'
import { api } from '@/api/client'

/**
 * Web Push subscription manager. Talks to /v1/push/* on the backend.
 *
 *   const { state, enable, disable } = usePush()
 *   await enable()  // requests permission, subscribes, posts to backend
 */

type PushState = 'unsupported' | 'denied' | 'idle' | 'enabled'

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const b64 = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(b64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

export function usePush() {
  const state = ref<PushState>('idle')
  const busy = ref(false)
  const error = ref<string | null>(null)

  const supported = computed(
    () =>
      typeof window !== 'undefined' &&
      'serviceWorker' in navigator &&
      'PushManager' in window &&
      'Notification' in window,
  )

  async function refreshState() {
    if (!supported.value) {
      state.value = 'unsupported'
      return
    }
    if (Notification.permission === 'denied') {
      state.value = 'denied'
      return
    }
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    state.value = sub ? 'enabled' : 'idle'
  }

  async function enable() {
    if (busy.value) return
    busy.value = true
    error.value = null
    try {
      if (!supported.value) throw new Error('Браузер не поддерживает уведомления')

      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        state.value = 'denied'
        throw new Error('Разрешение не выдано')
      }

      const reg = await navigator.serviceWorker.ready

      // Reuse an existing subscription if there is one, else create.
      let sub = await reg.pushManager.getSubscription()
      if (!sub) {
        const { public_key } = await api<{ public_key: string }>('/v1/push/vapid-key')
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(public_key),
        })
      }

      const json = sub.toJSON() as { endpoint?: string; keys?: { p256dh?: string; auth?: string } }
      if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
        throw new Error('Не удалось получить ключи подписки')
      }

      await api('/v1/push/subscribe', {
        method: 'POST',
        body: {
          endpoint: json.endpoint,
          p256dh: json.keys.p256dh,
          auth: json.keys.auth,
        },
      })
      state.value = 'enabled'
    } catch (e: unknown) {
      error.value = (e as Error).message ?? 'Ошибка'
    } finally {
      busy.value = false
    }
  }

  async function disable() {
    if (busy.value) return
    busy.value = true
    error.value = null
    try {
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.getSubscription()
      if (sub) {
        try {
          await api('/v1/push/subscribe', {
            method: 'DELETE',
            body: { endpoint: sub.endpoint },
          })
        } catch {
          /* server cleanup; ignore network errors */
        }
        await sub.unsubscribe()
      }
      state.value = 'idle'
    } catch (e: unknown) {
      error.value = (e as Error).message ?? 'Ошибка'
    } finally {
      busy.value = false
    }
  }

  onMounted(() => {
    void refreshState()
  })

  return { state, supported, busy, error, enable, disable, refreshState }
}
