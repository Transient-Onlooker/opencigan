import { test } from 'node:test';
import assert from 'node:assert/strict';
import { personalizationVm as view } from './helpers/personalization-vm.js';

test('class and teacher selections preserve lesson order and all simultaneous lessons', () => {
  const records = [
    { grade: 1, class: 1, teacher: ' 김교사 ', subject: '수학' },
    { grade: 1, class: 1, teacher: '김교사', subject: '과학' },
    { grade: 2, class: 1, teacher: '김교사', subject: '영어' },
    { grade: 1, class: 2, teacher: '이교사', subject: '국어' },
  ];
  assert.deepEqual(Array.from(view.classLessons(records, 1, 1), (r) => r.subject), ['수학', '과학']);
  assert.deepEqual(Array.from(view.teacherLessons(records, '김교사'), (r) => r.subject), ['수학', '과학', '영어']);
  assert.deepEqual(Array.from(view.teacherNamesInTimetable(records)), ['김교사', '이교사']);
  assert.equal(view.teacherLessons(records, '').length, 0);
});

test('teacher suggestions accept partial original and displayed names but selection requires an exact match', () => {
  const names = ['김교사', '이교사'];
  const display = (name) => name === '김교사' ? 'Math T' : name;
  assert.deepEqual(Array.from(view.teacherSuggestions(names, ' math ', display)), ['김교사']);
  assert.deepEqual(Array.from(view.teacherSuggestions(names, '교사', display)), names);
  assert.equal(view.selectedTeacherName(names, ' Math T ', display), '김교사');
  assert.equal(view.selectedTeacherName(names, '김교사', display), '김교사');
  assert.equal(view.selectedTeacherName(names, '교사', display), '');
});

test('grade comparison and missing weekdays keep scope and ordering', () => {
  const records = [
    { grade: 2, class: '10', date: 'mon' },
    { grade: 1, class: 1, date: 'tue' },
    { grade: 2, class: 2, date: 'mon' },
    { grade: 2, class: 2, date: 'sat' },
  ];
  const selected = view.gradeLessons(records, 2);
  assert.deepEqual(Array.from(view.comparisonClasses(selected)), [2, 10]);
  assert.deepEqual(Array.from(view.missingWeekdayDates(selected, ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'])), ['tue', 'wed', 'thu', 'fri']);
  assert.equal(selected.length, 3);
});

test('school summary counts observed classes and lists distinct trimmed subjects', () => {
  const records = [
    { grade: 1, class: '2', subject: ' 수학 ' },
    { grade: '1', class: 2, subject: '수학' },
    { grade: 2, class: 2, subject: '국어' },
    { grade: 0, class: 3, subject: '' },
    { grade: 1, class: 'bad', subject: null },
  ];
  assert.equal(view.observedClassCount(records), 2);
  assert.deepEqual(Array.from(view.subjectNamesInTimetable(records)), ['국어', '수학']);
});
