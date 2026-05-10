<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, reactive, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { GradesOut, LessonTypeMarksOut, ScheduleOut, SubjectOut } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/Skeleton.vue'
import MarkBadge from '@/components/MarkBadge.vue'
import FilterSelect from '@/components/FilterSelect.vue'
import { relativeTime, formatDate, parseISODate, todayIsoDow } from '@/lib/time'
import { gradingFieldRu, lessonTypeRu, semesterLabelRu } from '@/lib/locale'
import { EDU_YEAR_OPTIONS, type UnecOption } from '@/lib/unec'

// A grading-detail dict is meaningful only if at least one *value* is non-empty
// (excluding the student-name row that always appears in the writing tab).
const META_KEYS = new Set(['№', 'Soyad Ad Ata adı'])

function dictHasRealValues(dict: Record<string, string> | null | undefined): boolean {
  if (!dict) return false
  return Object.entries(dict).some(
    ([k, v]) => !META_KEYS.has(k) && v != null && v.trim() !== '',
  )
}

function lessonTypeHasContent(lt: LessonTypeMarksOut): boolean {
  if (lt.marks.length > 0) return true
  // UNEC returns the SAME finalEval and scheme dicts in every popup, even for
  // lesson types the student isn't actually enrolled in. So those two fields
  // are unreliable — only use lesson-type-specific tabs as proof.
  return (
    dictHasRealValues(lt.course_work) ||
    dictHasRealValues(lt.independent_work) ||
    dictHasRealValues(lt.writing)
  )
}

const data = ref<GradesOut | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref<string | null>(null)

// Filters — sync with the URL so the choice survives reload + back-button.
const route = useRoute()
const router = useRouter()

function intFromQuery(key: string): number | null {
  const raw = route.query[key]
  const value = Array.isArray(raw) ? raw[0] : raw
  const parsed = value ? Number(value) : NaN
  return Number.isFinite(parsed) ? parsed : null
}

const selectedYearId = ref<number | null>(intFromQuery('year'))
const selectedSemesterId = ref<number | null>(intFromQuery('semester'))

// Available semesters for the currently-selected year. Semester IDs are
// per-year in UNEC, so we fetch this list each time the year changes.
const availableSemesters = ref<UnecOption[]>([])

// Course codes (e.g. "10_24_02_574-R_01300") with a class today. We match by
// code rather than name because schedule/journal show different display names
// for the same course — the code is the only stable identifier across both.
const todayCourseCodes = ref<Set<string>>(new Set())

// Track which subject IDs are expanded; track active lesson_type tab per subject.
const expanded = reactive<Set<string>>(new Set())
const activeTab = reactive<Record<string, number>>({})

const lastSyncedRel = computed(() => {
  if (!data.value?.last_synced_at) return null
  return relativeTime(new Date(data.value.last_synced_at))
})

// Localised semester options for the dropdown.
const semesterOptions = computed<UnecOption[]>(() =>
  availableSemesters.value.map((s) => ({ id: s.id, label: semesterLabelRu(s.label) })),
)

// Initialised flag — watchers below should only react to *user* interactions,
// not to the initial setup that happens during onMounted.
let initialised = false

onMounted(async () => {
  if (selectedYearId.value != null) {
    // We have a year from URL; fetch its semesters in parallel with the data
    // request so the dropdown is populated.
    void loadSemesters(selectedYearId.value)
  }
  void loadTodaySubjects()
  await load()
  // After load, if we picked the year from the response (URL didn't have one),
  // backfill the semester options.
  if (selectedYearId.value != null && availableSemesters.value.length === 0) {
    await loadSemesters(selectedYearId.value)
  }
  initialised = true
})

async function loadTodaySubjects() {
  try {
    const sched = await api<ScheduleOut>('/v1/schedule')
    const today = todayIsoDow()
    todayCourseCodes.value = new Set(
      sched.lessons
        .filter((l) => l.day === today && l.subject_code)
        .map((l) => l.subject_code as string),
    )
  } catch {
    // Schedule failure is non-blocking — the journal works without highlights.
    todayCourseCodes.value = new Set()
  }
}

