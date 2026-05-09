<script setup lang="ts">
import { RouterView } from 'vue-router'
import PwaPrompt from '@/components/PwaPrompt.vue'
import { useTheme } from '@/composables/useTheme'

// Initialise the theme system once at app root so the watcher and the
// system-preference media listener are active for the whole session.
useTheme()
</script>

<template>
  <RouterView />
  <PwaPrompt />
</template>
