import type { TimetableRecord } from './api';

export function classLessons(records: TimetableRecord[], grade: number, classroom: number): TimetableRecord[] {
  return records.filter((record) => Number(record.grade) === Number(grade) && Number(record.class) === Number(classroom));
}

export function teacherNamesInTimetable(records: TimetableRecord[]): string[] {
  return [...new Set(records.map((record) => record.teacher?.trim()).filter((name): name is string => !!name))]
    .sort((a, b) => a.localeCompare(b, 'ko-KR'));
}

export function teacherLessons(records: TimetableRecord[], name: string): TimetableRecord[] {
  return name ? records.filter((record) => record.teacher?.trim() === name) : [];
}
