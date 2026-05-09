<script setup lang="ts">
import type { ExamQuestionDetailOut } from '@/api/types'
import Skeleton from './Skeleton.vue'
import UnecImage from './UnecImage.vue'

interface DetailState {
  loading: boolean
  data: ExamQuestionDetailOut | null
  error: string | null
}

defineProps<{
  state: DetailState | undefined
}>()
</script>

<template>
  <div
    v-if="!state || state.loading"
    class="hairline-l border-l-2 border-border pl-4 py-2 space-y-2"
  >
    <Skeleton width="80%" height="0.9rem" />
    <Skeleton width="60%" height="0.85rem" />
    <Skeleton width="180px" height="120px" />
  </div>

  <div
    v-else-if="state.error"
    class="hairline-l border-l-2 border-mark-negative/40 pl-4 py-2 text-mark-negative text-[0.85rem]"
  >
    {{ state.error }}
  </div>

  <div
    v-else-if="state.data"
    class="border-l-2 border-border pl-4 py-2 space-y-3 text-[0.85rem]"
  >
    <!-- Question text + image (MCQ usually has both) -->
    <div v-if="state.data.question_text" class="text-ink leading-snug">
      {{ state.data.question_text }}
    </div>
    <UnecImage
      v-if="state.data.question_image_path"
      :src="state.data.question_image_path"
      alt="Вопрос"
      silent
    />

    <!-- ── MCQ branch ────────────────────────────────────────────────── -->
    <ul v-if="state.data.kind === 'mcq' && state.data.options.length" class="space-y-1.5">
      <li
        v-for="(opt, i) in state.data.options"
        :key="i"
        class="flex items-start gap-3 py-1.5 px-2 rounded-sm"
        :class="{
          'bg-mark-positive/8 ring-1 ring-mark-positive/30': opt.is_correct,
          'bg-mark-negative/8': opt.is_user_choice && !opt.is_correct,
        }"
      >
        <span
          class="mt-1 w-3 h-3 rounded-full border flex-shrink-0"
          :class="opt.is_correct
            ? 'border-mark-positive bg-mark-positive'
            : opt.is_user_choice
              ? 'border-mark-negative bg-mark-negative'
              : 'border-border'"
        />
        <div class="min-w-0 flex-1">
          <div class="text-ink-soft leading-snug">{{ opt.text }}</div>
          <UnecImage v-if="opt.image_path" :src="opt.image_path" class="mt-2" silent />
          <div
            v-if="opt.is_correct || opt.is_user_choice"
            class="mt-1 flex gap-2 text-micro font-mono uppercase tracking-wider"
          >
            <span v-if="opt.is_correct" class="text-mark-positive">правильный</span>
            <span v-if="opt.is_user_choice" class="text-mark-negative">ваш выбор</span>
          </div>
        </div>
      </li>
    </ul>

    <!-- ── Written branch ────────────────────────────────────────────── -->
    <template v-if="state.data.kind === 'written'">
      <div
        v-if="state.data.difficulty || state.data.score != null"
        class="flex items-baseline gap-4 text-[0.78rem] text-muted"
      >
        <span v-if="state.data.difficulty">
          сложность <span class="text-ink-soft">{{ state.data.difficulty }}</span>
        </span>
        <span v-if="state.data.score != null">
          балл
          <span class="font-mono tabular-nums text-ink ml-1">{{ state.data.score }}</span>
        </span>
      </div>

      <div v-if="state.data.answer_images.length" class="space-y-3 mt-2">
        <div class="eyebrow">Ответ</div>
        <div class="flex flex-wrap gap-3">
          <UnecImage
            v-for="(img, i) in state.data.answer_images"
            :key="i"
            :src="img"
            alt="Сканированный ответ"
            class="max-w-[280px]"
            zoomable
          />
        </div>
      </div>

      <div v-if="state.data.comment" class="text-[0.82rem] text-ink-soft italic">
        <span class="text-muted not-italic">Комментарий:</span> {{ state.data.comment }}
      </div>
    </template>

    <div
      v-if="state.data.kind === 'unknown'"
      class="text-muted text-[0.82rem]"
    >
      Не удалось распарсить детали.
    </div>
  </div>
</template>