/**
 * Pull the course code prefix out of the journal's group_name field
 * ("10_24_02_574-R_01300_XDİAK-4 (ingilis)_b" → "10_24_02_574-R_01300").
 * Format mirrors what the schedule parser stores in `lesson.subject_code`.
 */
function subjectCourseCode(subject: SubjectOut): string | null {
  if (!subject.group_name) return null
  const match = subject.group_name.match(/^([\w-]+_\d+)_/)
  return match ? match[1] : null
}

function hasClassToday(subject: SubjectOut): boolean {
  const code = subjectCourseCode(subject)
  return code != null && todayCourseCodes.value.has(code)
}

// Subjects with a class today bubble to the top, others keep the backend's
// alphabetical order. If no class today, the order is unchanged.
const sortedSubjects = computed<SubjectOut[]>(() => {
  if (!data.value) return []
  const today: SubjectOut[] = []
  const rest: SubjectOut[] = []
  for (const s of data.value.subjects) {
    if (hasClassToday(s)) today.push(s)
    else rest.push(s)
  }
  return [...today, ...rest]
})

watch(selectedYearId, async (newYear, oldYear) => {
  if (!initialised || newYear === oldYear) return
  if (newYear == null) return
  // Year changed — drop the stale semester ID, refresh the option list, then
  // auto-select the first valid semester. The semester watcher below will
  // pick up the change and call load().
  selectedSemesterId.value = null
  await loadSemesters(newYear)
  if (availableSemesters.value.length) {
    selectedSemesterId.value = availableSemesters.value[0].id
  }
})

watch(selectedSemesterId, async (newSem, oldSem) => {
  if (!initialised || newSem === oldSem) return
  await router.replace({
    query: {
      ...route.query,
      year: selectedYearId.value != null ? String(selectedYearId.value) : undefined,
      semester: newSem != null ? String(newSem) : undefined,
    },
  })
  expanded.clear()
  for (const k of Object.keys(activeTab)) delete activeTab[k]
  await load()
})

async function loadSemesters(yearId: number) {
  try {
    const res = await api<{ year_id: number; semesters: UnecOption[] }>(
      '/v1/grades/options',
      { query: { year_id: yearId } },
    )
    availableSemesters.value = res.semesters
  } catch {
    availableSemesters.value = []
  }
}

function buildParams(): Record<string, string | number> {
  const params: Record<string, string | number> = {}
  if (selectedYearId.value != null) params.year_id = selectedYearId.value
  if (selectedSemesterId.value != null) params.semester_id = selectedSemesterId.value
  return params
}

let pollTimer: ReturnType<typeof setInterval> | null = null
function pending(): boolean {
  return data.value !== null && !data.value.last_synced_at
}
function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}
onUnmounted(stopPolling)

async function fetchOnce() {
  data.value = await api<GradesOut>('/v1/grades', { query: buildParams() })
  if (data.value) {
    if (selectedYearId.value == null && data.value.edu_year_id != null) {
      selectedYearId.value = data.value.edu_year_id
    }
    if (selectedSemesterId.value == null && data.value.edu_semester_id != null) {
      selectedSemesterId.value = data.value.edu_semester_id
    }
  }
}

async function load() {
  loading.value = true
  error.value = null
  stopPolling()
  try {
    await fetchOnce()
    if (pending()) {
      pollTimer = setInterval(async () => {
        try {
          await fetchOnce()
        } catch { /* keep polling */ }
        if (!pending()) {
          stopPolling()
          loading.value = false
        }
      }, 4000)
      return  // skip the finally — poll keeps loading=true
    }
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string }; status?: number }
    if (err?.status === 409) {
      error.value = 'unec_creds_missing'
    } else if (err?.data?.detail === 'historical_years_unavailable') {
      error.value =
        'Кабинет UNEC не отдаёт данные за прошлые годы по нашему запросу — ' +
        'они доступны только в текущем учебном году.'
      data.value = null
    } else {
      error.value = err?.data?.detail ?? 'Не удалось загрузить.'
    }
  } finally {
    loading.value = false
  }
}

async function refresh() {
  refreshing.value = true
  try {
    data.value = await api<GradesOut>('/v1/grades/refresh', {
      method: 'POST',
      query: buildParams(),
    })
    error.value = null
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string } }
    error.value = err?.data?.detail ?? 'Не удалось обновить.'
  } finally {
    refreshing.value = false
  }
}

