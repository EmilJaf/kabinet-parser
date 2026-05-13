<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  code: string | null
}>()

type Kind = 'positive' | 'negative' | 'numeric' | 'neutral' | 'empty'

const kind = computed<Kind>(() => {
  if (!props.code || props.code.trim() === '') return 'empty'
  const c = props.code.trim().toLowerCase()
  if (c === 'i/e' || c === 'i/e/' || c === 'iştirak') return 'positive'
  if (c === 'q/b' || c === 'q/b/' || c === 'qaib') return 'negative'
  if (/^\d+([.,]\d+)?$/.test(c)) return 'numeric'
  return 'neutral'
})

const tooltip = computed(() => {
  if (kind.value === 'positive') return `iştirak edib · ${t('markBadge.presentRu')}`
  if (kind.value === 'negative') return `qaib · ${t('markBadge.absentRu')}`
  return ''
})

const display = computed(() => {
  if (kind.value === 'empty') return '—'
  return props.code!.trim()
})
</script>

<template>
  <span
    class="inline-block font-mono text-[0.85rem]"
    :class="{
      'text-mark-positive border-b border-mark-positive/60': kind === 'positive',
      'text-mark-negative border-b border-mark-negative/60': kind === 'negative',
      'text-ink font-medium': kind === 'numeric',
      'text-ink-soft': kind === 'neutral',
      'text-muted-soft': kind === 'empty',
    }"
    :title="tooltip"
  >
    {{ display }}
  </span>
</template>
