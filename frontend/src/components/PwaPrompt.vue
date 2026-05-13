<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { usePwa } from '@/composables/usePwa'

const { t } = useI18n()
const { canInstall, showIosHint, promptInstall, dismissInstall, needRefresh, applyUpdate } =
  usePwa()
</script>

<template>
  <!-- Install prompt — bottom-center pill on mobile, hidden on lg desktop. -->
  <Transition name="lift">
    <div
      v-if="canInstall || showIosHint"
      class="fixed inset-x-0 z-50 mx-auto flex max-w-sm items-center gap-3 rounded-md bg-ink px-4 py-3 text-bg shadow-lg"
      style="bottom: calc(env(safe-area-inset-bottom) + 5rem)"
    >
      <div class="flex h-7 w-7 items-center justify-center rounded bg-bg text-ink text-[0.85rem] font-semibold">
        K
      </div>
      <div class="min-w-0 flex-1 text-[0.82rem] leading-snug">
        <div class="font-medium">{{ t('pwa.installTitle') }}</div>
        <div v-if="canInstall" class="text-bg/70 mt-0.5">
          {{ t('pwa.installDesc') }}
        </div>
        <div v-else class="text-bg/70 mt-0.5">
          {{ t('pwa.iosShare') }}
        </div>
      </div>
      <button
        v-if="canInstall"
        class="shrink-0 rounded-sm bg-bg px-3 py-1.5 text-[0.78rem] font-medium text-ink hover:bg-bg/90 cursor-pointer"
        @click="promptInstall"
      >
        {{ t('pwa.install') }}
      </button>
      <button
        class="shrink-0 -mr-1 p-1.5 text-bg/60 hover:text-bg cursor-pointer"
        :aria-label="t('pwa.hide')"
        @click="dismissInstall"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <path d="M3 3l8 8M11 3L3 11" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
      </button>
    </div>
  </Transition>

  <!-- Update toast — appears when a fresh SW has installed. -->
  <Transition name="lift">
    <div
      v-if="needRefresh"
      class="fixed inset-x-0 bottom-3 z-50 mx-auto flex max-w-sm items-center gap-3 rounded-md bg-bg-soft px-4 py-3 hairline shadow-lg sm:bottom-5"
    >
      <div class="min-w-0 flex-1 text-[0.82rem] text-ink">
        {{ t('pwa.newVersion') }}
      </div>
      <button
        class="shrink-0 rounded-sm bg-ink px-3 py-1.5 text-[0.78rem] font-medium text-bg hover:bg-ink/90 cursor-pointer"
        @click="applyUpdate"
      >
        {{ t('pwa.update') }}
      </button>
    </div>
  </Transition>
</template>

<style scoped>
.lift-enter-active,
.lift-leave-active {
  transition:
    opacity 220ms ease,
    transform 220ms ease;
}
.lift-enter-from,
.lift-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
