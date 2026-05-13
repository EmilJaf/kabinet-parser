<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { FilesPageOut } from '@/api/types'
import PageHeader from '@/components/PageHeader.vue'
import Skeleton from '@/components/Skeleton.vue'
import FilterSelect from '@/components/FilterSelect.vue'
import { semesterLabelRu } from '@/lib/locale'
import { relativeTime } from '@/lib/time'

const { t } = useI18n()

const data = ref<FilesPageOut | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

const eduYearId = ref<string>('')
const eduSemesterId = ref<string>('')
const subject = ref<string>('')
const subjId = ref<string>('')
const teacher = ref<string>('')

const apiBase = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Years already look like "2025 - 2026"; we just upgrade the dash.
function translateYear(label: string): string {
  return label.replace(' - ', ' — ')
}

function translateSemester(label: string): string {
  // "Yay semestri" gets a friendlier short form; everything else uses the
  // shared UNEC catalog ("I semestr" → "I семестр" etc).
  if (label.trim() === 'Yay semestri') return t('files.summer')
  return semesterLabelRu(label)
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
      error.value = t('files.errLoad')
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

// File-type keys map 1:1 to backend `/files/download/<theme>/<api>` slugs.
// Labels are pulled from the i18n catalog at render time via t('files.kinds.<key>').
const FILE_TYPES = [
  { key: 'lecture', api: 'lection' },
  { key: 'presentation', api: 'presentation' },
  { key: 'test', api: 'test' },
  { key: 'seminar', api: 'seminar' },
  { key: 'other', api: 'other' },
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
    <PageHeader :eyebrow="t('files.eyebrow')" :title="t('files.title')">
      <template #below>
        <p class="mt-4 max-w-xl text-ink-soft">
          {{ t('files.intro1') }}
          {{ t('files.intro2') }}
        </p>
      </template>
    </PageHeader>

    <div class="px-6 sm:px-8 lg:px-12 pb-12 lg:pb-16">
      <!-- Cascading filters -->
      <section class="hairline-t pt-8">
        <div class="flex items-center gap-3 mb-6">
          <span class="eyebrow">{{ t('files.filter') }}</span>
          <span class="hairline flex-1 border-t" />
          <button
            v-if="data && teacher"
            type="button"
            :disabled="loading"
            class="text-micro font-mono uppercase tracking-wider px-3 py-1.5 hairline hover:bg-bg-deep cursor-pointer disabled:opacity-50"
            :title="
              cachedAgo
                ? t('files.fromCache', { ago: cachedAgo })
                : t('files.freshFromUnec')
            "
            @click="load({ force: true })"
          >
            {{ loading ? '…' : t('common.refresh') }}
          </button>
        </div>

        <div class="flex flex-wrap items-end gap-x-5 sm:gap-x-8 gap-y-5">
          <FilterSelect
            v-model="eduYearId"
            :label="t('files.yearLabel')"
            :options="yearOptions"
            :disabled="!yearOptions.length"
          />
          <FilterSelect
            v-model="eduSemesterId"
            :label="t('files.semesterLabel')"
            :options="semesterOptions"
            :disabled="!semesterOptions.length"
          />
          <FilterSelect
            v-model="subject"
            :label="t('files.subjectLabel')"
            :options="subjectOptions"
            :disabled="!subjectOptions.length"
          />
          <FilterSelect
            v-model="teacher"
            :label="t('files.teacherLabel')"
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
          {{ t('files.downloadSyllabus') }}
        </a>
      </div>

      <!-- States -->
      <div v-if="error === 'unec_creds_missing'" class="hairline-t mt-12 pt-12 max-w-2xl">
        <div class="eyebrow mb-4">{{ t('common.actionRequired') }}</div>
        <p class="text-ink leading-relaxed mb-2">
          {{ t('files.linkUnec') }}
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
                <th class="text-left font-normal pb-3 px-2">{{ t('files.topic') }}</th>
                <th
                  v-for="ft in FILE_TYPES"
                  :key="ft.key"
                  class="text-center font-normal pb-3 px-2 whitespace-nowrap"
                >
                  {{ t(`files.kinds.${ft.key}`) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(theme, i) in data.themes"
                :key="theme.theme_id"
                class="hairline-t hover:bg-bg-deep/40"
              >
                <td class="py-3 px-2 font-mono text-micro text-muted tabular-nums align-top w-10">
                  {{ i + 1 }}
                </td>
                <td class="py-3 px-2 align-top text-ink">
                  {{ theme.topic }}
                </td>
                <td
                  v-for="ft in FILE_TYPES"
                  :key="ft.key"
                  class="py-3 px-2 text-center align-top w-20"
                >
                  <a
                    v-if="(theme as any)[`has_${ft.key}`]"
                    :href="downloadHref(theme.theme_id, ft.api)"
                    download
                    :title="t('files.downloadAlt', { kind: t(`files.kinds.${ft.key}`) })"
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
            v-for="(theme, i) in data.themes"
            :key="theme.theme_id"
            class="hairline-b py-4"
          >
            <div class="flex items-baseline gap-3 mb-2.5">
              <span class="font-mono text-micro text-muted-soft tabular-nums shrink-0 w-6">
                {{ String(i + 1).padStart(2, '0') }}
              </span>
              <span class="text-[0.95rem] text-ink leading-snug">{{ theme.topic }}</span>
            </div>
            <div class="flex flex-wrap gap-2 pl-9">
              <template v-for="ft in FILE_TYPES" :key="ft.key">
                <a
                  v-if="(theme as any)[`has_${ft.key}`]"
                  :href="downloadHref(theme.theme_id, ft.api)"
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
                  {{ t(`files.kinds.${ft.key}`) }}
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
        {{ t('files.noMaterials') }}
      </div>

      <div v-else-if="!teacher" class="hairline-t mt-12 pt-12 text-muted">
        {{ t('files.selectAllFilters') }}
      </div>
    </div>
  </div>
</template>
