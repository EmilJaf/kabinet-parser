import { ofetch, type FetchOptions } from 'ofetch'
import { useAuthStore } from '@/stores/auth'

// `??` not `||`: VITE_API_BASE_URL='' is the explicit "same-origin" mode
// used by the prod build (SPA + API share a host behind Caddy). With `||`
// the empty string would falsely fall through to the dev default.
const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Single in-flight refresh promise so concurrent 401s don't all fire /auth/refresh.
let refreshInFlight: Promise<boolean> | null = null

async function refreshSession(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight

  refreshInFlight = (async () => {
    try {
      await ofetch(`${baseURL}/v1/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      })
      return true
    } catch {
      useAuthStore().clear()
      return false
    } finally {
      refreshInFlight = null
    }
  })()

  return refreshInFlight
}

function statusOf(err: unknown): number | undefined {
  const e = err as { status?: number; response?: { status?: number } }
  return e?.status ?? e?.response?.status
}

/**
 * Wrap an ofetch call with auth-refresh-on-401 retry.
 *
 * Why a function instead of ofetch's `onResponseError` hook: the hook
 * fires AFTER ofetch decides to throw. Mutating the response inside the
 * hook used to leak the original 401 to the caller anyway (browsers
 * treat Response.ok as a non-configurable getter), so views would render
 * empty state on first load and the user had to reload manually. A
 * try/catch wrapper gives us full control — try, catch 401, refresh,
 * retry, return the second response cleanly.
 */
export async function api<T = unknown>(
  path: string,
  options: FetchOptions<'json'> = {},
): Promise<T> {
  const opts: FetchOptions<'json'> = { baseURL, credentials: 'include', ...options }
  try {
    return await ofetch<T>(path, opts)
  } catch (err) {
    if (statusOf(err) !== 401) throw err
    if (!(await refreshSession())) throw err
    return await ofetch<T>(path, opts)
  }
}

/**
 * Fetch a binary asset through the auth/refresh pipeline. Returns the body
 * as a Blob so callers can hand it to URL.createObjectURL.
 */
export async function apiBlob(
  path: string,
  query?: Record<string, string | number | boolean>,
): Promise<Blob> {
  const opts = {
    baseURL,
    query,
    credentials: 'include' as const,
    responseType: 'blob' as const,
  }
  try {
    return (await ofetch(path, opts)) as Blob
  } catch (err) {
    if (statusOf(err) !== 401) throw err
    if (!(await refreshSession())) throw err
    return (await ofetch(path, opts)) as Blob
  }
}
