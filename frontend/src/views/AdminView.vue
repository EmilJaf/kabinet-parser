<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { AdminLogsOut, AdminStatsOut, AdminUserOut } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/Skeleton.vue'
import { relativeTime } from '@/lib/time'

const { t } = useI18n()

const users = ref<AdminUserOut[]>([])
const stats = ref<AdminStatsOut | null>(null)
const loading = ref(true)
const busy = ref<Record<string, string>>({})  // user_id -> last action ('schedule'/'grades'/'exams'/'push')
const message = ref<{ kind: 'ok' | 'error'; text: string } | null>(null)

onMounted(async () => {
  await load()
})

async function load() {
  loading.value = true
  try {
    const [u, s] = await Promise.all([
      api<AdminUserOut[]>('/v1/admin/users'),
      api<AdminStatsOut>('/v1/admin/stats'),
    ])
    users.value = u
    stats.value = s
  } finally {
    loading.value = false
  }
}

async function triggerSync(userId: string, kind: 'schedule' | 'grades' | 'exams') {
  busy.value = { ...busy.value, [userId]: kind }
  message.value = null
  try {
    await api(`/v1/admin/users/${userId}/sync/${kind}`, { method: 'POST' })
    message.value = { kind: 'ok', text: t('admin.syncQueued', { kind }) }
  } catch (e: unknown) {
    message.value = { kind: 'error', text: (e as Error).message ?? t('common.genericFailed') }
  } finally {
    busy.value = { ...busy.value, [userId]: '' }
  }
}

async function testPush(userId: string) {
  busy.value = { ...busy.value, [userId]: 'push' }
  message.value = null
  try {
    const r = await api<{ delivered: number }>(
      `/v1/admin/users/${userId}/push/test`,
      { method: 'POST' },
    )
    message.value = { kind: 'ok', text: t('admin.delivered', { count: r.delivered }) }
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string }; message?: string }
    message.value = { kind: 'error', text: err.data?.detail ?? err.message ?? t('common.genericFailed') }
  } finally {
    busy.value = { ...busy.value, [userId]: '' }
  }
}

function fmtDate(s: string | null): string {
  if (!s) return '—'
  return relativeTime(new Date(s))
}

// ─── Logs ─────────────────────────────────────────────────────────────
type LogService = 'api' | 'worker'
const logService = ref<LogService>('api')
const logFilter = ref('')
const logLines = ref(500)
const logsAuto = ref(false)
const logsData = ref<AdminLogsOut | null>(null)
const logsLoading = ref(false)
let logsTimer: ReturnType<typeof setInterval> | null = null

async function fetchLogs() {
  logsLoading.value = true
  try {
    const q = logFilter.value.trim()
    logsData.value = await api<AdminLogsOut>('/v1/admin/logs', {
      query: { service: logService.value, lines: logLines.value, ...(q ? { q } : {}) },
    })
  } finally {
    logsLoading.value = false
  }
}

function classifyLogLine(line: string): string {
  if (/\bERROR\b|Traceback|Exception/i.test(line)) return 'text-mark-negative'
  if (/\bWARN(ING)?\b/i.test(line)) return 'text-mark-warning'
  return 'text-ink-soft'
}

watch(logsAuto, (on) => {
  if (logsTimer !== null) {
    clearInterval(logsTimer)
    logsTimer = null
  }
  if (on) {
    void fetchLogs()
    logsTimer = setInterval(() => void fetchLogs(), 5000)
  }
})

watch([logService, logLines], () => {
  if (logsData.value) void fetchLogs()
})

onUnmounted(() => {
  if (logsTimer !== null) clearInterval(logsTimer)
})

const statCards = computed(() => {
  if (!stats.value) return []
  return [
    { label: t('admin.totalUsers'), value: stats.value.user_count },
    { label: t('admin.admins'), value: stats.value.admin_count },
    { label: t('admin.withUnec'), value: stats.value.unec_linked_count },
    { label: t('admin.withPush'), value: stats.value.push_enabled_count },
  ]
})
</script>

