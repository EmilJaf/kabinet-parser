<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { apiBlob } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import Skeleton from './Skeleton.vue'
import ImageLightbox from './ImageLightbox.vue'

const props = withDefaults(
  defineProps<{
    /** Either a UNEC ftp_path ("/ASEU/...") or a popup img src
     *  ("/az/img/8267720" / "/az/getImage?ftp_path=/ASEU/..."). */
    src: string
    alt?: string
    /** When true, clicking the image opens a fullscreen lightbox. */
    zoomable?: boolean
    /** When true, render nothing on error (404 / blob fail). Useful for the
     * placeholder images UNEC attaches to text-only MCQ questions. */
    silent?: boolean
  }>(),
  { alt: '', zoomable: false, silent: false },
)

const lightboxOpen = ref(false)

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const auth = useAuthStore()

const blobUrl = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

function normaliseFtpPath(raw: string): string {
  if (!raw) return ''
  if (raw.startsWith('/ASEU/')) return raw
  if (raw.includes('ftp_path=')) {
    try {
      const url = new URL(raw, baseURL)
      return decodeURIComponent(url.searchParams.get('ftp_path') ?? '')
    } catch {
      return raw
    }
  }
  return raw
}

function revoke() {
  if (blobUrl.value) {
    URL.revokeObjectURL(blobUrl.value)
    blobUrl.value = null
  }
}

async function load(src: string) {
  loading.value = true
  error.value = null
  revoke()
  try {
    const path = normaliseFtpPath(src)
    // apiBlob handles auth + auto-refresh on 401, returns the Blob.
    const blob = await apiBlob('/v1/exams/answer-image', { ftp_path: path })
    if (!blob || blob.size === 0) {
      throw new Error('пустой ответ')
    }
    blobUrl.value = URL.createObjectURL(blob)
  } catch (e: unknown) {
    const err = e as { status?: number; message?: string }
    error.value = err?.status ? `HTTP ${err.status}` : err?.message ?? 'ошибка загрузки'
  } finally {
    loading.value = false
  }
}

// Refetch when src changes or the user logs in/out.
watch(
  () => [props.src, auth.isAuthenticated] as const,
  ([src, authed]) => {
    if (!src || !authed) {
      revoke()
      loading.value = false
      error.value = null
      return
    }
    void load(src)
  },
  { immediate: true },
)

onUnmounted(revoke)

function onImgError() {
  error.value = 'не удалось отобразить'
  revoke()
}
</script>

<template>
  <div v-if="silent && error" class="hidden" />
  <div v-else class="inline-block">
    <Skeleton v-if="loading" width="220px" height="280px" />
    <div
      v-else-if="error"
      class="text-mark-negative text-[0.78rem] py-2 px-3 border border-mark-negative/40 rounded-sm bg-mark-negative/5"
    >
      Картинка не загрузилась
      <span class="block text-[0.7rem] text-muted mt-0.5">{{ error }}</span>
    </div>
    <img
      v-else-if="blobUrl"
      :src="blobUrl"
      :alt="alt"
      class="max-w-full block rounded-sm border border-border transition-opacity"
      :class="zoomable ? 'cursor-zoom-in hover:opacity-90' : ''"
      @error="onImgError"
      @click="zoomable && (lightboxOpen = true)"
    />
    <ImageLightbox
      v-if="zoomable"
      :open="lightboxOpen"
      :src="blobUrl"
      :alt="alt"
      @close="lightboxOpen = false"
    />
  </div>
</template>
