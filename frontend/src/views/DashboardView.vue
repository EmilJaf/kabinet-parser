<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type {
  CalendarTodayOut,
  GradesOut,
  LessonOut,
  MarkOut,
  ScheduleOut,
  SubjectOut,
} from '@/api/types'
import Skeleton from '@/components/Skeleton.vue'
import MarkBadge from '@/components/MarkBadge.vue'
import {
  dayName,
  formatDate,
  parseISODate,
  relativeTime,
  shortTime,
  todayIsoDow,
} from '@/lib/time'
import { lessonTypeRu } from '@/lib/locale'
import { useNow } from '@/composables/useNow'
import { PhConfetti, PhMoon } from '@phosphor-icons/vue'

const schedule = ref<ScheduleOut | null>(null)
const grades = ref<GradesOut | null>(null)
const calendar = ref<CalendarTodayOut | null>(null)
const loading = ref(true)
const credsMissing = ref(false)
const error = ref<string | null>(null)

const now = useNow()
const todayDow = todayIsoDow()

/** Combine a HH:MM:SS string with today's date into a Date object. */
function todayAt(timeStr: string): Date {
  const d = new Date(now.value)
  const [hh, mm, ss] = timeStr.split(':').map((p) => Number(p))
  d.setHours(hh ?? 0, mm ?? 0, ss ?? 0, 0)
  return d
}

/** Closest upcoming or in-progress lesson. Considers today first, then forward. */
const upcomingLesson = computed<
  { day: number; lesson: LessonOut; status: 'in_progress' | 'today' | 'future' } | null
>(() => {
  if (!schedule.value) return null
  const nowMs = now.value.getTime()

  // 1) Lesson happening right now (started, not yet ended).
  for (const l of schedule.value.lessons.filter((x) => x.day === todayDow)) {
    const start = todayAt(l.start).getTime()
    const end = todayAt(l.end).getTime()
    if (start <= nowMs && nowMs < end) {
      return { day: todayDow, lesson: l, status: 'in_progress' }
    }
  }

  // 2) Earliest later-today lesson that hasn't started yet.
  const laterToday = schedule.value.lessons
    .filter((l) => l.day === todayDow && todayAt(l.start).getTime() > nowMs)
    .sort((a, b) => a.start.localeCompare(b.start))
  if (laterToday.length) {
    return { day: todayDow, lesson: laterToday[0], status: 'today' }
  }

  // 3) Next day with any lessons.
  for (let offset = 1; offset <= 7; offset++) {
    const target = ((todayDow - 1 + offset) % 7) + 1
    const lessons = schedule.value.lessons
      .filter((l) => l.day === target)
      .sort((a, b) => a.start.localeCompare(b.start))
    if (lessons.length) return { day: target, lesson: lessons[0], status: 'future' }
  }
  return null
})

/** Human-readable countdown for the upcoming lesson card. */
const upcomingCountdown = computed<string | null>(() => {
  const u = upcomingLesson.value
  if (!u) return null
  const start = todayAt(u.lesson.start)
  if (u.status === 'in_progress') {
    const end = todayAt(u.lesson.end)
    return `идёт · до конца ${humanMinutes(end.getTime() - now.value.getTime())}`
  }
  if (u.status === 'today') {
    return `до начала ${humanMinutes(start.getTime() - now.value.getTime())}`
  }
  // Future day: just say which day it's on; no minute-level countdown.
  return dayName(u.day === 7 ? 0 : u.day)
})

function humanMinutes(ms: number): string {
  const totalMin = Math.max(0, Math.floor(ms / 60000))
  if (totalMin < 60) return `${totalMin} ${pluralRu(totalMin, ['минута', 'минуты', 'минут'])}`
  const h = Math.floor(totalMin / 60)
  const m = totalMin % 60
  if (m === 0) return `${h} ${pluralRu(h, ['час', 'часа', 'часов'])}`
  return `${h} ч ${m} мин`
}

function pluralRu(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100
  const b = a % 10
  if (a > 10 && a < 20) return forms[2]
  if (b > 1 && b < 5) return forms[1]
  if (b === 1) return forms[0]
  return forms[2]
}

const headerDate = computed(
  () => `${dayName(now.value.getDay())}, ${formatDate(now.value)}`,
)

