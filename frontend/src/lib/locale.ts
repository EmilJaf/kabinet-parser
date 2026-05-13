/**
 * Translates strings UNEC hands us in Azerbaijani — lesson types, grading
 * column headers, semester labels, exam types/forms/grades. Backed by the
 * vue-i18n catalogs under `lessonType`, `gradingField`, `semester`,
 * `examType`, `examForm`, `examGrade` so they pick up the user's chosen
 * language at runtime.
 */
import { i18n } from '@/i18n'

function tStr(key: string, vars?: Record<string, unknown>): string {
  return i18n.global.t(key, vars ?? {}) as string
}

function tMaybe(key: string): string | null {
  // vue-i18n returns the key unchanged when missing — that's our cue
  // to fall back to the original UNEC label.
  const v = i18n.global.t(key)
  return typeof v === 'string' && v !== key ? v : null
}

function tPluralForms(key: string): [string, string, string] | null {
  // vue-i18n v10 returns strings from `t()`; arrays come through `tm()`.
  const v = i18n.global.tm(key) as unknown
  if (Array.isArray(v) && v.length === 3 && v.every((s) => typeof s === 'string')) {
    return v as [string, string, string]
  }
  return null
}

/** Localise a lesson_type label coming straight from UNEC. */
export function lessonTypeRu(name: string | null | undefined, id?: number | null): string {
  if (name) return tMaybe(`lessonType.byName.${name}`) ?? name
  if (id != null) return tMaybe(`lessonType.byId.${id}`) ?? tStr('lessonType.fallback', { id })
  return ''
}

/** Pluralised lowercase noun for lesson_type — for "12 лекций" style strings. */
export function lessonTypePluralRu(name: string | null | undefined, n: number): string {
  if (!name) return ''
  const forms = tPluralForms(`lessonType.byNamePlural.${name}`)
  if (!forms) return (tMaybe(`lessonType.byName.${name}`) ?? name).toLowerCase()
  return pluralize(n, forms)
}

/** Localise a grading-table column header. Falls back to the original key. */
export function gradingFieldRu(key: string): string {
  return tMaybe(`gradingField.${key}`) ?? key
}

/** Localise a semester label coming straight from UNEC's getEduSemester XHR. */
export function semesterLabelRu(label: string | null | undefined): string {
  if (!label) return ''
  return tMaybe(`semester.${label}`) ?? label
}

export function examTypeRu(name: string | null | undefined): string {
  if (!name) return ''
  return tMaybe(`examType.${name}`) ?? name
}

export function examFormRu(name: string | null | undefined): string {
  if (!name) return ''
  return tMaybe(`examForm.${name}`) ?? name
}

export function examGradeLabelRu(label: string | null | undefined): string {
  if (!label) return ''
  return tMaybe(`examGrade.${label}`) ?? label
}

/** Russian plural picker. forms = [for 1, for 2-4, for 5-20]. AZ/EN
 *  fall through naturally because their catalogs use the same value
 *  in all three slots, so the picked form doesn't matter. */
export function pluralize(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return forms[1]
  return forms[2]
}