<template>
  <div>
    <PageHeader :eyebrow="t('admin.eyebrow')" :title="t('admin.title')">
      <template #below>
        <p class="mt-4 max-w-xl text-ink-soft">
          {{ t('admin.intro') }}
        </p>
      </template>
    </PageHeader>

    <div class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16">
      <!-- Stats -->
      <section class="hairline-t pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">{{ t('admin.stats') }}</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <div v-if="loading" class="grid grid-cols-2 sm:grid-cols-4 gap-x-8 gap-y-5">
          <div v-for="i in 4" :key="i">
            <Skeleton width="60%" height="0.7rem" />
            <Skeleton width="40%" height="1.5rem" class="mt-2.5" />
          </div>
        </div>
        <div v-else class="grid grid-cols-2 sm:grid-cols-4 gap-x-8 gap-y-5">
          <div v-for="card in statCards" :key="card.label">
            <div class="text-micro text-muted font-mono uppercase tracking-wider">
              {{ card.label }}
            </div>
            <div class="text-[1.5rem] font-medium tabular-nums mt-1">
              {{ card.value }}
            </div>
          </div>
        </div>
      </section>

      <!-- Toast -->
      <div
        v-if="message"
        :class="message.kind === 'ok' ? 'text-mark-positive' : 'text-mark-negative'"
        class="mt-6 text-[0.9rem]"
      >
        {{ message.text }}
      </div>

      <!-- User list -->
      <section class="hairline-t mt-12 pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">{{ t('admin.users') }}</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <div v-if="loading" class="space-y-4">
          <Skeleton v-for="i in 3" :key="i" width="100%" height="4rem" />
        </div>

        <ul v-else-if="users.length" class="hairline-t">
          <li
            v-for="u in users"
            :key="u.id"
            class="hairline-b py-5 flex flex-col sm:flex-row sm:items-start gap-4"
          >
            <!-- Identity -->
            <div class="flex-1 min-w-0">
              <div class="flex items-baseline gap-3 flex-wrap">
                <span class="text-[1rem] text-ink truncate">{{ u.email }}</span>
                <span
                  v-if="u.is_admin"
                  class="text-micro font-mono uppercase text-mark-positive"
                  >admin</span
                >
                <span
                  v-if="u.push_subscription_count > 0"
                  class="text-micro font-mono uppercase text-muted"
                  >push:{{ u.push_subscription_count }}</span
                >
              </div>
              <div class="mt-1.5 text-micro text-muted font-mono">
                <span v-if="u.unec_username">UNEC: {{ u.unec_username }}</span>
                <span v-else>UNEC: —</span>
                <span class="mx-2">·</span>
                <span>{{ t('admin.registered', { date: fmtDate(u.created_at) }) }}</span>
              </div>
              <div class="mt-1 text-micro text-muted">
                {{ t('admin.scheduleColon', { date: fmtDate(u.schedule_last_synced_at) }) }} ·
                {{ t('admin.gradesColon', { date: fmtDate(u.grades_last_synced_at) }) }} ·
                {{ t('admin.examsColon', { date: fmtDate(u.exams_last_synced_at) }) }}
              </div>
            </div>

            <!-- Actions -->
            <div class="flex flex-wrap gap-2 shrink-0">
              <button
                v-for="kind in (['schedule', 'grades', 'exams'] as const)"
                :key="kind"
                :disabled="busy[u.id] === kind || !u.unec_username"
                class="text-micro font-mono uppercase tracking-wider px-3 py-1.5 hairline hover:bg-bg-deep cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                @click="triggerSync(u.id, kind)"
              >
                {{ busy[u.id] === kind ? '…' : `sync ${kind}` }}
              </button>
              <button
                :disabled="busy[u.id] === 'push' || u.push_subscription_count === 0"
                class="text-micro font-mono uppercase tracking-wider px-3 py-1.5 hairline hover:bg-bg-deep cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                @click="testPush(u.id)"
              >
                {{ busy[u.id] === 'push' ? '…' : 'test push' }}
              </button>
            </div>
          </li>
        </ul>

        <div v-else class="text-muted hairline-t pt-12">
          {{ t('admin.noUsers') }}
        </div>
      </section>

      <!-- Logs -->
      <section class="hairline-t mt-12 pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">{{ t('admin.logs') }}</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <!-- Controls -->
        <div class="flex flex-wrap items-center gap-3 mb-4">
          <div class="inline-flex hairline rounded-sm overflow-hidden">
            <button
              v-for="svc in (['api', 'worker'] as const)"
              :key="svc"
              type="button"
              class="px-3 py-1.5 text-[0.85rem] cursor-pointer transition-colors"
              :class="
                logService === svc
                  ? 'bg-ink text-bg'
                  : 'bg-bg text-ink-soft hover:bg-bg-deep'
              "
              @click="logService = svc"
            >
              {{ svc }}
            </button>
          </div>

          <input
            v-model="logFilter"
            type="text"
            placeholder="grep…"
            class="min-w-0 flex-1 max-w-xs bg-transparent border-0 border-b border-border px-0 py-1 text-[0.9rem] font-mono focus:outline-none focus:border-ink"
            @keydown.enter="fetchLogs"
          />

          <select
            v-model.number="logLines"
            class="bg-bg hairline text-[0.85rem] font-mono px-2 py-1 cursor-pointer"
          >
            <option :value="100">100</option>
            <option :value="500">500</option>
            <option :value="2000">2000</option>
            <option :value="5000">5000</option>
          </select>

          <button
            type="button"
            class="text-micro font-mono uppercase tracking-wider px-3 py-1.5 hairline hover:bg-bg-deep cursor-pointer"
            :disabled="logsLoading"
            @click="fetchLogs"
          >
            {{ logsLoading ? '…' : t('admin.logRefresh') }}
          </button>

          <label class="flex items-center gap-2 text-micro text-muted cursor-pointer">
            <input v-model="logsAuto" type="checkbox" class="cursor-pointer" />
            {{ t('admin.logAuto') }}
          </label>
        </div>

        <!-- Output -->
        <div
          v-if="logsData"
          class="bg-bg-soft hairline rounded-sm overflow-auto max-h-[60vh] text-[0.78rem] leading-relaxed font-mono"
        >
          <div v-if="!logsData.available" class="p-4 text-muted">
            {{ t('admin.logEmpty', { service: logService }) }}
          </div>
          <div v-else-if="logsData.lines.length === 0" class="p-4 text-muted">
            {{ t('admin.logEmptyFiltered') }}
          </div>
          <pre v-else class="p-4 whitespace-pre-wrap break-words"><code><span
            v-for="(line, i) in logsData.lines"
            :key="i"
            :class="classifyLogLine(line)"
            class="block"
          >{{ line }}</span></code></pre>
        </div>
        <div v-else-if="!logsLoading" class="text-muted text-[0.9rem]">
          {{ t('admin.logHint') }}
        </div>

        <p v-if="logsData?.available" class="text-micro text-muted mt-2 font-mono">
          {{ t('admin.logSummary', { lines: logsData.lines.length, kb: Math.round(logsData.file_size_bytes / 1024) }) }}
        </p>
      </section>
    </div>
  </div>
</template>
