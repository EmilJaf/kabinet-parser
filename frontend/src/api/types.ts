// Types mirror the FastAPI response shapes in src/unec/api/schemas.py.

export interface UserOut {
  id: string
  email: string
  created_at: string
  is_admin: boolean
}

export interface AdminUserOut {
  id: string
  email: string
  is_admin: boolean
  created_at: string
  unec_username: string | null
  unec_last_login_at: string | null
  schedule_last_synced_at: string | null
  grades_last_synced_at: string | null
  exams_last_synced_at: string | null
  push_subscription_count: number
}

export interface AdminStatsOut {
  user_count: number
  admin_count: number
  unec_linked_count: number
  push_enabled_count: number
}

export interface AdminLogsOut {
  service: 'api' | 'worker'
  available: boolean
  file_size_bytes: number
  lines: string[]
}

export interface FilesOption {
  value: string
  label: string
  selected: boolean
}

export interface FilesSubject extends FilesOption {
  subj_id: string
}

export interface FilesTeacher {
  value: string
  name: string
  sylabus_path: string | null
  selected: boolean
}

export interface FilesTheme {
  theme_id: string
  subj_id: string
  topic: string
  has_lecture: boolean
  has_presentation: boolean
  has_test: boolean
  has_seminar: boolean
  has_other: boolean
}

export interface FilesPageOut {
  years: FilesOption[]
  semesters: FilesOption[]
  subjects: FilesSubject[]
  teachers: FilesTeacher[]
  themes: FilesTheme[]
  last_synced_at: string | null
}

export interface UnecCredentialsStatus {
  configured: boolean
  username: string | null
  last_login_at: string | null
  updated_at: string | null
}

export interface LessonOut {
  id: string
  day: number // 1=Mon..7=Sun
  start: string // "08:30:00"
  end: string
  subject: string
  subject_code: string | null
  lesson_type: string | null
  room: string | null
  building: string | null
  teacher: string | null
  week_parity: 'normal' | 'upper' | 'lower'
  period_start: string | null
  period_end: string | null
}

export interface ScheduleOut {
  edu_year_id: number | null
  last_synced_at: string | null
  sync_status: 'ok' | 'error' | null
  sync_error: string | null
  lessons: LessonOut[]
}

export interface MarkOut {
  id: string
  date: string
  topic: string
  mark_code: string | null
}

export interface LessonTypeMarksOut {
  lesson_type_id: number
  lesson_type_name: string | null
  marks: MarkOut[]
  final_eval: Record<string, string> | null
  scheme: Record<string, string> | null
  course_work: Record<string, string> | null
  independent_work: Record<string, string> | null
  writing: Record<string, string> | null
}

export interface SubjectOut {
  id: string
  unec_subject_id: number
  name: string
  group_name: string | null
  credits: number | null
  edu_form_id: number | null
  by_lesson_type: LessonTypeMarksOut[]
}

export interface GradesOut {
  edu_year_id: number | null
  edu_semester_id: number | null
  last_synced_at: string | null
  sync_status: 'ok' | 'error' | null
  sync_error: string | null
  subjects: SubjectOut[]
}

export interface ExamOut {
  id: string
  exam_type_name: string
  unec_exam_id: number | null
  subject_code: string | null
  subject_name: string
  subject_full: string | null
  form: string | null
  date: string | null
  start_time: string | null
  end_time: string | null
  entry_score: number | null
  exam_score: number | null
  final_score: number | null
  grade_letter: string | null
  grade_label: string | null
}

export interface ExamsOut {
  edu_year_id: number | null
  edu_semester_id: number | null
  last_synced_at: string | null
  sync_status: 'ok' | 'error' | null
  sync_error: string | null
  exams: ExamOut[]
}

export interface ExamQuestionOut {
  index: number
  question_id: number
  text: string
  status: 'correct' | 'wrong' | 'unknown'
  score: number | null
  comment: string | null
}

export interface ExamQuestionsOut {
  exam_id: string
  available: boolean
  correct_count: number
  wrong_count: number
  unknown_count: number
  questions: ExamQuestionOut[]
}

export interface ExamAnswerOptionOut {
  text: string
  image_path: string | null
  is_correct: boolean
  is_user_choice: boolean
}

export interface ExamQuestionDetailOut {
  kind: 'mcq' | 'written' | 'unknown'
  question_text: string
  question_image_path: string | null
  options: ExamAnswerOptionOut[]
  difficulty: string | null
  score: number | null
  comment: string | null
  answer_images: string[]
}

export interface UpcomingExamOut {
  group_name: string
  date: string | null
  start_time: string | null
  end_time: string | null
  entry_score: number | null
  username: string | null
  password: string | null
  exam_type_name: string
  status: string | null
  blocked: boolean
}
