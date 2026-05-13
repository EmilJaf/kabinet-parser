<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { ExamQuestionDetailOut, ExamQuestionsOut } from '@/api/types'
import Skeleton from './Skeleton.vue'
import ExamQuestionDetail from './ExamQuestionDetail.vue'

const { t } = useI18n()

function statusTitle(status: 'correct' | 'wrong' | 'unknown'): string {
  if (status === 'correct') return t('examQuestion.correctTooltip')
  if (status === 'wrong') return t('examQuestion.wrongTooltip')
  return t('examQuestion.blankTooltip')
}

interface QuestionsState {
  loading: boolean
  data: ExamQuestionsOut | null
  error: string | null
}

interface DetailState {
  loading: boolean
  data: ExamQuestionDetailOut | null
  error: string | null
}

const props = withDefaults(
  defineProps<{
    state: QuestionsState | undefined
    examId: string
    /** When true (desktop in ExamsView), question rows use a 1fr/5rem/5rem/7rem
     * grid that mirrors the parent exam table — score column lines up with
     * the parent's "Итог" column. */
    alignColumns?: boolean
  }>(),
  { alignColumns: false },
)

const expandedQuestion = reactive<Set<number>>(new Set())
const detailCache = reactive<Record<number, DetailState>>({})

const summary = computed(() => {
  const d = props.state?.data
  if (!d) return null
  const total = d.correct_count + d.wrong_count + d.unknown_count
  return { total, correct: d.correct_count, wrong: d.wrong_count }
})

async function toggleQuestion(qid: number) {
  if (expandedQuestion.has(qid)) {
    expandedQuestion.delete(qid)
    return
  }
  expandedQuestion.add(qid)
  if (!detailCache[qid]) {
    detailCache[qid] = { loading: true, data: null, error: null }
    try {
      detailCache[qid].data = await api<ExamQuestionDetailOut>(
        `/v1/exams/${props.examId}/questions/${qid}`,
      )
    } catch (e: unknown) {
      const err = e as { data?: { detail?: string } }
      detailCache[qid].error = err?.data?.detail ?? t('examQuestion.loadDetailsFailed')
    } finally {
      detailCache[qid].loading = false
    }
  }
}

function statusDot(status: 'correct' | 'wrong' | 'unknown'): string {
  if (status === 'correct') return 'bg-mark-positive'
  if (status === 'wrong') return 'bg-mark-negative'
  return 'bg-muted-soft'
}
</script>

<template>
  <div v-if="!state || state.loading" class="space-y-2 pt-2">
    <div v-for="i in 4" :key="i" class="flex items-baseline gap-3">
      <Skeleton width="0.4rem" height="0.4rem" rounded />
      <Skeleton width="60%" height="0.85rem" />
    </div>
  </div>

  <div v-else-if="state.error" class="text-mark-negative text-[0.85rem] pt-2">
    {{ state.error }}
  </div>

  <div v-else-if="state.data && !state.data.available" class="text-muted text-[0.85rem] pt-2">
    {{ t('examQuestion.noDetails') }}
    <span class="block text-micro text-muted-soft mt-1">
      {{ t('examQuestion.noDetailsHint') }}
    </span>
  </div>

  <div v-else-if="state.data && !state.data.questions.length" class="text-muted text-[0.85rem] pt-2">
    {{ t('examQuestion.noQuestions') }}
  </div>

  <div v-else-if="state.data" class="pt-2">
    <!-- Summary line -->
    <div class="flex items-baseline gap-4 text-[0.82rem] text-muted mb-3 flex-wrap">
      <span class="flex items-baseline gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full bg-mark-positive inline-block" />
        <span class="font-mono tabular-nums text-ink">{{ summary!.correct }}</span>
        {{ t('examQuestion.right') }}
      </span>
      <span class="flex items-baseline gap-1.5">
        <span class="w-1.5 h-1.5 rounded-full bg-mark-negative inline-block" />
        <span class="font-mono tabular-nums text-ink">{{ summary!.wrong }}</span>
        {{ t('examQuestion.wrong') }}
      </span>
      <span class="text-muted-soft">{{ t('examQuestion.outOf') }} <span class="font-mono">{{ summary!.total }}</span></span>
    </div>

    <!-- Questions list -->
    <ul class="space-y-1">
      <li v-for="q in state.data.questions" :key="q.question_id">
        <button
          class="w-full text-left py-1 hover:bg-bg-deep/40 transition-colors cursor-pointer items-baseline text-[0.85rem]"
          :class="alignColumns
            ? 'grid grid-cols-[1fr_5rem_5rem_7rem] gap-0 sm:grid'
            : 'grid grid-cols-[1.5rem_0.5rem_1fr_auto] gap-x-2.5'"
          @click="toggleQuestion(q.question_id)"
        >
          <!-- Aligned-columns mode (desktop, mirrors parent exam table) -->
          <template v-if="alignColumns">
            <div class="flex items-baseline gap-2.5 min-w-0">
              <span class="font-mono text-[0.75rem] text-muted-soft tabular-nums w-6 text-right shrink-0">
                {{ q.index }}
              </span>
              <span
                class="w-1.5 h-1.5 rounded-full mt-1 shrink-0"
                :class="statusDot(q.status)"
                :title="statusTitle(q.status)"
              />
              <span class="text-ink-soft leading-snug min-w-0">{{ q.text }}</span>
            </div>
            <!-- spacer matching parent's "До" column -->
            <div></div>
            <!-- score column — aligns with parent's "Экзамен" -->
            <div class="text-right whitespace-nowrap font-mono tabular-nums text-[0.95rem]"
                 :class="q.score !== null ? 'text-ink-soft' : 'text-muted-soft'">
              {{ q.score ?? '—' }}
            </div>
            <!-- spacer matching parent's "Итог" column -->
            <div></div>
          </template>

          <!-- Compact mode (mobile or non-aligned contexts) -->
          <template v-else>
            <span class="font-mono text-[0.75rem] text-muted-soft tabular-nums text-right">
              {{ q.index }}
            </span>
            <span
              class="w-1.5 h-1.5 rounded-full mt-1"
              :class="statusDot(q.status)"
              :title="statusTitle(q.status)"
            />
            <span class="text-ink-soft leading-snug min-w-0">{{ q.text }}</span>
            <span
              v-if="q.score !== null"
              class="font-mono tabular-nums text-[0.9rem] text-ink-soft pl-3 whitespace-nowrap"
            >
              {{ q.score }}
            </span>
          </template>
        </button>

        <!-- Question detail (lazy-loaded) -->
        <div v-if="expandedQuestion.has(q.question_id)" class="ml-[2rem] mt-2 mb-4">
          <ExamQuestionDetail :state="detailCache[q.question_id]" />
        </div>
      </li>
    </ul>
  </div>
</template>
