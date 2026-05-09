<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute, RouterLink } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

type Mode = 'login' | 'register'

const mode = ref<Mode>('login')
const email = ref('')
const password = ref('')
const passwordConfirm = ref('')
const submitting = ref(false)
const error = ref<string | null>(null)

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const title = computed(() =>
  mode.value === 'login' ? 'Войдите в кабинет' : 'Создайте аккаунт',
)

const submitLabel = computed(() =>
  mode.value === 'login' ? 'Войти' : 'Создать и войти',
)

const canSubmit = computed(() => {
  if (!email.value || !password.value) return false
  if (mode.value === 'register' && password.value !== passwordConfirm.value) return false
  return !submitting.value
})

function switchMode(next: Mode) {
  if (mode.value === next) return
  mode.value = next
  error.value = null
}

async function submit() {
  if (!canSubmit.value) return
  submitting.value = true
  error.value = null
  try {
    if (mode.value === 'register') {
      await auth.register(email.value, password.value)
    } else {
      await auth.login(email.value, password.value)
    }
    const next = (route.query.next as string | undefined) || '/schedule'
    await router.push(next)
  } catch (e: unknown) {
    error.value = humanizeError(e)
  } finally {
    submitting.value = false
  }
}

function humanizeError(e: unknown): string {
  const err = e as { data?: { detail?: string }; status?: number; message?: string }
  if (err?.data?.detail) return err.data.detail
  if (err?.status === 401) return 'Неверный email или пароль.'
  if (err?.status === 409) return 'Этот email уже зарегистрирован.'
  return err?.message ?? 'Что-то пошло не так. Попробуйте ещё раз.'
}
</script>

<template>
  <div class="min-h-screen bg-bg text-ink flex flex-col">
    <!-- Top strip with brand. Same safe-area treatment as AppLayout so the
         brand text sits at the same height in standalone PWA mode. -->
    <header
      class="px-6 sm:px-10"
      style="padding-top: max(env(safe-area-inset-top), 0.75rem)"
    >
      <span class="text-[1.35rem] font-semibold tracking-tight">Kabinet</span>
    </header>

    <!-- Centered column -->
    <div class="flex-1 grid place-items-center px-6 py-12 sm:py-16">
      <div class="w-full max-w-[460px]">
        <!-- Eyebrow + title -->
        <div class="eyebrow mb-5">
          {{ mode === 'login' ? 'Вход' : 'Регистрация' }}
        </div>

        <h1 class="text-display-lg font-medium text-ink leading-[1.15] tracking-tight mb-4">
          {{ title }}
        </h1>

        <p class="text-ink-soft leading-relaxed mb-12 max-w-md">
          Подключитесь к
          <span class="font-mono text-[0.85em] bg-bg-deep px-1.5 py-0.5 rounded-sm">
            kabinet.unec.edu.az
          </span>
          и получите расписание и оценки в нормальном виде.
        </p>

        <form @submit.prevent="submit" class="space-y-5">
          <!-- Email -->
          <div>
            <label class="block text-micro text-muted mb-2 font-mono uppercase tracking-wider">
              Email
            </label>
            <input
              v-model="email"
              type="email"
              autocomplete="email"
              required
              class="w-full bg-transparent border-0 border-b border-border px-0 py-2 text-ink placeholder-muted-soft focus:outline-none focus:border-ink transition-colors"
              placeholder="you@example.com"
            />
          </div>

          <!-- Password -->
          <div>
            <label class="block text-micro text-muted mb-2 font-mono uppercase tracking-wider">
              Пароль
            </label>
            <input
              v-model="password"
              type="password"
              :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
              required
              minlength="8"
              class="w-full bg-transparent border-0 border-b border-border px-0 py-2 text-ink placeholder-muted-soft focus:outline-none focus:border-ink transition-colors"
              :placeholder="mode === 'register' ? 'минимум 8 символов' : ''"
            />
          </div>

          <!-- Confirm (register only) -->
          <div v-if="mode === 'register'">
            <label class="block text-micro text-muted mb-2 font-mono uppercase tracking-wider">
              Пароль ещё раз
            </label>
            <input
              v-model="passwordConfirm"
              type="password"
              autocomplete="new-password"
              required
              class="w-full bg-transparent border-0 border-b border-border px-0 py-2 text-ink placeholder-muted-soft focus:outline-none focus:border-ink transition-colors"
            />
            <p
              v-if="passwordConfirm && password !== passwordConfirm"
              class="text-micro mt-2 text-mark-negative"
            >
              Пароли не совпадают.
            </p>
          </div>

          <!-- Error -->
          <div v-if="error" class="text-micro text-mark-negative pt-1">
            {{ error }}
          </div>

          <!-- Actions -->
          <div class="pt-6 flex items-baseline gap-6">
            <button
              type="submit"
              :disabled="!canSubmit"
              class="group relative bg-ink text-bg px-7 py-3 text-[0.95rem] tracking-tight transition-all hover:bg-ink-soft disabled:bg-muted-soft disabled:cursor-not-allowed cursor-pointer"
            >
              <span>{{ submitLabel }}</span>
              <span
                class="absolute inset-y-0 right-3 flex items-center transition-transform group-hover:translate-x-1"
              >
                →
              </span>
              <span class="invisible pl-7">→</span>
            </button>

            <button
              v-if="mode === 'login'"
              type="button"
              class="text-ink-soft hover:text-ink transition-colors text-[0.9rem] cursor-pointer"
              @click="switchMode('register')"
            >
              Нет аккаунта?
              <span class="underline underline-offset-4 decoration-border">
                Создайте
              </span>
            </button>
            <button
              v-else
              type="button"
              class="text-ink-soft hover:text-ink transition-colors text-[0.9rem] cursor-pointer"
              @click="switchMode('login')"
            >
              Уже есть аккаунт?
              <span class="underline underline-offset-4 decoration-border">Войдите</span>
            </button>
          </div>
        </form>

        <!-- Footnote -->
        <div class="hairline-t mt-16 pt-6 flex items-baseline justify-between text-micro text-muted">
          <span>Пароль UNEC хранится зашифрованным.</span>
          <span class="font-mono">v0.1</span>
        </div>
      </div>
    </div>
  </div>
</template>
