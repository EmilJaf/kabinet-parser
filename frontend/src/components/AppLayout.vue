<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterView, RouterLink, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()

const baseSections = [
  { name: 'dashboard', label: 'Сегодня', shortcut: 'Д' },
  { name: 'schedule', label: 'Расписание', shortcut: 'Р' },
  { name: 'grades', label: 'Журнал', shortcut: 'Ж' },
  { name: 'exams', label: 'Экзамены', shortcut: 'Э' },
  { name: 'files', label: 'Материалы', shortcut: 'М' },
  { name: 'settings', label: 'Настройки', shortcut: 'Н' },
]

const sections = computed(() => {
  if (auth.user?.is_admin) {
    return [...baseSections, { name: 'admin', label: 'Админка', shortcut: 'А' }]
  }
  return baseSections
})

const activeName = computed(() => route.name)
const userInitial = computed(() => (auth.user?.email ?? '?').slice(0, 1).toUpperCase())

// Mobile drawer state — sidebar slides in from the left.
const drawerOpen = ref(false)
watch(() => route.fullPath, () => (drawerOpen.value = false))
</script>

<template>
  <!-- On desktop the layout is a fixed-height app shell: page itself
       doesn't scroll, sidebar and main scroll independently inside their
       own boxes. On mobile we keep normal page scroll (so iOS Safari can
       hide/show its URL bar on swipe). -->
  <div class="flex bg-bg text-ink lg:h-screen lg:overflow-hidden">
    <!-- Backdrop — mobile only, dismisses the drawer on tap.
         Use top-0 + explicit height: 100dvh (dynamic viewport height — tracks
         iOS Safari's URL bar). inset-0 / inset-y-0 on a fixed element binds
         to the layout viewport, which is shorter than the visual viewport
         while the URL bar is showing — that's where the grey strip came from. -->
    <div
      v-if="drawerOpen"
      class="fixed inset-x-0 top-0 bg-ink/30 z-40 lg:hidden"
      style="height: 100dvh; padding-bottom: env(safe-area-inset-bottom)"
      @click="drawerOpen = false"
    />

    <!-- Sidebar — persistent on lg+, off-canvas drawer below.
         On lg+ aside is in flex flow with its own height (parent is h-screen)
         and overflows vertically inside itself if nav is taller than viewport,
         so the page never scrolls when the user spins the wheel over the nav. -->
    <aside
      class="hairline-r flex w-64 shrink-0 flex-col bg-bg-soft fixed top-0 left-0 z-50 transition-transform duration-200 ease-out lg:static lg:translate-x-0 lg:h-screen lg:overflow-y-auto"
      :class="drawerOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'"
      style="height: 100dvh; will-change: transform;"
    >
      <!-- Top padding matches the mobile top bar so the "Kabinet" brand sits
           at the same vertical position whether you're looking at the drawer
           or the closed-state top bar. On lg+ desktop the top bar is hidden,
           so we add a bit more breathing room there. -->
      <div
        class="px-7 pb-12 flex items-start justify-between lg:pt-9"
        style="padding-top: max(env(safe-area-inset-top), 0.75rem)"
      >
        <RouterLink :to="{ name: 'dashboard' }" class="inline-block">
          <span class="text-[1.35rem] font-semibold tracking-tight text-ink">Kabinet</span>
          <div class="eyebrow mt-1">UNEC</div>
        </RouterLink>
        <button
          class="lg:hidden -mr-2 -mt-1 p-2 text-muted hover:text-ink cursor-pointer"
          aria-label="Закрыть меню"
          @click="drawerOpen = false"
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path d="M4 4l10 10M14 4L4 14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </button>
      </div>

      <nav class="flex-1 px-3">
        <ul class="space-y-px">
          <li v-for="s in sections" :key="s.name">
            <RouterLink
              :to="{ name: s.name }"
              class="group flex items-center justify-between rounded-sm px-4 py-2.5 text-[0.95rem] transition-colors"
              :class="
                activeName === s.name
                  ? 'bg-bg-deep text-ink'
                  : 'text-ink-soft hover:bg-bg-soft hover:text-ink'
              "
            >
              <span class="flex items-center gap-3">
                <span
                  class="h-1 w-1 rounded-full transition-all"
                  :class="
                    activeName === s.name ? 'bg-ink w-3' : 'bg-muted-soft group-hover:bg-muted'
                  "
                />
                {{ s.label }}
              </span>
              <span class="font-mono text-[0.65rem] text-muted-soft hidden sm:inline">
                {{ s.shortcut }}
              </span>
            </RouterLink>
          </li>
        </ul>
      </nav>

      <!-- User block, footer -->
      <div
        class="hairline-t mt-4 px-7 pt-5"
        style="padding-bottom: max(env(safe-area-inset-bottom), 1.25rem)"
      >
        <div class="flex items-center gap-3">
          <div
            class="flex h-8 w-8 items-center justify-center rounded-full bg-ink text-bg text-[0.78rem] font-medium"
          >
            {{ userInitial }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[0.85rem] text-ink">
              {{ auth.user?.email ?? '—' }}
            </div>
            <button
              class="text-micro mt-0.5 text-muted hover:text-ink transition-colors cursor-pointer"
              @click="auth.logout()"
            >
              Выйти
            </button>
          </div>
        </div>
      </div>
    </aside>

    <!-- Main column. overflow-x-clip is a safety net — if any nested element
         accidentally overflows on mobile, we clip rather than introduce a
         page-level horizontal scrollbar.
         On lg+ this is its own vertical scroll container, separate from the
         sidebar — scrolling the wheel here moves only this column. -->
    <main class="flex-1 min-w-0 overflow-x-clip lg:h-screen lg:overflow-y-auto">
      <!-- Mobile top bar — hamburger + brand. Safe-area padding so the bar
           stays clear of the iOS status bar / dynamic island in standalone PWA. -->
      <div
        class="lg:hidden flex items-center gap-3 px-5 pb-3 hairline-b sticky top-0 bg-bg z-30"
        style="padding-top: max(env(safe-area-inset-top), 0.75rem)"
      >
        <button
          class="-ml-2 p-2 text-ink cursor-pointer"
          aria-label="Открыть меню"
          @click="drawerOpen = true"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
            <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
        </button>
        <span class="text-[1.05rem] font-semibold tracking-tight">Kabinet</span>
      </div>

      <RouterView v-slot="{ Component }">
        <Transition name="fade" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition:
    opacity 200ms ease,
    transform 200ms ease;
}
.fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.fade-leave-to {
  opacity: 0;
}
</style>
