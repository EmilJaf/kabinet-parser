const RU_MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

const RU_DAYS_FULL = [
  'Воскресенье', 'Понедельник', 'Вторник', 'Среда',
  'Четверг', 'Пятница', 'Суббота',
]

const RU_DAYS_SHORT = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

export function relativeTime(date: Date): string {
  const diff = Date.now() - date.getTime()
  const min = Math.floor(diff / 60_000)
  if (min < 1) return 'только что'
  if (min < 60) return `${min} мин назад`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} ч назад`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day} дн назад`
  return date.toLocaleDateString('ru-RU')
}

/**
 * "6 мая" — or "6 мая 2026" if year differs from current.
 *
 *   { withYear: false } → never append year (use when the calling context
 *     already pins the year, e.g. inside a year/semester-filtered view)
 *   { withYear: true }  → always append year
 *   default             → append only when year differs from this year
 */
export function formatDate(date: Date, opts: { withYear?: boolean } = {}): string {
  const dd = date.getDate()
  const month = RU_MONTHS_GENITIVE[date.getMonth()]
  const includeYear =
    opts.withYear === true ||
    (opts.withYear !== false && date.getFullYear() !== new Date().getFullYear())
  if (includeYear) {
    return `${dd} ${month} ${date.getFullYear()}`
  }
  return `${dd} ${month}`
}

/** Russian day name. js dow (0=Sun..6=Sat). */
export function dayName(dow: number, short = false): string {
  return short ? RU_DAYS_SHORT[dow] : RU_DAYS_FULL[dow]
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
