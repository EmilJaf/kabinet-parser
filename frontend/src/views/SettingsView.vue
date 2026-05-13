<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { UnecCredentialsStatus } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/Skeleton.vue'
import { relativeTime } from '@/lib/time'
import { usePush } from '@/composables/usePush'
import { useTheme, type ThemeMode } from '@/composables/useTheme'
import { useAuthStore } from '@/stores/auth'
import { SUPPORTED_LOCALES, type AppLocale } from '@/i18n'

const { t, locale } = useI18n()
const push = usePush()
const theme = useTheme()
const auth = useAuthStore()

const themeOptions = computed<{ value: ThemeMode; label: string; hint: string }[]>(() => [
  { value: 'light', label: t('settings.themeLight'), hint: '☀' },
  { value: 'dark', label: t('settings.themeDark'), hint: '☾' },
  { value: 'system', label: t('settings.themeSystem'), hint: '◐' },
])

// Native names of supported locales — kept here instead of in the catalog
// so each language is shown in *its own* script, not the active UI language.
const LANG_LABELS: Record<AppLocale, string> = {
  az: 'Azərbaycan',
  ru: 'Русский',
  en: 'English',
}
const languageOptions = computed(() =>
  (SUPPORTED_LOCALES as AppLocale[]).map((l) => ({ value: l, label: LANG_LABELS[l] })),
)
const languageSaving = ref(false)

async function setLanguage(lang: AppLocale) {
  if (lang === locale.value) return
  languageSaving.value = true
  try {
    await auth.setLanguage(lang)
  } finally {
    languageSaving.value = false
  }
}

const status = ref<UnecCredentialsStatus | null>(null)
const loading = ref(true)
const submitting = ref(false)
const message = ref<{ kind: 'ok' | 'error'; text: string } | null>(null)

const username = ref('')
const password = ref('')

const lastLoginRel = computed(() => {
  if (!status.value?.last_login_at) return null
  return relativeTime(new Date(status.value.last_login_at))
})

const intlTag = computed(() => ({ az: 'az-AZ', ru: 'ru-RU', en: 'en-GB' }[locale.value as AppLocale] ?? 'az-AZ'))

onMounted(async () => {
  await load()
})

async function load() {
  loading.value = true
  try {
    status.value = await api<UnecCredentialsStatus>('/v1/unec/credentials')
    if (status.value.configured && status.value.username) {
      username.value = status.value.username
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  submitting.value = true
  message.value = null
  try {
    status.value = await api<UnecCredentialsStatus>('/v1/unec/credentials', {
      method: 'PUT',
      body: { username: username.value, password: password.value },
    })
    password.value = ''
    message.value = { kind: 'ok', text: t('settings.saved') }
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string }; status?: number }
    message.value = {
      kind: 'error',
      text: err?.data?.detail ?? t('settings.saveFailed'),
    }
  } finally {
    submitting.value = false
  }
}

async function unlink() {
  if (!confirm(t('settings.unlinkConfirm'))) return
  await api('/v1/unec/credentials', { method: 'DELETE' })
  status.value = { configured: false, username: null, last_login_at: null, updated_at: null }
  username.value = ''
  password.value = ''
  message.value = { kind: 'ok', text: t('settings.unlinked') }
}

</script>

