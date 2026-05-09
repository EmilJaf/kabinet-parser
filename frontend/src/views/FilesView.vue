<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { api } from '@/api/client'
import type { FilesPageOut } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/Skeleton.vue'
import FilterSelect from '@/components/FilterSelect.vue'
import { relativeTime } from '@/lib/time'

const data = ref<FilesPageOut | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const eduYearId = ref<string>('')
const eduSemesterId = ref<string>('')
const subject = ref<string>('')
const subjId = ref<string>('')
const teacher = ref<string>('')

const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// UNEC ships labels in Azerbaijani — translate to keep the rest of the app
// consistently in Russian. Years already look like '2025 - 2026'; we just
// upgrade the dash.
function translateYear(label: string): string {
  return label.replace(' - ', ' — ')
}

const SEMESTER_RU: Record<string, string> = {
  'Yay semestri': 'Летний',
  'I semestr': 'I семестр',
  'II semestr': 'II семестр',
}
function translateSemester(label: string): string {
  return SEMESTER_RU[label.trim()] ?? label
}

// Subject labels are 'Title / 10_24_..._suffix' — keep the title only.
function shortSubject(label: string): string {
  return label.split(' / ')[0] || label
}

async function load(opts: { force?: boolean } = {}) {
  loading.value = true
  error.value = null
  try {
    const params: Record<string, string | boolean> = {}
    if (eduYearId.value) params.edu_year_id = eduYearId.value
    if (eduSemesterId.value) params.edu_semester_id = eduSemesterId.value
    if (subject.value) {
      params.subject = subject.value
      if (subjId.value) params.subj_id = subjId.value
    }
    if (teacher.value) params.teacher = teacher.value
    if (opts.force) params.force = true
    data.value = await api<FilesPageOut>('/v1/files', { query: params })

    if (!eduYearId.value && data.value.years.length) {
      const sel = data.value.years.find((y) => y.selected) ?? data.value.years[0]
      eduYearId.value = sel.value
    }
  } catch (e: unknown) {
    const err = e as { data?: { detail?: string }; status?: number }
    if (err?.data?.detail === 'unec_creds_missing') {
      error.value = 'unec_creds_missing'
    } else {
      error.value = 'Не удалось загрузить материалы.'
    }
  } finally {
    loading.value = false
  }
}

onMounted(load)

watch(eduYearId, () => {
  eduSemesterId.value = ''
  subject.value = ''
  subjId.value = ''
  teacher.value = ''
  void load()
})
watch(eduSemesterId, () => {
  subject.value = ''
  subjId.value = ''
  teacher.value = ''
  void load()
})
watch(subject, (val) => {
  const found = data.value?.subjects.find((s) => s.value === val)
  subjId.value = found?.subj_id ?? ''
  teacher.value = ''
  void load()
})
watch(teacher, () => void load())

const FILE_TYPES = [
  { key: 'lecture', label: 'Лекция', api: 'lection' },
  { key: 'presentation', label: 'Презентация', api: 'presentation' },
  { key: 'test', label: 'Тест', api: 'test' },
  { key: 'seminar', label: 'Семинар', api: 'seminar' },
  { key: 'other', label: 'Прочее', api: 'other' },
] as const

function downloadHref(themeId: string, fileType: string): string {
  return `${apiBase}/v1/files/download/${themeId}/${fileType}`
}

function syllabusHref(path: string): string {
  return `${apiBase}/v1/files/download-path?path=${encodeURIComponent(path)}`
}

const selectedTeacher = computed(() =>
  data.value?.teachers.find((t) => t.value === teacher.value) ?? null,
)

const yearOptions = computed(() =>
  (data.value?.years ?? []).map((o) => ({ id: o.value, label: translateYear(o.label) })),
)
const semesterOptions = computed(() =>
  (data.value?.semesters ?? []).map((o) => ({ id: o.value, label: translateSemester(o.label) })),
)
const subjectOptions = computed(() =>
  (data.value?.subjects ?? []).map((o) => ({ id: o.value, label: shortSubject(o.label) })),
)
const teacherOptions = computed(() =>
  (data.value?.teachers ?? []).map((o) => ({ id: o.value, label: o.name.trim() })),
)

const cachedAgo = computed(() =>
  data.value?.last_synced_at ? relativeTime(new Date(data.value.last_synced_at)) : null,
)
</script>

