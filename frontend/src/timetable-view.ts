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

export function gradeLessons(records: TimetableRecord[], grade: number): TimetableRecord[] {
  return records.filter((record) => Number(record.grade) === Number(grade));
}

export function comparisonClasses(records: TimetableRecord[]): number[] {
  return [...new Set(records.map((record) => Number(record.class)))].sort((a, b) => a - b);
}

export function missingWeekdayDates(records: TimetableRecord[], dates: string[]): string[] {
  const recordedDates = new Set(records.map((record) => record.date));
  return dates.slice(0, 5).filter((date) => !recordedDates.has(date));
}