function toggle(subjectId: string) {
  if (expanded.has(subjectId)) {
    expanded.delete(subjectId)
  } else {
    expanded.add(subjectId)
    // Default the active tab to the first non-empty lesson type.
    const subject = data.value?.subjects.find((s) => s.id === subjectId)
    if (subject && !(subjectId in activeTab)) {
      const visible = visibleLessonTypes(subject)
      if (visible.length) activeTab[subjectId] = visible[0].lesson_type_id
    }
  }
}

function visibleLessonTypes(subject: SubjectOut): LessonTypeMarksOut[] {
  return subject.by_lesson_type.filter(lessonTypeHasContent)
}

// Two-tier attendance thresholds.
//   ≥ 25% → "срез" (cut from the course), red
//   ≥ 20% → warning ("careful, don't skip more"), amber
const ABSENCE_CUT_THRESHOLD = 25
const ABSENCE_WARN_THRESHOLD = 20

// UNEC's pre-exam max is universally 50 (the other 50 are the final exam).
// Older popups don't always include it in the scheme dict — fall back.
const PRE_EXAM_MAX = '50'

type AbsenceLevel = 'ok' | 'warn' | 'cut'

function absenceLevel(pct: number | null): AbsenceLevel {
  if (pct === null) return 'ok'
  if (pct >= ABSENCE_CUT_THRESHOLD) return 'cut'
  if (pct >= ABSENCE_WARN_THRESHOLD) return 'warn'
  return 'ok'
}

interface SubjectStats {
  absencePercent: number | null
  absenceLevel: AbsenceLevel
  seminar: { average: string; max: string | null; markCount: number } | null
  currentScore: { value: string; max: string | null } | null
}

function parseLooseNumber(raw: string | undefined | null): number | null {
  if (raw == null) return null
  const trimmed = raw.trim().replace(',', '.')
  if (trimmed === '') return null
  const num = Number(trimmed)
  return Number.isFinite(num) ? num : null
}

function isSeminarLessonType(lt: LessonTypeMarksOut): boolean {
  return (lt.lesson_type_name ?? '').toLowerCase().includes('seminar')
}

/** A "real" mark — numeric score, not an attendance flag (i/e, q/b). */
function isNumericMark(code: string | null): boolean {
  if (!code) return false
  return /^\d+([.,]\d+)?$/.test(code.trim())
}

function statsFor(subject: SubjectOut): SubjectStats {
  let absencePercent: number | null = null
  let seminarAverage: string | null = null
  let seminarMax: string | null = null
  let seminarMarkCount = 0
  let currentScoreValue: string | null = null
  let currentScoreMax: string | null = null

  for (const lt of visibleLessonTypes(subject)) {
    const fe = lt.final_eval
    const scheme = lt.scheme

    if (fe) {
      // Worst-case absence across lesson types — that's what counts for "срез".
      const qf = parseLooseNumber(fe['Qaib faizi'])
      if (qf !== null) {
        absencePercent = absencePercent === null ? qf : Math.max(absencePercent, qf)
      }

      // Seminar average lives in the final_eval of any lesson type that has
      // seminars graded (typically the Seminar lesson type itself).
      const sa = (fe['Seminarın orta balı'] ?? '').trim()
      if (sa) seminarAverage = sa

      // Running total of points so far this semester.
      const cur = (fe['Cari qiymətləndirmə'] ?? '').trim()
      if (cur) currentScoreValue = cur
    }

    if (scheme) {
      // Max possible for the seminar component (e.g. 20).
      const sMax = (scheme['Seminar'] ?? '').trim()
      if (sMax && seminarMax === null) seminarMax = sMax
      // Max points reachable before the final exam (e.g. 50).
      const cMax = (scheme['İmtahana qədər yekun'] ?? '').trim()
      if (cMax && currentScoreMax === null) currentScoreMax = cMax
    }

    // Count of *graded* marks under seminar — attendance flags (i/e, q/b)
    // don't count as scores.
    if (isSeminarLessonType(lt)) {
      seminarMarkCount += lt.marks.filter((m) => isNumericMark(m.mark_code)).length
    }
  }

  return {
    absencePercent,
    absenceLevel: absenceLevel(absencePercent),
    seminar:
      seminarAverage || seminarMarkCount > 0
        ? { average: seminarAverage ?? '—', max: seminarMax, markCount: seminarMarkCount }
        : null,
    // Always show "набрано X/50" — keeps the template consistent across
    // semesters where some subjects' schemes are missing.
    currentScore: {
      value: currentScoreValue ?? '—',
      max: currentScoreMax ?? PRE_EXAM_MAX,
    },
  }
}