const todayLessons = computed(() => {
  if (!schedule.value) return []
  // On weekends and AZ public holidays, the recurring weekday slots in the
  // DB are not real classes — hide them so the holiday/weekend branch wins.
  if (calendar.value && !calendar.value.is_workday) return []
  return [...schedule.value.lessons]
    .filter((l) => l.day === todayDow)
    .sort((a, b) => a.start.localeCompare(b.start))
})

interface RecentMark {
  mark: MarkOut
  subject: SubjectOut
  lessonTypeName: string | null
}

const recentMarks = computed<RecentMark[]>(() => {
  if (!grades.value) return []
  // Track insertion order so we can break ties within the same date.
  // UNEC returns marks chronologically (earlier pairs come first), so the
  // last-inserted mark for a day = the latest pair of that day.
  const all: (RecentMark & { _idx: number })[] = []
  let idx = 0
  for (const subject of grades.value.subjects) {
    for (const lt of subject.by_lesson_type) {
      for (const mark of lt.marks) {
        if (!mark.mark_code || mark.mark_code.trim() === '') continue
        all.push({ mark, subject, lessonTypeName: lt.lesson_type_name, _idx: idx++ })
      }
    }
  }
  return all
    .sort((a, b) => {
      const byDate = b.mark.date.localeCompare(a.mark.date)
      // Same date → newer-inserted first (latest pair of the day on top).
      return byDate !== 0 ? byDate : b._idx - a._idx
    })
    .slice(0, 8)
})

// JS toLowerCase() turns Azerbaijani "İ" into "i" + U+0307 combining dot
// (two code units), so naïve string compares between schedule "XDİAK"
// and an acronym "xdiak" silently fail. Strip combining marks via NFD
// so both sides reduce to plain ASCII-ish letters first. Same trick
// flattens "ş" → "s", "ğ" → "g", etc.
function normalize(s: string): string {
  return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
}

// Build an acronym from a verbose subject title — first letter of each
// word ≥3 chars (skips Azerbaijani conjunctions like "və"). Strips trailing
// numeric suffix (e.g. "-4") so it can be compared separately.
function acronymOf(name: string): string {
  return normalize(name)
    .replace(/-\d+\b/g, '')
    .split(/[\s\-]+/)
    .filter((w) => w.length >= 3)
    .map((w) => w[0])
    .join('')
}

// "XDIAK-4" → "xdiak". Strips parens content, _b-style suffixes, dashes.
function compactSubject(name: string): string {
  return normalize(name)
    .replace(/\(.*?\)/g, '')
    .replace(/_[a-zəıöüşçğ]+\b/gi, '')
    .replace(/-\d+\b/g, '')
    .replace(/[\s\-]/g, '')
}

function trailingNum(name: string): string | null {
  return name.match(/-(\d+)\b/)?.[1] ?? null
}

/** Match a grades subject ("Xarici dildə işgüzar və akademik kommunikasiya-4")
 *  to a schedule subject ("XDIAK-4"). Tries exact, substring, acronym. */
function matchesSubject(scheduleSubj: string, gradeSubj: string): boolean {
  const a = normalize(scheduleSubj).trim()
  const b = normalize(gradeSubj).trim()
  if (a === b) return true
  if (a.length > 6 && b.includes(a)) return true
  if (b.length > 6 && a.includes(b)) return true

  const acr = acronymOf(gradeSubj)
  if (acr.length >= 3) {
    const compact = compactSubject(scheduleSubj)
    if (compact.startsWith(acr)) {
      const ta = trailingNum(scheduleSubj)
      const tb = trailingNum(gradeSubj)
      if (ta && tb && ta !== tb) return false
      return true
    }
  }
  return false
}

// All schedule lessons grouped by their (verbose) subject string.
const lessonsBySubject = computed<
  Map<string, { day: number; start: string; lesson_type: string | null }[]>
>(() => {
  const m = new Map<string, { day: number; start: string; lesson_type: string | null }[]>()
  if (!schedule.value) return m
  for (const l of schedule.value.lessons) {
    const arr = m.get(l.subject) ?? []
    arr.push({ day: l.day, start: l.start, lesson_type: l.lesson_type })
    m.set(l.subject, arr)
  }
  for (const arr of m.values()) {
    arr.sort((a, b) => a.start.localeCompare(b.start))
  }
  return m
})

