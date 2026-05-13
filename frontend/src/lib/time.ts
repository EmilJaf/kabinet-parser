// Date/time formatting helpers — locale-aware via vue-i18n catalogs
// (week-day labels) and Intl.DateTimeFormat (month + numeric formatting).
import { i18n, currentLocale, type AppLocale } from '@/i18n'

function tArr(key: string): string[] {
  const v = i18n.global.t(key)
  return Array.isArray(v) ? (v as string[]) : []
}

function tStr(key: string, vars?: Record<string, unknown>): string {
  return i18n.global.t(key, vars ?? {}) as string
}

const INTL_TAG: Record<AppLocale, string> = {
  az: 'az-AZ',
  ru: 'ru-RU',
  en: 'en-GB',
}

function intlTag(): string {
  return INTL_TAG[currentLocale()]
}

export function relativeTime(date: Date): string {
  const diff = Date.now() - date.getTime()
  const min = Math.floor(diff / 60_000)
  if (min < 1) return tStr('time.justNow')
  if (min < 60) return tStr('time.minAgo', { n: min })
  const hr = Math.floor(min / 60)
  if (hr < 24) return tStr('time.hAgo', { n: hr })
  const day = Math.floor(hr / 24)
  if (day < 30) return tStr('time.dAgo', { n: day })
  return date.toLocaleDateString(intlTag())
}

/**
 * Locale-aware "6 May" / "6 мая" / "6 may". Appends the year when it
 * differs from the current one (or always with `withYear: true`,
 * never with `withYear: false`).
 */
export function formatDate(date: Date, opts: { withYear?: boolean } = {}): string {
  const sameYear = date.getFullYear() === new Date().getFullYear()
  const includeYear = opts.withYear === true || (opts.withYear !== false && !sameYear)
  return new Intl.DateTimeFormat(intlTag(), {
    day: 'numeric',
    month: 'long',
    ...(includeYear ? { year: 'numeric' } : {}),
  }).format(date)
}

/** Day name from JS weekday (0=Sun..6=Sat). `short` returns 2-3 letter form. */
export function dayName(dow: number, short = false): string {
  const arr = tArr(short ? 'time.weekDaysShort' : 'time.weekDaysLong')
  // Catalogs are stored Mon..Sun; convert from JS Sun..Sat.
  const idx = dow === 0 ? 6 : dow - 1
  return arr[idx] ?? ''
}

/** Backend uses ISO weekday (1=Mon..7=Sun). Convert to JS dow (0=Sun..6=Sat). */
export function isoToJsDow(iso: number): number {
  return iso === 7 ? 0 : iso
}

/** Today as backend ISO weekday. */
export function todayIsoDow(): number {
  const js = new Date().getDay()
  return js === 0 ? 7 : js
}

/** "08:30:00" → "08:30". */
export function shortTime(t: string): string {
  return t.slice(0, 5)
}

/** "2026-05-06" → Date. */
export function parseISODate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