<template>
  <div>
    <PageHeader eyebrow="Материалы · 01" title="Файлы">
      <template #below>
        <p class="mt-4 max-w-xl text-ink-soft">
          Лекции, презентации, тесты и семинары по предметам из кабинета UNEC.
          Выбери год, семестр, предмет и преподавателя — потом скачивай прямо отсюда.
        </p>
      </template>
    </PageHeader>

    <div class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16">
      <!-- Cascading filters -->
      <section class="hairline-t pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">Фильтр</span>
          <span class="hairline flex-1 border-t" />
          <button
            v-if="data && teacher"
            type="button"
            :disabled="loading"
            class="text-micro font-mono uppercase tracking-wider px-3 py-1.5 hairline hover:bg-bg-deep cursor-pointer disabled:opacity-50"
            :title="
              cachedAgo
                ? `Из кеша (обновлено ${cachedAgo})`
                : 'Свежий запрос к UNEC'
            "
            @click="load({ force: true })"
          >
            {{ loading ? '…' : 'обновить' }}
          </button>
        </div>

        <div class="flex flex-wrap items-end gap-x-5 sm:gap-x-8 gap-y-5">
          <FilterSelect
            v-model="eduYearId"
            label="Год"
            :options="yearOptions"
            :disabled="!yearOptions.length"
          />
          <FilterSelect
            v-model="eduSemesterId"
            label="Семестр"
            :options="semesterOptions"
            :disabled="!semesterOptions.length"
          />
          <FilterSelect
            v-model="subject"
            label="Предмет"
            :options="subjectOptions"
            :disabled="!subjectOptions.length"
          />
          <FilterSelect
            v-model="teacher"
            label="Преподаватель"
            :options="teacherOptions"
            :disabled="!teacherOptions.length"
          />
        </div>
      </section>

      <!-- Syllabus quick-link -->
      <div v-if="selectedTeacher?.sylabus_path" class="mt-6">
        <a
          :href="syllabusHref(selectedTeacher.sylabus_path)"
          download
          class="text-[0.9rem] text-ink-soft hover:text-ink underline underline-offset-4 decoration-border"
        >
          Скачать силлабус →
        </a>
      </div>

      <!-- States -->
      <div v-if="error === 'unec_creds_missing'" class="hairline-t mt-12 pt-12 max-w-2xl">
        <div class="eyebrow mb-4">Нужно действие</div>
        <p class="text-ink leading-relaxed mb-2">
          Чтобы видеть материалы — подключи кабинет UNEC в настройках.
        </p>
      </div>

      <div v-else-if="error" class="text-mark-negative mt-12">{{ error }}</div>

      <div v-else-if="loading && !data" class="hairline-t mt-12 pt-8 space-y-3">
        <Skeleton v-for="i in 5" :key="i" width="100%" height="3rem" />
      </div>

      <!-- Themes — desktop table, mobile card list -->
      <section v-else-if="teacher && data?.themes.length" class="hairline-t mt-12 pt-8">
        <!-- Desktop table (sm+) -->
        <div class="hidden sm:block">
          <table class="w-full text-[0.9rem]">
            <thead>
              <tr class="text-micro font-mono uppercase tracking-wider text-muted-soft">
                <th class="text-left font-normal pb-3 px-2">№</th>
                <th class="text-left font-normal pb-3 px-2">Тема</th>
                <th
                  v-for="ft in FILE_TYPES"
                  :key="ft.key"
                  class="text-center font-normal pb-3 px-2 whitespace-nowrap"
                >
                  {{ ft.label }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(t, i) in data.themes"
                :key="t.theme_id"
                class="hairline-t hover:bg-bg-deep/40"
              >
                <td class="py-3 px-2 font-mono text-micro text-muted tabular-nums align-top w-10">
                  {{ i + 1 }}
                </td>
                <td class="py-3 px-2 align-top text-ink">
                  {{ t.topic }}
                </td>
                <td
                  v-for="ft in FILE_TYPES"
                  :key="ft.key"
                  class="py-3 px-2 text-center align-top w-20"
                >
                  <a
                    v-if="(t as any)[`has_${ft.key}`]"
                    :href="downloadHref(t.theme_id, ft.api)"
                    download
                    :title="`Скачать: ${ft.label}`"
                    class="inline-flex items-center justify-center text-ink hover:text-mark-positive cursor-pointer"
                  >
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <path
                        d="M8 1.5v8.5m0 0L4.5 6.75M8 10l3.5-3.25M2 12.5h12"
                        stroke="currentColor"
                        stroke-width="1.4"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </a>
                  <span v-else class="text-muted-soft">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Mobile cards (< sm) -->
        <ul class="sm:hidden hairline-t">
          <li
            v-for="(t, i) in data.themes"
            :key="t.theme_id"
            class="hairline-b py-4"
          >
            <div class="flex items-baseline gap-3 mb-2.5">
              <span class="font-mono text-micro text-muted-soft tabular-nums shrink-0 w-6">
                {{ String(i + 1).padStart(2, '0') }}
              </span>
              <span class="text-[0.95rem] text-ink leading-snug">{{ t.topic }}</span>
            </div>
            <div class="flex flex-wrap gap-2 pl-9">
              <template v-for="ft in FILE_TYPES" :key="ft.key">
                <a
                  v-if="(t as any)[`has_${ft.key}`]"
                  :href="downloadHref(t.theme_id, ft.api)"
                  download
                  class="inline-flex items-center gap-1.5 text-micro hairline rounded-sm px-2.5 py-1.5 text-ink-soft hover:text-ink hover:bg-bg-deep cursor-pointer"
                >
                  <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                    <path
                      d="M8 1.5v8.5m0 0L4.5 6.75M8 10l3.5-3.25M2 12.5h12"
                      stroke="currentColor"
                      stroke-width="1.6"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  {{ ft.label }}
                </a>
              </template>
            </div>
          </li>
        </ul>
      </section>

      <div
        v-else-if="teacher && data && !data.themes.length"
        class="hairline-t mt-12 pt-12 text-muted"
      >
        Нет материалов.
      </div>

      <div v-else-if="!teacher" class="hairline-t mt-12 pt-12 text-muted">
        Выбери все 4 фильтра выше, чтобы увидеть список тем.
      </div>
    </div>
  </div>
</template>