/** Loose match — same lesson type is named differently in schedule
 *  ("Seminar", "Mühazirə") vs grades ("Seminar", "Mühazirə").
 *  Compare lowercased prefixes for robustness. */
function sameLessonType(a: string | null, b: string | null): boolean {
  if (!a || !b) return false
  return a.trim().toLowerCase().startsWith(b.trim().toLowerCase().slice(0, 4))
    || b.trim().toLowerCase().startsWith(a.trim().toLowerCase().slice(0, 4))
}

/** Lesson start time for the given mark, if we can match by subject +
 *  weekday + (preferably) lesson type. Marks come from seminars, so when
 *  the same day has both a lecture and a seminar we pick the seminar. */
function startTimeFor(rm: RecentMark): string | null {
  // Find matching schedule subject — exact name first, then fuzzy
  // (acronym/substring) for cases like grades 'Xarici dildə işgüzar və
  // akademik kommunikasiya-4' ↔ schedule 'XDIAK-4'.
  let lessons = lessonsBySubject.value.get(rm.subject.name)
  if (!lessons || !lessons.length) {
    for (const [name, arr] of lessonsBySubject.value) {
      if (matchesSubject(name, rm.subject.name)) {
        lessons = arr
        break
      }
    }
  }
  if (!lessons || !lessons.length) return null

  // parseISODate returns local-midnight; getDay() reads local. JS Sun=0..Sat=6
  // → ISO Mon=1..Sun=7 to match Lesson.day.
  const jsDow = parseISODate(rm.mark.date).getDay()
  const dow = jsDow === 0 ? 7 : jsDow
  const sameDay = lessons.filter((l) => l.day === dow)
  if (!sameDay.length) return null
  // Prefer the lesson whose type matches the mark's lesson type (e.g.
  // a 'Seminar' mark → the Seminar lesson on that day). Fall back to first.
  const matched = sameDay.find((l) => sameLessonType(l.lesson_type, rm.lessonTypeName))
  return shortTime((matched ?? sameDay[0]).start)
}

const lastSync = computed(() => {
  const ts: string[] = []
  if (schedule.value?.last_synced_at) ts.push(schedule.value.last_synced_at)
  if (grades.value?.last_synced_at) ts.push(grades.value.last_synced_at)
  if (!ts.length) return null
  // Most recent of the two.
  ts.sort()
  return relativeTime(new Date(ts[ts.length - 1]))
})

onMounted(load)
onUnmounted(() => stopPolling())

let pollTimer: ReturnType<typeof setInterval> | null = null

