<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { LessonOut, ScheduleOut } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/Skeleton.vue'
import { relativeTime, shortTime, todayIsoDow } from '@/lib/time'
import { lessonTypeRu } from '@/lib/locale'

const data = ref<ScheduleOut | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref<string | null>(null)

const DAY_LABELS_LONG = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const DAY_LABELS_FULL = [
  'Понедельник',
  'Вторник',
  'Среда',
  'Четверг',
  'Пятница',
  'Суббота',
  'Воскресенье',
]

const todayDow = computed(() => todayIsoDow())

// Group lessons by (day, start) so a single time-slot cell can hold multiple
// (alternating-week) lessons.
interface LessonGroup {
  day: number
  start: string
  end: string
  lessons: LessonOut[]
}

interface DayColumn {
  day: number
  groupsByStart: Map<string, LessonGroup>
  hasAnything: boolean
}

const grid = computed(() => {
  if (!data.value || !data.value.lessons.length) {
    return { days: [] as DayColumn[], timeSlots: [] as { start: string; end: string }[] }
  }

  // Collect unique time slots across all lessons, ordered by start.
  const slotMap = new Map<string, { start: string; end: string }>()
  for (const l of data.value.lessons) {
    const key = `${l.start}-${l.end}`
    if (!slotMap.has(key)) slotMap.set(key, { start: l.start, end: l.end })
  }
  const timeSlots = [...slotMap.values()].sort((a, b) => a.start.localeCompare(b.start))

  // Determine which days have any lessons; hide weekend columns if empty.
  const dayHas = new Set<number>()
  for (const l of data.value.lessons) dayHas.add(l.day)

  const days: DayColumn[] = []
  for (let d = 1; d <= 7; d++) {
    const isWeekend = d === 6 || d === 7
    if (isWeekend && !dayHas.has(d)) continue
    days.push({
      day: d,
      groupsByStart: new Map(),
      hasAnything: dayHas.has(d),
    })
  }

  for (const l of data.value.lessons) {
    const dayCol = days.find((c) => c.day === l.day)
    if (!dayCol) continue
    const key = `${l.start}-${l.end}`
    if (!dayCol.groupsByStart.has(key)) {
      dayCol.groupsByStart.set(key, { day: l.day, start: l.start, end: l.end, lessons: [] })
    }
    dayCol.groupsByStart.get(key)!.lessons.push(l)
  }

  return { days, timeSlots }
})

const lastSyncedRel = computed(() => {
  if (!data.value?.last_synced_at) return null
  return relativeTime(new Date(data.value.last_synced_at))
})

onMounted(async () => {
  await load()
})

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await api<ScheduleOut>('/v1/schedule')
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string }; status?: number }
    if (err?.status === 409) {
      error.value = 'unec_creds_missing'
    } else {
      error.value = err?.data?.detail ?? 'Не удалось загрузить расписание.'
    }
  } finally {
    loading.value = false
  }
}

async function refresh() {
  refreshing.value = true
  try {
    data.value = await api<ScheduleOut>('/v1/schedule/refresh', { method: 'POST' })
    error.value = null
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string } }
    error.value = err?.data?.detail ?? 'Не удалось обновить.'
  } finally {
    refreshing.value = false
  }
}

function parityBadge(p: LessonOut['week_parity']): { label: string; symbol: string } | null {
  if (p === 'normal') return null
  if (p === 'upper') return { label: 'верх', symbol: '◐' }
  return { label: 'низ', symbol: '◑' }
}
</script>

