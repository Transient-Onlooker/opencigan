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
