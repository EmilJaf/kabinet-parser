<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import type { UnecCredentialsStatus } from '@/api/types'
import { useSyncStatus } from '@/composables/useSyncStatus'
import { ref } from 'vue'

const sync = useSyncStatus()
const credsConfigured = ref(false)
const credsChecked = ref(false)

async function checkCreds() {
  try {
    const status = await api<UnecCredentialsStatus>('/v1/unec/credentials')
    credsConfigured.value = status.configured
  } catch {
    credsConfigured.value = false
  } finally {
    credsChecked.value = true
  }
}

onMounted(async () => {
  await checkCreds()
  if (credsConfigured.value) sync.start()
})

// If user adds creds while on a page (rare — but Settings updates a global
// store eventually) we'd want to react. For now we re-check after every
// route change via the AppLayout host.

defineExpose({ recheck: async () => { await checkCreds(); if (credsConfigured.value) sync.start() } })

const sections = computed(() => {
  const s = sync.status.value
  return [
    { label: 'Расписание', key: 'schedule' as const, state: s?.schedule.status ?? null },
    { label: 'Журнал',      key: 'grades' as const,   state: s?.grades.status ?? null },
    { label: 'Экзамены',    key: 'exams' as const,    state: s?.exams.status ?? null },
  ]
})

// Show only when creds are linked AND at least one section isn't OK.
const visible = computed(() => {
  if (!credsChecked.value) return false
  if (!credsConfigured.value) return false
  const s = sync.status.value
  if (!s) return false
  return !s.all_synced
})

function icon(state: 'ok' | 'error' | null): string {
  if (state === 'ok') return '✓'
  if (state === 'error') return '✕'
  return '⏳'
}

function colorClass(state: 'ok' | 'error' | null): string {
  if (state === 'ok') return 'text-mark-positive'
  if (state === 'error') return 'text-mark-negative'
  return 'text-muted'
}

watch(visible, (now) => {
  // Stop polling immediately when banner hides (also handled inside the
  // composable when all_synced flips; this is belt-and-braces).
  if (!now) sync.stop()
})
</script>

<template>
  <Transition name="lift">
    <div
      v-if="visible"
      class="hairline-b bg-bg-soft px-6 sm:px-8 lg:px-12 py-3 flex flex-wrap items-center gap-4"
    >
      <span class="flex items-center gap-2 text-[0.9rem] text-ink">
        <span class="inline-block h-2 w-2 rounded-full bg-mark-warning animate-pulse" />
        Загружаем данные из UNEC, обычно ~30 секунд…
      </span>
      <ul class="flex flex-wrap items-center gap-x-4 gap-y-1 text-micro font-mono uppercase tracking-wider">
        <li
          v-for="s in sections"
          :key="s.key"
          :class="colorClass(s.state)"
          class="flex items-center gap-1.5"
        >
          <span class="font-mono text-[0.95rem] leading-none">{{ icon(s.state) }}</span>
          {{ s.label }}
        </li>
      </ul>
    </div>
  </Transition>
</template>

<style scoped>
.lift-enter-active,
.lift-leave-active {
  transition:
    opacity 200ms ease,
    transform 200ms ease;
}
.lift-enter-from,
.lift-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
