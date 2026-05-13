// vue-i18n bootstrap. Catalogs are bundled (small enough — ~30 KB each
// gzipped), so no async loader. Initial locale comes from localStorage
// or the browser hint; auth store overwrites it once /auth/me returns
// the user's preferred language.
import { createI18n } from 'vue-i18n'
import az from '@/locales/az.json'
import ru from '@/locales/ru.json'
import en from '@/locales/en.json'

export type AppLocale = 'az' | 'ru' | 'en'
export const SUPPORTED_LOCALES: AppLocale[] = ['az', 'ru', 'en']
export const DEFAULT_LOCALE: AppLocale = 'az'
const STORAGE_KEY = 'kabinet:locale'

function detectInitial(): AppLocale {
  const stored = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
  if (stored && (SUPPORTED_LOCALES as string[]).includes(stored)) return stored as AppLocale
  if (typeof navigator !== 'undefined') {
    const tag = (navigator.language ?? '').slice(0, 2).toLowerCase()
    if ((SUPPORTED_LOCALES as string[]).includes(tag)) return tag as AppLocale
  }
  return DEFAULT_LOCALE
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: detectInitial(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { az, ru, en },
})

export function setAppLocale(lang: AppLocale): void {
  i18n.global.locale.value = lang
  try {
    localStorage.setItem(STORAGE_KEY, lang)
  } catch {
    /* private mode etc — fine */
  }
}

/** Plain getter for places that can't call useI18n() (e.g. modules). */
export function currentLocale(): AppLocale {
  return i18n.global.locale.value as AppLocale
}
