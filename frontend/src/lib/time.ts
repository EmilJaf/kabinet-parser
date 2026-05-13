// Date/time formatting helpers — locale-aware via vue-i18n catalogs.
//
// We deliberately avoid Intl.DateTimeFormat for month names because some
// runtime ICU builds (notably mobile Safari with small-icu data) emit
// fallback skeletons like "M05 14" for less-common locales (az). Sourcing
// month and weekday names from our own catalog keeps output predictable
// across every environment the PWA runs in.
import { i18n } from '@/i18n'

// vue-i18n v10's `t()` returns a string and serialises array values; raw
// arrays must be fetched via `tm()`.
function tmArr(key: string): string[] {
  const v = i18n.global.tm(key) as unknown
  return Array.isArray(v) ? (v as string[]) : []
}

function tStr(key: string, vars?: Record<string, unknown>): string {
  return i18n.global.t(key, vars ?? {}) as string
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
  return formatDate(date, { withYear: true })
}

/**
 * Locale-aware "6 May" / "6 мая" / "6 may" using the i18n catalog's month
 * names. Appends the year when it differs from the current one (or always
 * with `withYear: true`, never with `withYear: false`).
 */
export function formatDate(date: Date, opts: { withYear?: boolean } = {}): string {
  const months = tmArr('time.monthsLong')
  const monthName = months[date.getMonth()] ?? String(date.getMonth() + 1)
  const sameYear = date.getFullYear() === new Date().getFullYear()
  const includeYear = opts.withYear === true || (opts.withYear !== false && !sameYear)
  const base = `${date.getDate()} ${monthName}`
  return includeYear ? `${base} ${date.getFullYear()}` : base
}

/** Day name from JS weekday (0=Sun..6=Sat). `short` returns 2-3 letter form. */
export function dayName(dow: number, short = false): string {
  const arr = tmArr(short ? 'time.weekDaysShort' : 'time.weekDaysLong')
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
