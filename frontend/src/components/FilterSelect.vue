<script setup lang="ts" generic="T extends string | number">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { UnecOption } from '@/lib/unec'

const props = defineProps<{
  label: string
  options: UnecOption<T>[]
  modelValue: T | null | undefined
  // When true the trigger is dimmed and clicks are ignored. Useful for
  // cascading filters where downstream selectors must show but stay
  // unusable until upstream is picked.
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: T]
}>()

const open = ref(false)
const triggerRef = ref<HTMLButtonElement | null>(null)
const panelRef = ref<HTMLDivElement | null>(null)

const selected = computed(
  () => props.options.find((o) => o.id === props.modelValue) ?? null,
)

function toggle() {
  if (props.disabled) return
  open.value = !open.value
}

function pick(opt: UnecOption<T>) {
  emit('update:modelValue', opt.id)
  open.value = false
  triggerRef.value?.focus()
}

function onPointerDown(e: PointerEvent) {
  if (!open.value) return
  const target = e.target as Node
  if (
    triggerRef.value &&
    !triggerRef.value.contains(target) &&
    panelRef.value &&
    !panelRef.value.contains(target)
  ) {
    open.value = false
  }
}

function onKeydown(e: KeyboardEvent) {
  if (!open.value) return
  if (e.key === 'Escape') {
    open.value = false
    triggerRef.value?.focus()
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="relative">
    <!-- Trigger — looks like an underlined inline label/value pair -->
    <button
      ref="triggerRef"
      type="button"
      :disabled="disabled"
      class="group flex items-baseline gap-2 text-left disabled:cursor-not-allowed disabled:opacity-40"
      :class="disabled ? '' : 'cursor-pointer'"
      :aria-expanded="open"
      aria-haspopup="listbox"
      @click="toggle"
    >
      <span class="text-muted text-[0.78rem]">{{ label }}</span>
      <span
        class="flex items-baseline gap-1.5 border-b transition-colors py-1"
        :class="
          disabled
            ? 'border-border'
            : open
              ? 'border-ink'
              : 'border-border group-hover:border-ink'
        "
      >
        <span class="font-mono text-ink text-[0.9rem] whitespace-nowrap">
          {{ selected?.label ?? '—' }}
        </span>
        <svg
          width="9" height="9" viewBox="0 0 9 9" fill="none"
          class="text-muted transition-transform translate-y-[-1px]"
          :class="open ? 'rotate-180' : ''"
          aria-hidden="true"
        >
          <path d="M1.5 3.25L4.5 6.25L7.5 3.25" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </span>
    </button>

    <!-- Panel -->
    <Transition name="dropdown">
      <div
        v-if="open"
        ref="panelRef"
        class="absolute z-30 mt-1.5 left-0 min-w-full bg-bg border border-border rounded-sm shadow-[0_4px_24px_-8px_rgba(0,0,0,0.15)] max-h-[280px] overflow-y-auto py-1"
        role="listbox"
      >
        <button
          v-for="opt in options"
          :key="opt.id"
          type="button"
          role="option"
          :aria-selected="opt.id === modelValue"
          class="w-full flex items-center gap-3 px-3 py-2 text-left text-[0.88rem] cursor-pointer transition-colors hover:bg-bg-deep"
          :class="opt.id === modelValue ? 'text-ink' : 'text-ink-soft'"
          @click="pick(opt)"
        >
          <span class="font-mono whitespace-nowrap">{{ opt.label }}</span>
          <svg
            v-if="opt.id === modelValue"
            width="12" height="12" viewBox="0 0 12 12" fill="none"
            class="ml-auto text-ink shrink-0"
            aria-hidden="true"
          >
            <path d="M2 6.5L4.5 9L10 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.dropdown-enter-active,
.dropdown-leave-active {
  transition:
    opacity 140ms ease,
    transform 140ms ease;
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}
</style>
