import type { TimetableRecord } from './api';

export function observedClassCount(records: TimetableRecord[]): number {
  return new Set(records.filter((record) => Number.isInteger(Number(record.grade)) && Number(record.grade) > 0 && Number.isInteger(Number(record.class)) && Number(record.class) > 0)
    .map((record) => `${Number(record.grade)}:${Number(record.class)}`)).size;
}

export function subjectNamesInTimetable(records: TimetableRecord[]): string[] {
  return [...new Set(records.map((record) => record.subject?.trim()).filter((name): name is string => !!name))]
    .sort((a, b) => a.localeCompare(b, 'ko-KR'));
}

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

export function teacherSuggestions(names: string[], query: string, display: (name: string) => string): string[] {
  const normalized = query.trim().toLocaleLowerCase('ko-KR');
  return names.filter((name) => [name, display(name)].some((label) => label.toLocaleLowerCase('ko-KR').includes(normalized)));
}

export function selectedTeacherName(names: string[], query: string, display: (name: string) => string): string {
  const trimmed = query.trim();
  return names.find((name) => name === trimmed || display(name) === trimmed) ?? '';
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