<template>
  <div>
    <PageHeader :eyebrow="t('settings.unecEyebrow')" :title="t('settings.unecTitle')">
      <template #below>
        <p class="mt-4 max-w-xl text-ink-soft">
          {{ t('settings.unecIntro1') }}
          {{ t('settings.unecIntro2') }}
        </p>
      </template>
    </PageHeader>

    <div class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16 max-w-3xl">
      <!-- Status block -->
      <section class="hairline-t pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">{{ t('settings.status') }}</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 gap-x-12 gap-y-5">
          <div>
            <Skeleton width="40%" height="0.7rem" />
            <Skeleton width="60%" height="1rem" class="mt-2.5" />
          </div>
          <div>
            <Skeleton width="40%" height="0.7rem" />
            <Skeleton width="70%" height="1rem" class="mt-2.5" />
          </div>
        </div>

        <div v-else-if="status?.configured" class="grid grid-cols-1 sm:grid-cols-2 gap-x-12 gap-y-5">
          <div>
            <div class="text-micro text-muted font-mono uppercase tracking-wider mb-1">
              {{ t('settings.stateLabel') }}
            </div>
            <div class="flex items-center gap-2.5">
              <span class="h-1.5 w-1.5 rounded-full bg-mark-positive" />
              <span>{{ t('settings.connected') }}</span>
            </div>
          </div>
          <div>
            <div class="text-micro text-muted font-mono uppercase tracking-wider mb-1">
              {{ t('settings.loginLabel') }}
            </div>
            <div class="font-mono">{{ status.username }}</div>
          </div>
          <div v-if="lastLoginRel" class="col-span-2">
            <div class="text-micro text-muted font-mono uppercase tracking-wider mb-1">
              {{ t('settings.lastLoginLabel') }}
            </div>
            <div>
              {{ lastLoginRel }}
              <span class="text-muted text-[0.85rem] ml-2 font-mono">
                {{ new Date(status!.last_login_at!).toLocaleString(intlTag) }}
              </span>
            </div>
          </div>
        </div>

        <div v-else class="text-ink-soft">
          {{ t('settings.notConnected') }}
        </div>
      </section>

      <!-- Form -->
      <section class="hairline-t mt-12 pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">
            {{ status?.configured ? t('settings.updatePassword') : t('settings.connect') }}
          </span>
          <span class="hairline flex-1 border-t" />
        </div>

        <form @submit.prevent="save" class="space-y-5 max-w-md">
          <div>
            <label class="block text-micro text-muted mb-2 font-mono uppercase tracking-wider">
              {{ t('settings.loginField') }}
            </label>
            <input
              v-model="username"
              type="text"
              autocomplete="username"
              required
              :placeholder="t('settings.loginFieldPlaceholder')"
              class="w-full bg-transparent border-0 border-b border-border px-0 py-2 text-ink placeholder-muted-soft font-mono focus:outline-none focus:border-ink transition-colors"
            />
          </div>

          <div>
            <label class="block text-micro text-muted mb-2 font-mono uppercase tracking-wider">
              {{ t('settings.passwordField') }}
            </label>
            <input
              v-model="password"
              type="password"
              autocomplete="off"
              required
              class="w-full bg-transparent border-0 border-b border-border px-0 py-2 text-ink focus:outline-none focus:border-ink transition-colors"
            />
            <p class="text-micro mt-2 text-muted">
              {{ t('settings.saveHint') }}
            </p>
          </div>

          <div
            v-if="message"
            :class="
              message.kind === 'ok' ? 'text-mark-positive' : 'text-mark-negative'
            "
            class="text-[0.9rem]"
          >
            {{ message.text }}
          </div>

          <div class="flex items-center gap-6 pt-2">
            <button
              type="submit"
              :disabled="submitting || !username || !password"
              class="group relative bg-ink text-bg px-6 py-2.5 text-[0.9rem] tracking-tight transition-all hover:bg-ink-soft disabled:bg-muted-soft disabled:cursor-not-allowed cursor-pointer"
            >
              {{ submitting ? t('common.saving') : t('common.save') }}
            </button>

            <button
              v-if="status?.configured"
              type="button"
              class="text-mark-negative hover:underline text-[0.9rem] cursor-pointer"
              @click="unlink"
            >
              {{ t('settings.unlinkButton') }}
            </button>
          </div>
        </form>
      </section>

      <!-- Appearance -->
      <section class="hairline-t mt-12 pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">{{ t('settings.appearance') }}</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <div class="max-w-md">
          <div class="text-[0.95rem] text-ink mb-1.5">{{ t('settings.theme') }}</div>
          <p class="text-micro text-muted mb-4 leading-relaxed">
            {{ t('settings.themeHint') }}
          </p>
          <div class="inline-flex hairline rounded-sm overflow-hidden">
            <button
              v-for="opt in themeOptions"
              :key="opt.value"
              type="button"
              class="px-4 py-2 text-[0.85rem] transition-colors cursor-pointer"
              :class="
                theme.mode.value === opt.value
                  ? 'bg-ink text-bg'
                  : 'bg-bg text-ink-soft hover:bg-bg-deep'
              "
              @click="theme.setMode(opt.value)"
            >
              <span class="mr-2 font-mono text-[0.95rem]">{{ opt.hint }}</span>
              {{ opt.label }}
            </button>
          </div>
        </div>

        <!-- Language -->
        <div class="max-w-md mt-8">
          <div class="text-[0.95rem] text-ink mb-1.5">{{ t('settings.language') }}</div>
          <p class="text-micro text-muted mb-4 leading-relaxed">
            {{ t('settings.languageHint') }}
          </p>
          <div class="inline-flex hairline rounded-sm overflow-hidden">
            <button
              v-for="opt in languageOptions"
              :key="opt.value"
              type="button"
              :disabled="languageSaving"
              class="px-4 py-2 text-[0.85rem] transition-colors cursor-pointer disabled:cursor-wait disabled:opacity-60"
              :class="
                locale === opt.value
                  ? 'bg-ink text-bg'
                  : 'bg-bg text-ink-soft hover:bg-bg-deep'
              "
              @click="setLanguage(opt.value)"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>
      </section>

      <!-- Push notifications -->
      <section class="hairline-t mt-12 pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">{{ t('settings.notifications') }}</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-4 items-start max-w-md">
          <div>
            <div class="text-[0.95rem] text-ink">{{ t('settings.lessonNotifications') }}</div>
            <p class="text-micro text-muted mt-1.5 leading-relaxed">
              {{ t('settings.lessonNotifDesc') }}
              {{ t('settings.iosPwaHint') }}
            </p>
            <p
              v-if="push.error.value"
              class="text-micro text-mark-negative mt-2"
            >
              {{ push.error.value }}
            </p>
            <p
              v-if="push.state.value === 'denied'"
              class="text-micro text-muted mt-2"
            >
              {{ t('settings.permDenied') }}
            </p>
            <p
              v-else-if="push.state.value === 'unsupported'"
              class="text-micro text-muted mt-2"
            >
              {{ t('settings.unsupported') }}
            </p>
          </div>

          <button
            v-if="push.state.value === 'enabled'"
            type="button"
            :disabled="push.busy.value"
            class="text-mark-negative hover:underline text-[0.9rem] cursor-pointer disabled:opacity-50"
            @click="push.disable()"
          >
            {{ push.busy.value ? '…' : t('settings.disable') }}
          </button>
          <button
            v-else
            type="button"
            :disabled="push.busy.value || push.state.value === 'unsupported' || push.state.value === 'denied'"
            class="bg-ink text-bg px-5 py-2 text-[0.9rem] tracking-tight transition-all hover:bg-ink-soft disabled:bg-muted-soft disabled:cursor-not-allowed cursor-pointer"
            @click="push.enable()"
          >
            {{ push.busy.value ? '…' : t('settings.enable') }}
          </button>
        </div>
      </section>

      <!-- Trust footer -->
      <section class="hairline-t mt-16 pt-6 text-micro text-muted leading-relaxed">
        {{ t('settings.encryptionFooter') }}
      </section>
    </div>
  </div>
</template>
