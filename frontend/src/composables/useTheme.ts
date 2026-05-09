import { ref, computed, watchEffect, onMounted, onUnmounted } from 'vue'

/**
 * Theme preference manager.
 *
 *   const { mode, effective, setMode } = useTheme()
 *
 * - `mode` is the user's stored choice: 'light' | 'dark' | 'system'
 * - `effective` resolves 'system' against the OS `prefers-color-scheme`
 * - applying the theme writes `data-theme="..."` on <html> AND updates the
 *   <meta name="theme-color"> tag so iOS status bar matches
 *
 * The default is read from localStorage at module load. An inline script
 * in index.html sets data-theme synchronously before Vue mounts so users
 * never see a light-flash before dark theme kicks in.
 */

export type ThemeMode = 'light' | 'dark' | 'system'

const STORAGE_KEY = 'kabinet:theme'

const THEME_COLOR = {
  light: '#ffffff',
  dark: '#0a0a0a',
}

function readStored(): ThemeMode {
  if (typeof localStorage === 'undefined') return 'system'
  const v = localStorage.getItem(STORAGE_KEY)
  return v === 'light' || v === 'dark' ? v : 'system'
}

function writeStored(value: ThemeMode) {
  if (typeof localStorage === 'undefined') return
  if (value === 'system') localStorage.removeItem(STORAGE_KEY)
  else localStorage.setItem(STORAGE_KEY, value)
}

// Module-level state so all consumers share one source of truth.
const mode = ref<ThemeMode>(readStored())
const systemPrefersDark = ref(
  typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches,
)

const effective = computed<'light' | 'dark'>(() =>
  mode.value === 'system' ? (systemPrefersDark.value ? 'dark' : 'light') : mode.value,
)

let mediaListenerAttached = false

function attachMediaListener() {
  if (mediaListenerAttached || typeof matchMedia === 'undefined') return
  mediaListenerAttached = true
  const mq = matchMedia('(prefers-color-scheme: dark)')
  mq.addEventListener('change', (e) => {
    systemPrefersDark.value = e.matches
  })
}

function applyToDocument(theme: 'light' | 'dark') {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.theme = theme
  // Update PWA / iOS status-bar tint to match.
  let meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (!meta) {
    meta = document.createElement('meta')
    meta.name = 'theme-color'
    document.head.appendChild(meta)
  }
  meta.content = THEME_COLOR[theme]
}

export function useTheme() {
  onMounted(() => {
    attachMediaListener()
  })
  onUnmounted(() => {
    /* media listener intentionally lives until tab close — shared state */
  })

  // Whenever effective resolves to a new value, push it into the DOM.
  watchEffect(() => {
    applyToDocument(effective.value)
  })

  function setMode(next: ThemeMode) {
    mode.value = next
    writeStored(next)
  }

  return { mode, effective, setMode }
}
