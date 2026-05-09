<script setup lang="ts">
import { ref, computed, onMounted, reactive, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { ExamOut, ExamQuestionsOut, ExamsOut } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/Skeleton.vue'
import FilterSelect from '@/components/FilterSelect.vue'
import ExamQuestionsPanel from '@/components/ExamQuestionsPanel.vue'
import { formatDate, parseISODate, relativeTime, shortTime } from '@/lib/time'
import { examFormRu, examGradeLabelRu, examTypeRu, semesterLabelRu } from '@/lib/locale'
import {
  EDU_YEAR_OPTIONS,
  EXAM_TYPE_OPTIONS,
  examTypeAzKey,
  type UnecOption,
} from '@/lib/unec'

const data = ref<ExamsOut | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref<string | null>(null)

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
const selectedExamTypeId = ref<number>(intFromQuery('type') ?? 0)
const availableSemesters = ref<UnecOption[]>([])

const semesterOptions = computed<UnecOption[]>(() =>
  availableSemesters.value.map((s) => ({ id: s.id, label: semesterLabelRu(s.label) })),
)

const lastSyncedRel = computed(() =>
  data.value?.last_synced_at ? relativeTime(new Date(data.value.last_synced_at)) : null,
)

let initialised = false

onMounted(async () => {
  if (selectedYearId.value != null) void loadSemesters(selectedYearId.value)
  await load()
  if (selectedYearId.value != null && availableSemesters.value.length === 0) {
    await loadSemesters(selectedYearId.value)
  }
  initialised = true
})

watch(selectedYearId, async (newYear, oldYear) => {
  if (!initialised || newYear === oldYear || newYear == null) return
  selectedSemesterId.value = null
  await loadSemesters(newYear)
  if (availableSemesters.value.length) {
    selectedSemesterId.value = availableSemesters.value[0].id
  }
})

watch(selectedSemesterId, async (newSem, oldSem) => {
  if (!initialised || newSem === oldSem) return
  await syncUrlAndReload()
})

watch(selectedExamTypeId, async (newType, oldType) => {
  if (!initialised || newType === oldType) return
  await syncUrlAndReload()
})

async function syncUrlAndReload() {
  await router.replace({
    query: {
      ...route.query,
      year: selectedYearId.value != null ? String(selectedYearId.value) : undefined,
      semester:
        selectedSemesterId.value != null ? String(selectedSemesterId.value) : undefined,
      type: selectedExamTypeId.value ? String(selectedExamTypeId.value) : undefined,
    },
  })
  await load()
}

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
  const p: Record<string, string | number> = {}
  if (selectedYearId.value != null) p.year_id = selectedYearId.value
  if (selectedSemesterId.value != null) p.semester_id = selectedSemesterId.value
  const azKey = examTypeAzKey(selectedExamTypeId.value)
  if (azKey) p.exam_type = azKey
  return p
}

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await api<ExamsOut>('/v1/exams', { query: buildParams() })
    if (data.value) {
      if (selectedYearId.value == null && data.value.edu_year_id != null) {
        selectedYearId.value = data.value.edu_year_id
      }
      if (selectedSemesterId.value == null && data.value.edu_semester_id != null) {
        selectedSemesterId.value = data.value.edu_semester_id
      }
    }
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string }; status?: number }
    if (err?.status === 409) {
      error.value = 'unec_creds_missing'
    } else if (err?.data?.detail === 'historical_years_unavailable') {
      error.value =
        'Кабинет UNEC не отдаёт результаты за прошлые годы по нашему запросу.'
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
    data.value = await api<ExamsOut>('/v1/exams/refresh', {
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

// Group exams by exam_type_name for editorial layout.
interface ExamGroup {
  type: string
  exams: ExamOut[]
}

const groupedExams = computed<ExamGroup[]>(() => {
  if (!data.value) return []
  const groups = new Map<string, ExamOut[]>()
  for (const e of data.value.exams) {
    if (!groups.has(e.exam_type_name)) groups.set(e.exam_type_name, [])
    groups.get(e.exam_type_name)!.push(e)
  }
  // Order: финальные сначала, потом промежуточные. Простая сортировка по name.
  return [...groups.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([type, exams]) => ({ type, exams }))
})

function gradeColor(letter: string | null): string {
  if (!letter) return 'text-ink'
  const map: Record<string, string> = {
    A: 'text-mark-positive font-semibold',
    B: 'text-mark-positive',
    C: 'text-ink',
    D: 'text-ink',
    E: 'text-mark-warning',
    F: 'text-mark-negative font-semibold',
  }
  return map[letter] ?? 'text-ink'
}

function pluralizeExams(n: number): string {
  const m10 = n % 10
  const m100 = n % 100
  if (m10 === 1 && m100 !== 11) return 'экзамен'
  if ([2, 3, 4].includes(m10) && ![12, 13, 14].includes(m100)) return 'экзамена'
  return 'экзаменов'
}

// Per-exam expansion state — one cache entry per exam_id.
interface QuestionsState {
  loading: boolean
  data: ExamQuestionsOut | null
  error: string | null
}

const expanded = reactive<Set<string>>(new Set())
const questionsCache = reactive<Record<string, QuestionsState>>({})

async function toggleExam(exam: ExamOut) {
  if (expanded.has(exam.id)) {
    expanded.delete(exam.id)
    return
  }
  expanded.add(exam.id)
  if (!questionsCache[exam.id]) {
    questionsCache[exam.id] = { loading: true, data: null, error: null }
    try {
      questionsCache[exam.id].data = await api<ExamQuestionsOut>(
        `/v1/exams/${exam.id}/questions`,
      )
    } catch (e: unknown) {
      const err = e as { data?: { detail?: string } }
      questionsCache[exam.id].error = err?.data?.detail ?? 'Не удалось загрузить вопросы.'
    } finally {
      questionsCache[exam.id].loading = false
    }
  }
}

function statusColor(status: 'correct' | 'wrong' | 'unknown'): string {
  if (status === 'correct') return 'bg-mark-positive'
  if (status === 'wrong') return 'bg-mark-negative'
  return 'bg-muted-soft'
}

function statusLabel(status: 'correct' | 'wrong' | 'unknown'): string {
  if (status === 'correct') return 'Правильно'
  if (status === 'wrong') return 'Неправильно'
  return '—'
}
</script>

<template>
  <div>
    <PageHeader eyebrow="Экзамены" title="Результаты сессий">
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
            label="семестр"
            :options="semesterOptions"
            :model-value="selectedSemesterId"
            @update:model-value="(v) => (selectedSemesterId = Number(v))"
          />
          <FilterSelect
            class="ml-auto mr-1 sm:ml-0 sm:mr-0"
            label="тип"
            :options="EXAM_TYPE_OPTIONS"
            :model-value="selectedExamTypeId"
            @update:model-value="(v) => (selectedExamTypeId = Number(v))"
          />
          <span
            v-if="data && !loading"
            class="text-muted text-[0.85rem] ml-auto hidden sm:inline"
          >
            {{ data.exams.length }} {{ pluralizeExams(data.exams.length) }}
          </span>
        </div>
      </template>
    </PageHeader>

    <div class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16">
      <!-- Error banner -->
      <div
        v-if="error && error !== 'unec_creds_missing' && data?.exams.length"
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
      <div v-if="loading" class="hairline-t pt-6 space-y-5">
        <div v-for="i in 5" :key="i" class="grid grid-cols-[1fr_auto] gap-4">
          <div>
            <Skeleton width="60%" height="1rem" />
            <Skeleton width="35%" height="0.78rem" class="mt-2" />
          </div>
          <Skeleton width="3rem" height="1.05rem" />
        </div>
      </div>

      <!-- No UNEC creds -->
      <div v-else-if="error === 'unec_creds_missing'" class="hairline-t pt-12 max-w-2xl">
        <div class="eyebrow mb-4">Нужно действие</div>
        <h2 class="text-display text-ink leading-tight mb-4">
          Сначала привяжите аккаунт UNEC
        </h2>
        <p class="text-ink-soft mb-8 max-w-lg">
          Без логина и пароля от
          <span class="font-mono text-[0.9em] bg-bg-deep px-1 rounded-sm">kabinet.unec.edu.az</span>
          мы не можем тянуть ваши экзамены.
        </p>
        <RouterLink :to="{ name: 'settings' }"
          class="inline-block bg-ink text-bg px-6 py-2.5 text-[0.9rem] hover:bg-ink-soft transition-colors">
          Перейти в настройки →
        </RouterLink>
      </div>

      <!-- Generic error -->
      <div v-else-if="error && !data?.exams.length" class="text-mark-negative">
        {{ error }}
      </div>

      <!-- Empty -->
      <div v-else-if="!data?.exams.length" class="text-muted hairline-t pt-12">
        В выбранном семестре нет результатов экзаменов.
      </div>

      <!-- Exam groups -->
      <div v-else class="space-y-12">
        <section v-for="group in groupedExams" :key="group.type">
          <div class="flex items-baseline gap-3 mb-4 hairline-b pb-3">
            <h2 class="text-[1.1rem] font-medium text-ink">
              {{ examTypeRu(group.type) }}
            </h2>
            <span class="text-muted text-[0.78rem] font-mono">
              {{ group.exams.length }}
            </span>
          </div>

          <!-- Desktop: table-aligned columns -->
          <table class="hidden sm:table w-full table-fixed border-collapse">
            <colgroup>
              <col />
              <col class="w-[5rem]" />
              <col class="w-[5rem]" />
              <col class="w-[7rem]" />
            </colgroup>
            <thead>
              <tr class="text-micro font-mono uppercase tracking-wider text-muted-soft">
                <th class="text-left font-normal pb-2"></th>
                <th class="text-right font-normal pb-2">До</th>
                <th class="text-right font-normal pb-2">Экзамен</th>
                <th class="text-right font-normal pb-2">Итог</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="exam in group.exams" :key="exam.id">
                <tr
                  class="hairline-b align-top cursor-pointer hover:bg-bg-deep/40 transition-colors"
                  @click="toggleExam(exam)"
                >
                  <td class="py-4 pr-4">
                    <div class="flex items-baseline gap-2">
                      <span
                        class="font-mono text-[0.7rem] text-muted-soft transition-transform inline-block"
                        :class="expanded.has(exam.id) ? 'rotate-90 text-ink' : ''"
                      >▶</span>
                      <div class="flex-1 min-w-0">
                        <div class="text-[0.95rem] text-ink leading-snug">
                          {{ exam.subject_name }}
                        </div>
                        <div class="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[0.78rem] text-muted">
                          <span v-if="exam.date" class="font-mono">
                            {{ formatDate(parseISODate(exam.date)) }}
                          </span>
                          <span v-if="exam.form">{{ examFormRu(exam.form) }}</span>
                          <span v-if="exam.start_time" class="font-mono text-muted-soft">
                            {{ shortTime(exam.start_time) }}
                          </span>
                        </div>
                      </div>
                    </div>
                  </td>

                  <td class="py-4 text-right font-mono tabular-nums text-[0.95rem]"
                      :class="exam.entry_score != null ? 'text-ink-soft' : 'text-muted-soft'">
                    {{ exam.entry_score ?? '—' }}
                  </td>

                  <td class="py-4 text-right font-mono tabular-nums text-[0.95rem]"
                      :class="exam.exam_score != null ? 'text-ink-soft' : 'text-muted-soft'">
                    {{ exam.exam_score ?? '—' }}
                  </td>

                  <td class="py-4 text-right whitespace-nowrap">
                    <template v-if="exam.final_score != null">
                      <span class="font-mono tabular-nums text-[1rem]"
                            :class="gradeColor(exam.grade_letter)">
                        {{ exam.final_score }}<span v-if="exam.grade_letter" class="ml-1">{{ exam.grade_letter }}</span>
                      </span>
                      <div v-if="exam.grade_label" class="text-[0.72rem] text-muted mt-0.5">
                        {{ examGradeLabelRu(exam.grade_label) }}
                      </div>
                    </template>
                    <span v-else class="text-muted-soft font-mono">—</span>
                  </td>
                </tr>

                <!-- Expanded questions panel — no horizontal padding so the
                     panel's grid can align directly with the parent columns. -->
                <tr v-if="expanded.has(exam.id)" class="hairline-b">
                  <td colspan="4" class="pb-6 pt-1">
                    <ExamQuestionsPanel
                      :state="questionsCache[exam.id]"
                      :exam-id="exam.id"
                      align-columns
                    />
                  </td>
                </tr>
              </template>
            </tbody>
          </table>

          <!-- Mobile: stacked rows, prominent grade on right -->
          <ul class="sm:hidden divide-y divide-border">
            <li
              v-for="exam in group.exams"
              :key="exam.id"
              class="py-4"
            >
              <div
                class="grid grid-cols-[1fr_auto] gap-x-4 items-baseline cursor-pointer"
                @click="toggleExam(exam)"
              >
              <div class="min-w-0">
                <div class="text-[0.95rem] text-ink leading-snug">
                  {{ exam.subject_name }}
                </div>
                <div class="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[0.75rem] text-muted">
                  <span v-if="exam.date" class="font-mono">
                    {{ formatDate(parseISODate(exam.date)) }}
                  </span>
                  <span v-if="exam.form">{{ examFormRu(exam.form) }}</span>
                </div>
                <div
                  v-if="exam.entry_score != null || exam.exam_score != null"
                  class="mt-1.5 flex items-baseline gap-3 text-[0.75rem] text-muted"
                >
                  <span v-if="exam.entry_score != null" class="flex items-baseline gap-1">
                    <span class="text-muted-soft">до</span>
                    <span class="font-mono tabular-nums text-ink-soft">{{ exam.entry_score }}</span>
                  </span>
                  <span v-if="exam.exam_score != null" class="flex items-baseline gap-1">
                    <span class="text-muted-soft">экз</span>
                    <span class="font-mono tabular-nums text-ink-soft">{{ exam.exam_score }}</span>
                  </span>
                </div>
              </div>

              <div class="text-right whitespace-nowrap">
                <template v-if="exam.final_score != null">
                  <span class="font-mono tabular-nums text-[1.05rem]"
                        :class="gradeColor(exam.grade_letter)">
                    {{ exam.final_score }}<span v-if="exam.grade_letter" class="ml-0.5">{{ exam.grade_letter }}</span>
                  </span>
                  <div v-if="exam.grade_label" class="text-[0.7rem] text-muted mt-0.5">
                    {{ examGradeLabelRu(exam.grade_label) }}
                  </div>
                </template>
                <span v-else class="text-muted-soft font-mono text-[0.95rem]">—</span>
              </div>
              </div>

              <!-- Mobile expanded panel -->
              <div v-if="expanded.has(exam.id)" class="mt-4">
                <ExamQuestionsPanel :state="questionsCache[exam.id]" :exam-id="exam.id" />
              </div>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>
