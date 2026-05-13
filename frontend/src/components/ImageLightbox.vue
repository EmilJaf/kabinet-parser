<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  open: boolean
  src: string | null
  alt?: string
}>()

const emit = defineEmits<{ close: [] }>()

const zoomed = ref(false)

function close() {
  emit('close')
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}

watch(
  () => props.open,
  (open) => {
    zoomed.value = false
    if (open) {
      document.body.style.overflow = 'hidden'
      document.addEventListener('keydown', onKey)
    } else {
      document.body.style.overflow = ''
      document.removeEventListener('keydown', onKey)
    }
  },
)

onUnmounted(() => {
  document.body.style.overflow = ''
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="lightbox">
      <div
        v-if="open && src"
        class="fixed inset-0 z-[1000] bg-ink/90 flex items-center justify-center p-4 overflow-auto cursor-zoom-out"
        @click.self="close"
      >
        <button
          class="fixed top-4 right-4 z-10 w-9 h-9 flex items-center justify-center bg-bg/10 text-bg hover:bg-bg/20 rounded-full transition-colors cursor-pointer"
          :aria-label="t('imageLightbox.close')"
          @click="close"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M4 4l10 10M14 4L4 14" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" />
          </svg>
        </button>

        <img
          :src="src"
          :alt="alt"
          :class="zoomed ? 'cursor-zoom-out' : 'cursor-zoom-in'"
          class="max-w-none transition-transform duration-200 select-none"
          :style="zoomed
            ? { width: 'auto', maxWidth: 'none', maxHeight: 'none' }
            : { maxWidth: '95vw', maxHeight: '90vh' }"
          @click.stop="zoomed = !zoomed"
          draggable="false"
        />

        <div
          v-if="zoomed"
          class="fixed bottom-4 left-1/2 -translate-x-1/2 text-bg/70 text-micro font-mono uppercase tracking-wider"
        >
          {{ t('imageLightbox.clickToShrink') }}
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.lightbox-enter-active,
.lightbox-leave-active {
  transition:
    opacity 180ms ease,
    transform 180ms ease;
}
.lightbox-enter-from,
.lightbox-leave-to {
  opacity: 0;
}
</style>
