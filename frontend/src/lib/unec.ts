/**
 * Static UNEC reference data — IDs the cabinet uses for years and semesters.
 * IDs are stable across users (verified from real responses), so we hardcode
 * them here instead of asking the backend on every navigation.
 */

// Generic over the id type so the same component handles both numeric
// IDs (most filters) and arbitrary strings (e.g. teacher hashes from
// UNEC's files page). Default = number for backwards compatibility.
export interface UnecOption<TId extends string | number = number> {
  id: TId
  label: string
}

// Listed newest-first — matches how UNEC orders them in the dropdown.
export const EDU_YEAR_OPTIONS: UnecOption[] = [
  { id: 1000048, label: '2025 — 2026' },
  { id: 1000044, label: '2024 — 2025' },
  { id: 1000043, label: '2023 — 2024' },
  { id: 1000042, label: '2022 — 2023' },
  { id: 1000041, label: '2021 — 2022' },
  { id: 1000040, label: '2020 — 2021' },
  { id: 1000039, label: '2019 — 2020' },
  { id: 1000018, label: '2018 — 2019' },
  { id: 1000008, label: '2017 — 2018' },
  { id: 1000005, label: '2016 — 2017' },
  { id: 1000004, label: '2015 — 2016' },
  { id: 1000006, label: '2014 — 2015' },
  { id: 1000009, label: '2013 — 2014' },
  { id: 1000010, label: '2012 — 2013' },
  { id: 1000011, label: '2011 — 2012' },
  { id: 1000012, label: '2010 — 2011' },
]

export const SEMESTER_OPTIONS: UnecOption[] = [
  { id: 1000109, label: 'I семестр' },
  { id: 1000111, label: 'II семестр' },
  { id: 1000112, label: 'Летний семестр' },
]

export function eduYearLabel(id: number | null | undefined): string {
  if (id == null) return ''
  return EDU_YEAR_OPTIONS.find((o) => o.id === id)?.label ?? `${id}`
}

export function semesterLabel(id: number | null | undefined): string {
  if (id == null) return ''
  return SEMESTER_OPTIONS.find((o) => o.id === id)?.label ?? `${id}`
}

// Exam type filter — local IDs map to UNEC's Azerbaijani exam_type_name
// (the backend filters by name, not numeric id). 0 means "no filter".
export const EXAM_TYPE_OPTIONS: UnecOption[] = [
  { id: 0, label: 'Все типы' },
  { id: 1, label: 'Финальный' },
  { id: 2, label: 'Финальный 1' },
  { id: 3, label: 'Финальный 2' },
  { id: 4, label: 'Финальный 3' },
  { id: 5, label: 'Промежуточный 1' },
  { id: 6, label: 'Промежуточный 2' },
  { id: 7, label: 'Промежуточный 3' },
  { id: 8, label: 'ИГА' },
]

const EXAM_TYPE_AZ_BY_ID: Record<number, string> = {
  1: 'Yekun imtahan',
  2: 'Yekun imtahan 1',
  3: 'Yekun imtahan 2',
  4: 'Yekun imtahan 3',
  5: 'Ara imtahan 1',
  6: 'Ara imtahan 2',
  7: 'Ara imtahan 3',
  8: 'Yekun Dövlət Attestasiyasi',
}

export function examTypeAzKey(id: number | null | undefined): string | null {
  if (!id) return null
  return EXAM_TYPE_AZ_BY_ID[id] ?? null
}