function pluralizeMarks(n: number): string {
  return pluralize(n, ['отметка', 'отметки', 'отметок'])
}

function formatPercent(n: number): string {
  // Trim ".0" so "13.0" reads as "13", but keep "13.33" honest.
  if (Number.isInteger(n)) return `${n}%`
  return `${n.toFixed(2).replace(/\.?0+$/, '')}%`
}

function activeLessonType(subject: SubjectOut): LessonTypeMarksOut | null {
  const visible = visibleLessonTypes(subject)
  if (!visible.length) return null
  const tabId = activeTab[subject.id]
  if (tabId == null) return visible[0]
  return visible.find((lt) => lt.lesson_type_id === tabId) ?? visible[0]
}

function setTab(subjectId: string, lessonTypeId: number) {
  activeTab[subjectId] = lessonTypeId
}

function nonEmptyEntries(dict: Record<string, string> | null): [string, string][] {
  if (!dict) return []
  return Object.entries(dict).filter(
    ([k, v]) => !META_KEYS.has(k) && v !== '' && v != null,
  )
}

function sortedMarks(marks: LessonTypeMarksOut['marks']) {
  return [...marks].sort((a, b) => b.date.localeCompare(a.date))
}
</script>

<template>
  <div>
    <PageHeader eyebrow="Журнал" title="Электронный журнал">
      <template #actions>
        <span v-if="lastSyncedRel" class="text-micro text-muted font-mono">
          <span class="hidden sm:inline">Sync · </span>{{ lastSyncedRel }}
        </span>
        <button
          :disabled="refreshing"
          class="ml-auto mr-1 sm:ml-0 sm:mr-0 flex items-center gap-2 border border-ink-soft hover:border-ink hover:text-ink text-ink-soft px-3 sm:px-4 py-2 text-[0.85rem] tracking-tight transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-wait"
          :aria-label="refreshing ? 'Тянем' : 'Обновить'"
          @click="refresh"
        >
          <svg
            width="14" height="14" viewBox="0 0 16 16" fill="none"
            :class="refreshing ? 'animate-spin' : ''"
          >
            <path d="M14 8a6 6 0 1 1-2-4.5L14 5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M14 1.5v3.5h-3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span class="hidden sm:inline">{{ refreshing ? 'Тянем…' : 'Обновить' }}</span>
        </button>
      </template>
      <template #below>
        <div class="mt-5 flex flex-wrap items-center gap-x-6 sm:gap-x-7 gap-y-3">
          <FilterSelect
            label="год"
            :options="EDU_YEAR_OPTIONS"
            :model-value="selectedYearId"
            @update:model-value="(v) => (selectedYearId = Number(v))"
          />
          <FilterSelect
            v-if="semesterOptions.length"
            class="ml-auto mr-1 sm:ml-0 sm:mr-0"
            label="семестр"
            :options="semesterOptions"
            :model-value="selectedSemesterId"
            @update:model-value="(v) => (selectedSemesterId = Number(v))"
          />
          <span
            v-if="data && !loading"
            class="text-muted text-[0.85rem] ml-auto hidden sm:inline"
          >
            {{ data.subjects.length }} {{ pluralizeSubjects(data.subjects.length) }}
          </span>
        </div>
      </template>
    </PageHeader>

    <div class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16">
      <!-- Error banner — shown above content when we still have data to display -->
      <div
        v-if="error && error !== 'unec_creds_missing' && data?.subjects.length"
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

      <!-- Loading -->
      <div v-if="loading" class="hairline-t pt-8 space-y-6">
        <div v-for="i in 4" :key="i" class="space-y-2">
          <Skeleton width="55%" height="1.4rem" />
          <Skeleton width="35%" height="0.85rem" />
        </div>
      </div>

      <!-- No UNEC creds -->
      <div v-else-if="error === 'unec_creds_missing'" class="hairline-t pt-12 max-w-2xl">
        <div class="eyebrow mb-4">Нужно действие</div>
        <h2 class="text-display text-ink leading-tight mb-4"
