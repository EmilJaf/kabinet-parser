import { ref, onMounted, onUnmounted } from 'vue'

/**
 * Reactive `now` ticking every minute. Use anywhere a UI needs to recompute
 * relative to the current time (countdowns, "started X minutes ago", etc.)
 * without writing your own setInterval per component.
 *
 *   const now = useNow()
 *   // now.value.getTime() updates every 60s
 */
export function useNow(intervalMs = 60_000) {
  const now = ref(new Date())
  let timer: ReturnType<typeof setInterval> | null = null

  onMounted(() => {
    timer = setInterval(() => {
      now.value = new Date()
    }, intervalMs)
  })

  onUnmounted(() => {
    if (timer !== null) clearInterval(timer)
  })

  return now
}
