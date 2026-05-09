/**
 * UNEC speaks Azerbaijani; the Kabinet UI speaks Russian. This module is the
 * single seam where we translate strings the cabinet hands us — lesson types,
 * grading-table column headers, sync statuses. Backend stores values as-is so
 * we can fix translations without re-syncing.
 */

const LESSON_TYPE_RU: Record<string, string> = {
  'Mühazirə': 'Лекция',
  'Seminar': 'Семинар',
  'Laboratoriya': 'Лабораторная',
  'Məsləhət saatı': 'Консультация',
  'Seminar-distant': 'Семинар (дистант)',
}

const LESSON_TYPE_PLURAL_RU: Record<string, [string, string, string]> = {
  // [for 1, for 2-4, for 5-20]
  'Mühazirə': ['лекция', 'лекции', 'лекций'],
  'Seminar': ['семинар', 'семинара', 'семинаров'],
  'Laboratoriya': ['лабораторная', 'лабораторных', 'лабораторных'],
  'Məsləhət saatı': ['консультация', 'консультации', 'консультаций'],
  'Seminar-distant': ['дистант-семинар', 'дистант-семинара', 'дистант-семинаров'],
}

const GRADING_FIELD_RU: Record<string, string> = {
  // Yekun qiymətləndirmə (final eval) headers
  'Davamiyyət': 'Посещаемость',
  'Kollokvium 1': 'Коллоквиум 1',
  'Kollokvium 2': 'Коллоквиум 2',
  'Kollokvium orta balı': 'Коллоквиум · средний',
  'Seminarın orta balı': 'Семинар · средний',
  'Sərbəst iş': 'Самостоятельная',
  'Laboratoriya işi': 'Лабораторная',
  'Kurs işi': 'Курсовая',
  'Cari qiymətləndirmə': 'Текущая оценка',
  'Qeyd': 'Примечание',
  'Mühazirə balı': 'Балл за лекции',
  'Ev tapşırığı': 'Домашнее задание',
  'Ev oxusu': 'Домашнее чтение',
  'Qaib faizi': 'Пропуски, %',

  // Forma (scheme / max-score schema)
  'Davamiyyət balı': 'Посещаемость',
  'Sərbəst iş/tapşırıq': 'Самостоятельная',
  'Writing1': 'Writing 1',
  'Writing2': 'Writing 2',
  'Ara imtahanına verilən maksimal bal': 'Промежуточный, макс',
  'Ara imtahanında sual sayı': 'Промежуточный, вопросов',
  'Laboratoriya': 'Лабораторная',
  'İmtahana qədər yekun': 'До экзамена · итог',
  'İmtahan maksimum bal': 'Экзамен, макс',

  // Writing tab
  '№': '№',
  'Soyad Ad Ata adı': 'ФИО',
  'Writting1': 'Writing 1',
  'Writting2': 'Writing 2',
  'Yekun': 'Итог',

  // Course work / independent work
  'Tarix': 'Дата',
  'Mövzu': 'Тема',
  'Bal': 'Балл',
  'Dərs nömrəsi': '№ занятия',
  'Fənn': 'Предмет',
}

/** UNEC lesson_type IDs are stable across years; map them when the label is missing. */
const LESSON_TYPE_BY_ID_RU: Record<number, string> = {
  4100: 'Лекция',
  4101: 'Семинар',
  4102: 'Лабораторная',
  4103: 'Семинар (дистант)',
  4104: 'Консультация',
}

/** Localise a lesson_type label coming straight from UNEC. */
export function lessonTypeRu(name: string | null | undefined, id?: number | null): string {
  if (name) return LESSON_TYPE_RU[name] ?? name
  if (id != null) return LESSON_TYPE_BY_ID_RU[id] ?? `Тип ${id}`
  return ''
}

/** Pluralised lowercase noun for lesson_type — for "12 лекций" style strings. */
export function lessonTypePluralRu(name: string | null | undefined, n: number): string {
  if (!name) return ''
  const forms = LESSON_TYPE_PLURAL_RU[name]
  if (!forms) return (LESSON_TYPE_RU[name] ?? name).toLowerCase()
  return pluralize(n, forms)
}

/** Localise a grading-table column header. Falls back to the original key. */
export function gradingFieldRu(key: string): string {
  return GRADING_FIELD_RU[key] ?? key
}

const SEMESTER_LABEL_RU: Record<string, string> = {
  'I semestr': 'I семестр',
  'II semestr': 'II семестр',
  'III semestr': 'III семестр',
  'IV semestr': 'IV семестр',
  'V semestr': 'V семестр',
  'VI semestr': 'VI семестр',
  'VII semestr': 'VII семестр',
  'VIII semestr': 'VIII семестр',
  'Yay semestri': 'Летний семестр',
}

/** Localise a semester label coming straight from UNEC's getEduSemester XHR. */
export function semesterLabelRu(label: string | null | undefined): string {
  if (!label) return ''
  return SEMESTER_LABEL_RU[label] ?? label
}

const EXAM_TYPE_RU: Record<string, string> = {
  'Yekun imtahan': 'Финальный',
  'Yekun imtahan 1': 'Финальный 1',
  'Yekun imtahan 2': 'Финальный 2',
  'Yekun imtahan 3': 'Финальный 3',
  'Ara imtahan 1': 'Промежуточный 1',
  'Ara imtahan 2': 'Промежуточный 2',
  'Ara imtahan 3': 'Промежуточный 3',
  'Yekun Dövlət Attestasiyasi': 'ИГА',
}

export function examTypeRu(name: string | null | undefined): string {
  if (!name) return ''
  return EXAM_TYPE_RU[name] ?? name
}

const EXAM_FORM_RU: Record<string, string> = {
  'Elektron imtahan': 'Электронный',
  'Yazili imtahan': 'Письменный',
}

export function examFormRu(name: string | null | undefined): string {
  if (!name) return ''
  return EXAM_FORM_RU[name] ?? name
}

const EXAM_GRADE_LABEL_RU: Record<string, string> = {
  'Əla': 'Отлично',
  'Çox yaxşı': 'Очень хорошо',
  'Yaxşı': 'Хорошо',
  'Kafi': 'Удовл.',
  'Qeyri-kafi': 'Неуд.',
}

export function examGradeLabelRu(label: string | null | undefined): string {
  if (!label) return ''
  return EXAM_GRADE_LABEL_RU[label] ?? label
}

/** Russian plural picker. forms = [for 1, for 2-4, for 5-20]. */
export function pluralize(n: number, forms: [string, string, string]): string {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return forms[0]
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return forms[1]
  return forms[2]
}