>
          Сначала привяжите аккаунт UNEC
        </h2>
        <p class="text-ink-soft mb-8 max-w-lg">
          Без логина и пароля от
          <span class="font-mono text-[0.9em] bg-bg-deep px-1 rounded-sm">kabinet.unec.edu.az</span>
          мы не можем тянуть ваш журнал.
        </p>
        <RouterLink :to="{ name: 'settings' }"
          class="inline-block bg-ink text-bg px-6 py-2.5 text-[0.9rem] hover:bg-ink-soft transition-colors">
          Перейти в настройки →
        </RouterLink>
      </div>

      <!-- Generic error — only shown when there's nothing else to show -->
      <div v-else-if="error && !data?.subjects.length" class="text-mark-negative">
        {{ error }}
      </div>

      <!-- Empty -->
      <div v-else-if="!data?.subjects.length" class="text-muted hairline-t pt-12">
        В выбранном семестре нет предметов.
      </div>

      <!-- Subject list (editorial table-of-contents style) -->
      <ul v-else class="hairline-t">
        <li v-for="(subject, idx) in sortedSubjects" :key="subject.id" class="hairline-b">
          <!-- Header row — clickable -->
          <button
            class="w-full text-left py-5 sm:py-6 group cursor-pointer transition-colors hover:bg-bg-deep/30 px-2 -mx-2"
            @click="toggle(subject.id)"
          >
            <div class="flex items-baseline gap-3 sm:gap-6">
              <span class="font-mono text-micro text-muted-soft tabular-nums w-6 hidden sm:inline">
                {{ String(idx + 1).padStart(2, '0') }}
              </span>

              <div class="flex-1 min-w-0">
                <div class="text-[1.15rem] sm:text-[1.5rem] leading-tight text-ink">
                  {{ subject.name }}
                </div>
                <!-- Stats — label / value pairs, gap-separated, no bullet dots -->
                <div class="mt-2.5 flex items-baseline gap-x-7 gap-y-2 flex-wrap text-[0.85rem]">
                  <!-- Credits -->
                  <span v-if="subject.credits" class="flex items-baseline gap-1.5">
                    <span class="text-muted text-[0.78rem]">кредиты</span>
                    <span class="font-mono text-ink">{{ subject.credits }}</span>
                  </span>

                  <!-- Absence: ok / warn (amber) / cut (red + СРЕЗ) -->
                  <span
                    v-if="statsFor(subject).absencePercent !== null"
                    class="flex items-baseline gap-1.5"
                  >
                    <span
                      class="text-[0.78rem]"
                      :class="{
                        'text-muted': statsFor(subject).absenceLevel === 'ok',
                        'text-mark-warning': statsFor(subject).absenceLevel === 'warn',
                        'text-mark-negative': statsFor(subject).absenceLevel === 'cut',
                      }"
                    >пропуски</span>
                    <span
                      class="font-mono"
                      :class="{
                        'text-ink': statsFor(subject).absenceLevel === 'ok',
                        'text-mark-warning font-semibold': statsFor(subject).absenceLevel === 'warn',
                        'text-mark-negative font-semibold': statsFor(subject).absenceLevel === 'cut',
                      }"
                    >{{ formatPercent(statsFor(subject).absencePercent!) }}</span>
                    <span
                      v-if="statsFor(subject).absenceLevel === 'cut'"
                      class="text-micro font-mono uppercase tracking-wider text-mark-negative"
                    >· срез</span>
                  </span>

                  <!-- Seminar — score / max + mark count in parens -->
                  <span v-if="statsFor(subject).seminar" class="flex items-baseline gap-1.5">
                    <span class="text-muted text-[0.78rem]">семинар</span>
                    <span class="font-mono text-ink">
                      {{ statsFor(subject).seminar!.average }}<template v-if="statsFor(subject).seminar!.max"
                        ><span class="text-muted-soft">/</span><span class="text-muted">{{ statsFor(subject).seminar!.max }}</span></template>
                    </span>
                    <span
                      v-if="statsFor(subject).seminar!.markCount"
                      class="text-muted text-[0.78rem]"
                    >
                      ({{ statsFor(subject).seminar!.markCount }} {{ pluralizeMarks(statsFor(subject).seminar!.markCount) }})
                    </span>
                  </span>

                  <!-- Current score -->
                  <span v-if="statsFor(subject).currentScore" class="flex items-baseline gap-1.5">
                    <span class="text-muted text-[0.78rem]">набрано</span>
                    <span class="font-mono text-ink">
                      {{ statsFor(subject).currentScore!.value }}<template v-if="statsFor(subject).currentScore!.max"
                        ><span class="text-muted-soft">/</span><span class="text-muted">{{ statsFor(subject).currentScore!.max }}</span></template>
                    </span>
                  </span>

                  <!-- Empty state -->
                  <span
                    v-if="
                      statsFor(subject).absencePercent === null &&
                      !statsFor(subject).seminar &&
                      !statsFor(subject).currentScore
                    "
                    class="text-muted text-[0.82rem]"
                  >
                    пока без оценок
                  </span>
                </div>
              </div>

              <!-- "Сегодня" badge — fixed-width slot so it lines up across rows -->
              <div class="w-[64px] sm:w-[78px] flex justify-end self-start pt-1 shrink-0">
                <span
                  v-if="hasClassToday(subject)"
                  class="text-[0.65rem] sm:text-micro font-mono uppercase tracking-wider text-bg bg-ink px-1.5 sm:px-2 py-0.5 sm:py-1 rounded-sm whitespace-nowrap"
                  title="Сегодня по этому предмету есть пара"
                >
                  сегодня
                </span>
              </div>

              <span
                class="font-mono text-micro text-muted-soft transition-all group-hover:text-ink self-start pt-1"
                :class="expanded.has(subject.id) ? 'rotate-90 text-ink' : ''"
                style="display: inline-block"
              >
                →
              </span>
            </div>
          </button>

          <!-- Expanded panel -->
          <div v-if="expanded.has(subject.id)" class="pb-10">
            <!-- Lesson type tabs (only those with real content) -->
            <div
              v-if="visibleLessonTypes(subject).length > 1"
              class="flex items-center gap-4 sm:gap-6 ml-0 sm:ml-12 mb-6 sm:mb-8 hairline-b pb-3 overflow-x-auto"
            >
              <button
                v-for="lt in visibleLessonTypes(subject)"
                :key="lt.lesson_type_id"
                class="pb-2 -mb-[13px] text-[0.9rem] tracking-tight whitespace-nowrap transition-colors cursor-pointer"
                :class="
                  (activeTab[subject.id] ?? visibleLessonTypes(subject)[0]?.lesson_type_id) === lt.lesson_type_id
                    ? 'text-ink border-b-2 border-accent'
                    : 'text-muted hover:text-ink border-b-2 border-transparent'
                "
                @click="setTab(subject.id, lt.lesson_type_id)"
              >
                {{ lessonTypeRu(lt.lesson_type_name, lt.lesson_type_id) }}
                <span v-if="lt.marks.length" class="font-mono text-[0.7rem] text-muted-soft ml-1.5">
                  {{ lt.marks.length }}
                </span>
              </button>
            </div>

            <!-- Single lesson type — show its name as a quiet eyebrow instead of a tab -->
            <div
              v-else-if="visibleLessonTypes(subject).length === 1"
              class="ml-0 sm:ml-12 mb-6 sm:mb-8 eyebrow"
            >
              {{ lessonTypeRu(
                visibleLessonTypes(subject)[0].lesson_type_name,
                visibleLessonTypes(subject)[0].lesson_type_id,
              ) }}
            </div>

            <!-- No content at all -->
            <div
              v-else
              class="ml-0 sm:ml-12 text-muted text-[0.9rem]"
            >
              Пока ничего не выставлено.
            </div>

            <div v-if="activeLessonType(subject)" class="ml-0 sm:ml-12 grid lg:grid-cols-[1.3fr_1fr] gap-10 lg:gap-12">
              <!-- Marks table -->
              <section>
                <div class="flex items-center gap-3 mb-4">
                  <span class="eyebrow">Отметки по датам</span>
                  <span class="hairline flex-1 border-t" />
                </div>

                <div v-if="!activeLessonType(subject)!.marks.length"
                  class="text-muted text-[0.9rem]">
                  Нет отметок.
                </div>

                <table v-else class="w-full">
                  <tbody>
                    <tr v-for="mark in sortedMarks(activeLessonType(subject)!.marks)" :key="mark.id"
                      class="hairline-b">
                      <td class="py-2.5 pr-4 align-top w-[5.5rem]">
                        <span class="font-mono text-[0.82rem] text-ink whitespace-nowrap">
                          {{ formatDate(parseISODate(mark.date), { withYear: false }) }}
                        </span>
                      </td>
                      <td class="py-2.5 pr-4 align-top text-[0.9rem] text-ink-soft leading-snug">
                        {{ mark.topic || '—' }}
                      </td>
                      <td class="py-2.5 align-top text-right whitespace-nowrap">
                        <MarkBadge :code="mark.mark_code" />
                      </td>
                    </tr>
                  </tbody>
                </table>
              </section>

              <!-- Final eval + Forma + extras -->
              <section class="space-y-10">
                <!-- Yekun -->
                <div v-if="nonEmptyEntries(activeLessonType(subject)!.final_eval).length">
                  <div class="flex items-center gap-3 mb-4">
                    <span class="eyebrow">Текущий итог</span>
                    <span class="hairline flex-1 border-t" />
                  </div>
                  <dl class="grid grid-cols-2 gap-x-6 gap-y-3">
                    <template
                      v-for="[k, v] in nonEmptyEntries(activeLessonType(subject)!.final_eval)"
                      :key="k"
                    >
                      <dt class="text-[0.82rem] text-muted leading-tight">{{ gradingFieldRu(k) }}</dt>
                      <dd class="font-mono text-[0.92rem] text-ink text-right tabular-nums">
                        {{ v }}
                      </dd>
                    </template>
                  </dl>
                </div>

                <!-- Forma (max scores schema) -->
                <div v-if="nonEmptyEntries(activeLessonType(subject)!.scheme).length">
                  <div class="flex items-center gap-3 mb-4">
                    <span class="eyebrow">Шкала максимума</span>
                    <span class="hairline flex-1 border-t" />
                  </div>
                  <dl class="grid grid-cols-2 gap-x-6 gap-y-2">
                    <template
                      v-for="[k, v] in nonEmptyEntries(activeLessonType(subject)!.scheme)"
                      :key="k"
                    >
                      <dt class="text-[0.78rem] text-muted-soft leading-tight">
                        {{ gradingFieldRu(k) }}
                      </dt>
                      <dd class="font-mono text-[0.85rem] text-ink-soft text-right tabular-nums">
                        {{ v }}
                      </dd>
                    </template>
                  </dl>
                </div>

                <!-- Course / independent / writing — show if non-empty -->
                <div
                  v-if="nonEmptyEntries(activeLessonType(subject)!.course_work).length"
                  class="text-[0.85rem] text-ink-soft"
                >
                  <span class="eyebrow block mb-2">Курсовая работа</span>
                  <dl class="grid grid-cols-2 gap-x-6 gap-y-2">
                    <template
                      v-for="[k, v] in nonEmptyEntries(activeLessonType(subject)!.course_work)"
                      :key="k"
                    >
                      <dt class="text-muted">{{ gradingFieldRu(k) }}</dt>
                      <dd class="font-mono text-right">{{ v }}</dd>
                    </template>
                  </dl>
                </div>
              </section>
            </div>

            <!-- Group name footnote -->
            <div
              v-if="subject.group_name"
              class="ml-0 sm:ml-12 mt-8 sm:mt-10 text-micro text-muted font-mono break-all"
            >
              {{ subject.group_name }}
            </div>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<script lang="ts">
import { pluralize } from '@/lib/locale'

function pluralizeSubjects(n: number): string {
  return pluralize(n, ['предмет', 'предмета', 'предметов'])
}
</script>
