<script setup lang="ts">
withDefaults(
  defineProps<{
    height?: string
    width?: string
    rounded?: boolean
  }>(),
  {
    height: '1rem',
    width: '100%',
    rounded: false,
  },
)
</script>

<template>
  <span
    class="block bg-border/60 animate-pulse"
    :class="rounded ? 'rounded-full' : 'rounded-[2px]'"
    :style="{ height, width }"
    aria-hidden="true"
  />
</template>
