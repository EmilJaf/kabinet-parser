<script setup lang="ts">
defineProps<{
  eyebrow?: string
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="px-5 sm:px-8 lg:px-12 pt-7 sm:pt-9 lg:pt-10 pb-6 lg:pb-8">
    <div v-if="eyebrow" class="eyebrow mb-3">{{ eyebrow }}</div>
    <div class="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 sm:gap-8">
      <h1
        class="text-[1.6rem] sm:text-display-lg font-medium text-ink leading-[1.15] sm:leading-[1.1] tracking-tight"
      >
        {{ title }}
      </h1>
      <div v-if="$slots.actions" class="flex items-center gap-3 flex-wrap">
        <slot name="actions" />
      </div>
    </div>
    <p v-if="subtitle" class="mt-3 text-ink-soft max-w-xl">{{ subtitle }}</p>
    <slot name="below" />
  </header>
</template>
