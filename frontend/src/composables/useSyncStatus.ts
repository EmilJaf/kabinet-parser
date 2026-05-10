import { ref, onUnmounted } from 'vue'
import { api } from '@/api/client'
import type { SyncStatusOut } from '@/api/types'

/**
 * Lightweight wrapper around /v1/sync/status with built-in polling.
 *
 * Call `start()` after the user has connected UNEC creds; the loader
 * banner uses `status` to render, and the composable auto-stops the
 * polling timer once `all_synced` flips to true (or the component
 * tearing it down).
 */
export function useSyncStatus(pollMs = 4000) {
  const status = ref<SyncStatusOut | null>(null)
  const loading = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh() {
    if (loading.value) return
    loading.value = true
    try {
      status.value = await api<SyncStatusOut>('/v1/sync/status')
      if (status.value.all_synced) stop()
    } catch {
      /* swallow; will retry on next tick */
    } finally {
      loading.value = false
    }
  }

  function start() {
    void refresh()
    if (timer === null) {
      timer = setInterval(() => void refresh(), pollMs)
    }
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  onUnmounted(stop)

  return { status, refresh, start, stop }
}
