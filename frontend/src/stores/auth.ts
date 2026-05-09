import { computed } from 'vue'
import { defineStore } from 'pinia'
import { useStorage } from '@vueuse/core'
import { ofetch } from 'ofetch'
import type { UserOut } from '@/api/types'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Tokens live in HttpOnly cookies set by the backend; the SPA never sees
// them. We only persist a copy of the user profile so we can render the
// shell instantly on reload — the next /auth/me call refreshes it (and a
// 401 will clear it).
export const useAuthStore = defineStore('auth', () => {
  const user = useStorage<UserOut | null>('kabinet:user', null, undefined, {
    serializer: {
      read: (v) => (v ? (JSON.parse(v) as UserOut) : null),
      write: (v) => (v ? JSON.stringify(v) : ''),
    },
  })

  const isAuthenticated = computed(() => Boolean(user.value))

  async function register(email: string, password: string) {
    await ofetch(`${baseURL}/v1/auth/register`, {
      method: 'POST',
      body: { email, password },
      credentials: 'include',
    })
    await login(email, password)
  }

  async function login(email: string, password: string) {
    const me = await ofetch<UserOut>(`${baseURL}/v1/auth/login`, {
      method: 'POST',
      body: { email, password },
      credentials: 'include',
    })
    user.value = me
    return me
  }

  async function fetchMe() {
    const me = await ofetch<UserOut>(`${baseURL}/v1/auth/me`, {
      credentials: 'include',
    })
    user.value = me
    return me
  }

  async function logout() {
    try {
      await ofetch(`${baseURL}/v1/auth/logout`, {
        method: 'POST',
        credentials: 'include',
      })
    } catch {
      /* ignore */
    }
    clear()
  }

  function clear() {
    user.value = null
  }

  return {
    user,
    isAuthenticated,
    register,
    login,
    logout,
    fetchMe,
    clear,
  }
})