function pending(): boolean {
  // Initial sync hasn't finished yet — keep showing the loader skeleton
  // and re-poll until the worker writes data into the DB.
  return (
    (schedule.value !== null && !schedule.value.last_synced_at) ||
    (grades.value !== null && !grades.value.last_synced_at)
  )
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function fetchOnce() {
  const results = await Promise.allSettled([
    api<ScheduleOut>('/v1/schedule'),
    api<GradesOut>('/v1/grades'),
    api<CalendarTodayOut>('/v1/calendar/today'),
  ])
  for (const r of results) {
    if (r.status === 'rejected') {
      const err = r.reason as { status?: number; data?: { detail?: string } }
      if (err?.status === 409) credsMissing.value = true
      else if (!error.value) error.value = err?.data?.detail ?? null
    }
  }
  if (results[0].status === 'fulfilled') schedule.value = results[0].value
  if (results[1].status === 'fulfilled') grades.value = results[1].value
  if (results[2].status === 'fulfilled') calendar.value = results[2].value
}

async function load() {
  loading.value = true
  error.value = null
  credsMissing.value = false
  await fetchOnce()
  if (pending()) {
    if (pollTimer === null) {
      pollTimer = setInterval(async () => {
        await fetchOnce()
        if (!pending()) {
          stopPolling()
          loading.value = false
        }
      }, 4000)
    }
  } else {
    loading.value = false
  }
}

function lessonTimeBlock(lesson: LessonOut): string {
  return `${shortTime(lesson.start)}–${shortTime(lesson.end)}`
}
</script>

<template>
  <div>
    <!-- Header — large date instead of generic "Dashboard" -->
    <header class="px-6 sm:px-8 lg:px-12 pt-6 sm:pt-9 lg:pt-10 pb-5 lg:pb-6">
      <div class="eyebrow mb-4">Сегодня</div>
      <h1
        class="text-[2rem] sm:text-display-xl text-ink leading-[1.05] sm:leading-[1] tracking-tight"
      >
        {{ headerDate }}
      </h1>
      <p v-if="lastSync" class="mt-4 text-micro text-muted font-mono">
        последняя синхронизация · {{ lastSync }}
      </p>
    </header>

    <!-- Missing UNEC creds — full-width prompt -->
    <div v-if="credsMissing && !loading" class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16">
      <div class="hairline-t pt-12 max-w-2xl">
        <div class="eyebrow mb-4">Нужно действие</div>
        <h2 class="text-display text-ink leading-tight mb-4"
>
          Подключите аккаунт UNEC
        </h2>
        <p class="text-ink-soft mb-8 max-w-lg">
          Без него Kabinet — пустая оболочка. Подключение занимает минуту.
        </p>
        <RouterLink :to="{ name: 'settings' }"
          class="inline-block bg-ink text-bg px-6 py-2.5 text-[0.9rem] hover:bg-ink-soft transition-colors">
          В настройки →
        </RouterLink>
      </div>
    </div>

    <!-- Two-column dashboard -->
    <div v-else class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16 grid lg:grid-cols-[1.4fr_1fr] gap-x-12 lg:gap-x-16 gap-y-10 lg:gap-y-12">
      <!-- LEFT: Today / next class -->
      <section>
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">Расписание на сегодня</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <div v-if="loading" class="space-y-6">
          <div v-for="i in 3" :key="i">
            <Skeleton width="40%" height="0.85rem" />
            <Skeleton width="80%" height="1.4rem" class="mt-2.5" />
            <Skeleton width="55%" height="0.85rem" class="mt-2" />
          </div>
        </div>

        <ul v-else-if="todayLessons.length" class="space-y-7">
          <li
            v-for="lesson in todayLessons"
            :key="lesson.id"
            class="grid grid-cols-[5.5rem_1fr] gap-6"
          >
            <div class="font-mono text-[0.95rem] text-ink leading-tight pt-1">
              {{ shortTime(lesson.start) }}
              <div class="text-muted text-[0.78rem] mt-0.5">
                {{ shortTime(lesson.end) }}
              </div>
            </div>
            <div>
              <div class="text-[1.05rem] text-ink leading-snug">
                {{ lesson.subject }}
              </div>
              <div class="mt-1.5 flex items-baseline gap-3 text-[0.85rem]">
                <span
                  v-if="lesson.room"
                  class="font-mono text-ink font-semibold bg-bg-deep px-2 py-0.5 rounded-sm text-[0.88rem]"
                >
                  {{ lesson.room }}
                </span>
                <span v-if="lesson.lesson_type" class="text-muted">
                  {{ lessonTypeRu(lesson.lesson_type) }}
                </span>
              </div>
              <div v-if="lesson.teacher" class="text-[0.85rem] text-muted mt-1.5">
                {{ lesson.teacher }}
              </div>
            </div>
          </li>
        </ul>

        <!-- No classes today: explain why (holiday / weekend) and show next class -->
        <div v-else>
          <div class="mb-6">
            <div
              v-if="calendar?.is_holiday"
              class="flex items-start gap-3 text-[1.5rem] text-ink leading-tight"
            >
              <PhConfetti
                class="shrink-0 mt-1 text-mark-positive"
                :size="26"
                weight="duotone"
                aria-hidden="true"
              />
              <span>Праздник: {{ calendar.holiday_name }}</span>
            </div>
            <div
              v-else-if="calendar?.is_weekend"
              class="flex items-start gap-3 text-[1.5rem] text-ink-soft leading-tight"
            >
              <PhMoon
                class="shrink-0 mt-1"
                :size="24"
                weight="regular"
                aria-hidden="true"
              />
              <span>Сегодня выходной</span>
            </div>
            <p v-else class="text-[1.5rem] text-ink-soft leading-tight">
              Сегодня свободно.
            </p>
            <p
              v-if="calendar && !calendar.is_workday"
              class="text-[0.85rem] text-muted mt-2 pl-[34px]"
            >
              Следующий рабочий день — {{ formatDate(parseISODate(calendar.next_workday)) }}.
            </p>
          </div>
          <div v-if="upcomingLesson" class="grid grid-cols-[5.5rem_1fr] gap-6">
            <div class="font-mono text-[0.95rem] text-ink leading-tight pt-1">
              {{ shortTime(upcomingLesson.lesson.start) }}
              <div class="text-muted text-[0.72rem] mt-0.5 uppercase tracking-wider">
                {{
                  upcomingLesson.status === 'in_progress' || upcomingLesson.status === 'today'
                    ? 'сегодня'
                    : dayName(upcomingLesson.day === 7 ? 0 : upcomingLesson.day, true)
                }}
              </div>
            </div>
            <div>
              <div class="eyebrow mb-1.5">
                {{ upcomingLesson.status === 'in_progress' ? 'Идёт сейчас' : 'Следующая пара' }}
              </div>
              <div class="text-[1.05rem] text-ink leading-snug">
                {{ upcomingLesson.lesson.subject }}
              </div>
              <div class="mt-1.5 flex items-baseline gap-3 text-[0.85rem] flex-wrap">
                <span
                  v-if="upcomingLesson.lesson.room"
                  class="font-mono text-ink font-semibold bg-bg-deep px-2 py-0.5 rounded-sm text-[0.88rem]"
                >
                  {{ upcomingLesson.lesson.room }}
                </span>
                <span v-if="upcomingLesson.lesson.lesson_type" class="text-muted">
                  {{ lessonTypeRu(upcomingLesson.lesson.lesson_type) }}
                </span>
              </div>
              <div
                v-if="upcomingCountdown"
                class="mt-2.5 text-micro font-mono uppercase tracking-wider"
                :class="
                  upcomingLesson.status === 'in_progress'
                    ? 'text-mark-positive'
                    : 'text-muted'
                "
              >
                {{ upcomingCountdown }}
              </div>
            </div>
          </div>
        </div>

        <RouterLink
          :to="{ name: 'schedule' }"
          class="mt-10 inline-block text-[0.9rem] text-ink-soft hover:text-ink transition-colors"
        >
          Вся неделя
          <span class="ml-1">→</span>
        </RouterLink>
      </section>

      <!-- RIGHT: Recent marks -->
      <section>
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">Свежие отметки</span>
          <span class="hairline flex-1 border-t" />
        </div>

        <div v-if="loading" class="space-y-3">
          <div v-for="i in 6" :key="i" class="flex items-baseline gap-3">
            <Skeleton width="3rem" height="0.85rem" />
            <Skeleton width="60%" height="0.85rem" />
            <Skeleton width="2rem" height="0.85rem" />
          </div>
        </div>

        <ul v-else-if="recentMarks.length" class="space-y-3.5">
          <li
            v-for="(rm, i) in recentMarks"
            :key="i"
            class="grid grid-cols-[6.5rem_1fr_2rem] gap-4 items-baseline"
          >
            <span class="font-mono text-[0.78rem] text-muted whitespace-nowrap">
              <span>{{ formatDate(parseISODate(rm.mark.date)) }}</span>
              <span v-if="startTimeFor(rm)" class="text-muted-soft">
                &middot; {{ startTimeFor(rm) }}
              </span>
            </span>
            <span class="text-[0.85rem] text-ink-soft truncate" :title="rm.subject.name">
              {{ rm.subject.name }}
            </span>
            <span class="text-right">
              <MarkBadge :code="rm.mark.mark_code" />
            </span>
          </li>
        </ul>

        <div v-else class="text-muted text-[0.9rem]">
          Нет отметок за этот семестр.
        </div>

        <RouterLink
          :to="{ name: 'grades' }"
          class="mt-10 inline-block text-[0.9rem] text-ink-soft hover:text-ink transition-colors"
        >
          Журнал целиком
          <span class="ml-1">→</span>
        </RouterLink>
      </section>
    </div>
  </div>
</template>