<template>
  <div>
    <PageHeader eyebrow="Расписание" title="Эта неделя">
      <template #actions>
        <span v-if="lastSyncedRel" class="text-micro text-muted font-mono">
          <span class="hidden sm:inline">Sync · </span>{{ lastSyncedRel }}
        </span>
        <button
          :disabled="refreshing"
          class="ml-auto mr-1 sm:ml-0 sm:mr-0 flex items-center gap-2 border border-ink-soft hover:border-ink hover:text-ink text-ink-soft px-3 sm:px-4 py-2 text-[0.85rem] tracking-tight transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-wait"
          :aria-label="refreshing ? 'Обновляем' : 'Обновить'"
          @click="refresh"
        >
          <svg
            width="14" height="14" viewBox="0 0 16 16" fill="none"
            :class="refreshing ? 'animate-spin' : ''"
          >
            <path d="M14 8a6 6 0 1 1-2-4.5L14 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M14 1.5v3.5h-3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="hidden sm:inline">{{ refreshing ? 'Обновляем…' : 'Обновить' }}</span>
        </button>
      </template>
    </PageHeader>

    <div class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16">
      <!-- Error banner — shown above content when we still have data to display -->
      <div
        v-if="error && error !== 'unec_creds_missing' && data?.lessons.length"
        class="hairline-t border-mark-negative/40 bg-mark-negative/5 px-5 py-3 mb-6 flex items-center justify-between text-[0.88rem]"
      >
        <span class="text-mark-negative">{{ error }}</span>
        <button
          class="text-micro font-mono uppercase tracking-wider text-mark-negative hover:text-ink cursor-pointer"
          @click="error = null"
        >
          закрыть
        </button>
      </div>

      <!-- Mobile loading skeleton -->
      <div v-if="loading" class="lg:hidden hairline-t border-border space-y-6 pt-5">
        <div v-for="i in 3" :key="`mload-${i}`">
          <Skeleton width="35%" height="1.05rem" />
          <div class="mt-3 grid grid-cols-[3.5rem_1fr] gap-4">
            <Skeleton width="2.5rem" height="0.85rem" />
            <div>
              <Skeleton width="3rem" height="1rem" />
              <Skeleton width="80%" height="0.9rem" class="mt-2" />
              <Skeleton width="55%" height="0.8rem" class="mt-1.5" />
            </div>
          </div>
        </div>
      </div>

      <!-- Desktop loading skeleton — mimics the eventual table grid -->
      <div v-if="loading" class="hidden lg:block hairline-t border-border">
        <table class="w-full border-separate border-spacing-0">
          <thead>
            <tr>
              <th class="hairline-r hairline-b w-[88px] py-4 px-3 text-left">
                <Skeleton width="3rem" height="0.7rem" />
              </th>
              <th
                v-for="d in 5"
                :key="d"
                class="hairline-r hairline-b py-4 px-4 text-left"
              >
                <Skeleton width="3.5rem" height="1.05rem" />
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in 4" :key="r" class="align-top">
              <td class="hairline-r hairline-b py-5 px-3">
                <Skeleton width="2.5rem" height="0.95rem" />
                <Skeleton width="2.5rem" height="0.78rem" class="mt-1.5" />
              </td>
              <td v-for="c in 5" :key="c" class="hairline-r hairline-b py-4 px-4">
                <Skeleton width="80%" height="0.95rem" />
                <Skeleton width="50%" height="0.78rem" class="mt-2" />
                <Skeleton width="60%" height="0.78rem" class="mt-1.5" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Missing UNEC creds -->
      <div
        v-else-if="error === 'unec_creds_missing'"
        class="hairline-t pt-12 max-w-2xl"
      >
        <div class="eyebrow mb-4">Нужно действие</div>
        <h2
          class="text-display text-ink leading-tight mb-4"

        >
          Сначала привяжите аккаунт UNEC
        </h2>
        <p class="text-ink-soft mb-8 max-w-lg">
          Без логина и пароля от
          <span class="font-mono text-[0.9em] bg-bg-deep px-1 rounded-sm">kabinet.unec.edu.az</span>
          мы не можем тянуть ваше расписание.
        </p>
        <RouterLink
          :to="{ name: 'settings' }"
          class="inline-block bg-ink text-bg px-6 py-2.5 text-[0.9rem] hover:bg-ink-soft transition-colors"
        >
          Перейти в настройки →
        </RouterLink>
      </div>

      <!-- Generic error — only shown when there's nothing else to show -->
      <div v-else-if="error && !data?.lessons.length" class="text-mark-negative">
        {{ error }}
      </div>

      <!-- Empty (no lessons even after sync) -->
      <div v-else-if="!data?.lessons.length" class="text-muted hairline-t pt-12">
        В кабинете не нашлось ни одной пары.
      </div>

      <!-- Mobile: per-day vertical list (lg+ uses the table grid below) -->
      <div v-else class="lg:hidden hairline-t border-border">
        <section
          v-for="dc in grid.days"
          :key="`mobile-${dc.day}`"
          class="hairline-b py-5"
          :class="{ 'bg-bg-soft': dc.day === todayDow }"
        >
          <div class="flex items-baseline gap-3 mb-4 px-1">
            <h3 class="text-[1.05rem] font-semibold text-ink">
              {{ DAY_LABELS_FULL[dc.day - 1] }}
            </h3>
            <span
              v-if="dc.day === todayDow"
              class="text-micro font-mono uppercase tracking-wider text-bg bg-ink px-1.5 py-0.5 rounded-sm"
            >
              сегодня
            </span>
          </div>

          <ul class="space-y-5">
            <li
              v-for="slot in grid.timeSlots.filter((s) => dc.groupsByStart.get(`${s.start}-${s.end}`))"
              :key="`m-${dc.day}-${slot.start}`"
            >
              <div
                v-for="(lesson, i) in dc.groupsByStart.get(`${slot.start}-${slot.end}`)!.lessons"
                :key="lesson.id"
                class="grid grid-cols-[3.5rem_1fr] gap-4"
                :class="i > 0 ? 'mt-3 pt-3 border-t border-border/60' : ''"
              >
                <div class="font-mono text-[0.85rem] text-ink leading-tight pt-0.5">
                  {{ shortTime(slot.start) }}
                  <div class="text-muted text-[0.7rem] mt-0.5">
                    {{ shortTime(slot.end) }}
                  </div>
                </div>

                <div>
                  <div
                    v-if="parityBadge(lesson.week_parity)"
                    class="text-micro font-mono uppercase tracking-wider text-muted mb-1 flex items-center gap-1.5"
                  >
                    <span class="text-ink">{{ parityBadge(lesson.week_parity)!.symbol }}</span>
                    <span>{{ parityBadge(lesson.week_parity)!.label }} нед</span>
                  </div>

                  <div v-if="lesson.room" class="mb-1.5">
                    <span class="font-mono text-[0.88rem] font-semibold text-ink bg-bg-deep px-2 py-0.5 rounded-sm">
                      {{ lesson.room }}
                    </span>
                  </div>

                  <div class="text-[0.95rem] text-ink leading-snug">
                    {{ lesson.subject }}
                  </div>

                  <div class="mt-1 text-[0.8rem] text-muted">
                    <span v-if="lesson.lesson_type">{{ lessonTypeRu(lesson.lesson_type) }}</span>
                    <span v-if="lesson.lesson_type && lesson.teacher" class="mx-1.5 text-muted-soft">·</span>
                    <span v-if="lesson.teacher">{{ lesson.teacher }}</span>
                  </div>
                </div>
              </div>
            </li>
          </ul>

          <p
            v-if="!grid.timeSlots.some((s) => dc.groupsByStart.get(`${s.start}-${s.end}`))"
            class="text-muted text-[0.85rem] px-1"
          >
            Нет занятий.
          </p>
        </section>
      </div>

      <!-- Sync status footer — kept outside the layout-specific blocks -->
      <div
        v-if="data?.sync_status === 'error' && data.sync_error"
        class="mt-6 text-micro text-mark-negative"
      >
        Ошибка последней синхронизации: {{ data.sync_error }}
      </div>

      <!-- Desktop: full week table grid -->
      <div v-else class="hidden lg:block hairline-t border-border">
        <table class="w-full border-separate border-spacing-0">
          <thead>
            <tr>
              <th
                class="hairline-r hairline-b w-[88px] py-4 px-3 text-left align-bottom"
              >
                <span class="eyebrow">Время</span>
              </th>
              <th
                v-for="dc in grid.days"
                :key="dc.day"
                class="hairline-r hairline-b py-4 px-4 text-left align-bottom"
                :class="{ 'bg-bg-deep': dc.day === todayDow }"
              >
                <div class="flex items-baseline gap-2">
                  <span
                    class="text-[1.05rem] font-medium"
                    :class="dc.day === todayDow ? 'text-accent' : 'text-ink'"
                    :title="DAY_LABELS_FULL[dc.day - 1]"
                  >
                    {{ DAY_LABELS_LONG[dc.day - 1] }}
                  </span>
                  <span
                    v-if="dc.day === todayDow"
                    class="text-micro font-mono uppercase tracking-wider text-accent"
                  >
                    сегодня
                  </span>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="slot in grid.timeSlots"
              :key="slot.start"
              class="align-top"
            >
              <td class="hairline-r hairline-b py-5 px-3 text-right">
                <div class="font-mono text-[0.95rem] text-ink leading-tight">
                  {{ shortTime(slot.start) }}
                </div>
                <div class="font-mono text-[0.78rem] text-muted leading-tight mt-0.5">
                  {{ shortTime(slot.end) }}
                </div>
              </td>

              <td
                v-for="dc in grid.days"
                :key="dc.day + slot.start"
                class="hairline-r hairline-b py-4 px-4 min-w-[180px]"
                :class="{ 'bg-bg-soft': dc.day === todayDow }"
              >
                <template v-if="dc.groupsByStart.get(`${slot.start}-${slot.end}`)">
                  <div
                    v-for="(lesson, i) in dc.groupsByStart.get(`${slot.start}-${slot.end}`)!.lessons"
                    :key="lesson.id"
                    :class="i > 0 ? 'mt-4 pt-4 border-t border-border/60' : ''"
                  >
                    <!-- Parity badge -->
                    <div
                      v-if="parityBadge(lesson.week_parity)"
                      class="text-micro font-mono uppercase tracking-wider text-muted mb-1.5 flex items-center gap-1.5"
                    >
                      <span class="text-ink">{{ parityBadge(lesson.week_parity)!.symbol }}</span>
                      <span>{{ parityBadge(lesson.week_parity)!.label }} нед</span>
                    </div>

                    <!-- Room — pulled out as the visually dominant element -->
                    <div v-if="lesson.room" class="mb-2">
                      <span class="font-mono text-[0.95rem] font-semibold text-ink bg-bg-deep px-2 py-0.5 rounded-sm">
                        {{ lesson.room }}
                      </span>
                    </div>

                    <!-- Subject -->
                    <div class="text-[0.92rem] text-ink leading-snug mb-1">
                      {{ lesson.subject }}
                    </div>

                    <!-- Type -->
                    <div v-if="lesson.lesson_type" class="text-[0.8rem] text-muted mb-1">
                      {{ lessonTypeRu(lesson.lesson_type) }}
                    </div>

                    <!-- Teacher -->
                    <div v-if="lesson.teacher" class="text-[0.8rem] text-muted">
                      {{ lesson.teacher }}
                    </div>
                  </div>
                </template>
                <template v-else>
                  <span class="text-muted-soft text-micro font-mono">·</span>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>
