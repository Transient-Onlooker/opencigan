import './embed.css';
import { getTimetable, type TimetableRecord, type TimetableResponse } from './api';
import { currentKoreaDate, monday, addDays } from './date';
import { slotLessons } from './timetable-slots';

export interface EmbedParams {
  school: string;
  name: string;
  region: string;
  grade: number;
  classroom: number;
  weekOffset: number;
  theme: 'light' | 'dark' | 'auto';
}

export function parseEmbedFragment(hash: string): EmbedParams | null {
  if (!hash || hash.length > 4096) return null;
  const raw = hash.replace(/^#/, '');
  if (!raw) return null;
  const params = new URLSearchParams(raw);

  const recognized = ['school', 'grade', 'class', 'name', 'region', 'week', 'theme'];
  if (recognized.some((k) => params.getAll(k).length > 1)) return null;
  if (['school', 'grade', 'class'].some((k) => params.getAll(k).length !== 1)) return null;
  const school = params.get('school')!;
  const gradeText = params.get('grade')!;
  const classText = params.get('class')!;

  if (!/^[0-9]+:[^:]{1,50}$/.test(school) || school.length > 100) return null;
  if (!/^[1-6]$/.test(gradeText)) return null;
  if (!/^[1-9][0-9]?$/.test(classText)) return null;

  const name = (params.get('name') ?? '').trim();
  if (name.length > 50) return null;

  const region = (params.get('region') ?? '').trim();
  if (region.length > 100) return null;

  let weekOffset = 0;
  const weekParam = params.get('week');
  if (weekParam === 'next') weekOffset = 1;
  else if (weekParam !== null && weekParam !== 'current' && weekParam !== '') return null;

  let theme: 'light' | 'dark' | 'auto' = 'auto';
  const themeParam = params.get('theme');
  if (themeParam === 'dark' || themeParam === 'light') theme = themeParam;
  else if (themeParam !== null && themeParam !== 'auto' && themeParam !== '') return null;

  return {
    school,
    name: name || school.split(':')[1] || school,
    region,
    grade: Number(gradeText),
    classroom: Number(classText),
    weekOffset,
    theme,
  };
}

export function filterClassRecords(records: TimetableRecord[], grade: number, classroom: number): TimetableRecord[] {
  return records.filter((r) => Number(r.grade) === grade && Number(r.class) === classroom);
}

export function applyWidgetTheme(element: HTMLElement, theme: 'light' | 'dark' | 'auto') {
  element.classList.remove('theme-dark');
  if (theme === 'dark') {
    element.classList.add('theme-dark');
  } else if (theme === 'auto') {
    if (typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      element.classList.add('theme-dark');
    }
  }
}

export function renderWidgetTable(
  tbody: HTMLTableSectionElement,
  classRecords: TimetableRecord[],
  mondayDate: string,
  todayDate: string,
  classroom: number
) {
  tbody.replaceChildren();
  const dates = [0, 1, 2, 3, 4].map((i) => addDays(mondayDate, i));

  let maxPeriod = 0;
  for (const r of classRecords) {
    if (r.period > maxPeriod) {
      maxPeriod = r.period;
    }
  }
  maxPeriod = Math.min(20, Math.max(6, maxPeriod));

  for (let p = 1; p <= maxPeriod; p++) {
    const tr = document.createElement('tr');

    const periodTd = document.createElement('td');
    periodTd.className = 'col-period-label';
    periodTd.textContent = String(p);
    tr.append(periodTd);

    for (let d = 0; d < 5; d++) {
      const dateStr = dates[d];
      const td = document.createElement('td');
      if (dateStr === todayDate) {
        td.classList.add('cell-today');
      }

      const lessons = slotLessons(classRecords, dateStr, p, classroom);
      if (lessons.length > 0) {
        if (lessons.some((lesson) => lesson.isChanged)) td.classList.add('cell-changed');
        for (const lesson of lessons) {
          const subjSpan = document.createElement('span');
          subjSpan.className = 'lesson-subject';
          subjSpan.textContent = lesson.subject;
          td.append(subjSpan);

          if (lesson.teacher) {
            const teacherSpan = document.createElement('span');
            teacherSpan.className = 'lesson-teacher';
            teacherSpan.textContent = lesson.teacher;
            td.append(teacherSpan);
          }
        }
      }
      tr.append(td);
    }
    tbody.append(tr);
  }
}

async function init() {
  const root = document.querySelector<HTMLElement>('#widget-root');
  const title = document.querySelector<HTMLElement>('#widget-title');
  const meta = document.querySelector<HTMLElement>('#widget-meta');
  const msg = document.querySelector<HTMLElement>('#widget-message');
  const tableWrap = document.querySelector<HTMLElement>('#widget-table-wrap');
  const tbody = document.querySelector<HTMLTableSectionElement>('#widget-table-body');
  const updated = document.querySelector<HTMLElement>('#widget-updated');
  const link = document.querySelector<HTMLAnchorElement>('#widget-link');

  if (!root || !title || !meta || !msg || !tableWrap || !tbody || !updated || !link) return;

  const params = parseEmbedFragment(location.hash);
  if (!params) {
    msg.textContent = '올바르지 않은 위젯 설정입니다. URL 해시를 확인해 주세요.';
    msg.classList.add('status-error');
    return;
  }

  applyWidgetTheme(root, params.theme);

  title.textContent = params.name + ' ' + params.grade + '학년 ' + params.classroom + '반';

  const now = new Date();
  const today = currentKoreaDate(now);
  const currentMonday = monday(today);
  const targetMonday = params.weekOffset === 1 ? addDays(currentMonday, 7) : currentMonday;
  const weekEndFriday = addDays(targetMonday, 4);
  meta.textContent = targetMonday + ' ~ ' + weekEndFriday + ' (' + (params.weekOffset === 1 ? '다음 주' : '이번 주') + ')';

  const parentUrl = new URL(location.href);
  parentUrl.pathname = parentUrl.pathname.replace(/embed\.html$/, '') || './';
  parentUrl.search = '';
  parentUrl.hash = new URLSearchParams({
    school: params.school,
    name: params.name,
    region: params.region,
    grade: String(params.grade),
    class: String(params.classroom),
  }).toString();
  link.href = parentUrl.href;

  const dayOfWeek = (new Date(today + 'T00:00:00Z').getUTCDay());
  if (params.weekOffset === 0 && dayOfWeek >= 1 && dayOfWeek <= 5) {
    const thToday = document.querySelector<HTMLTableCellElement>('#widget-table-head th[data-day="' + dayOfWeek + '"]');
    if (thToday) thToday.classList.add('day-today');
  }

  try {
    msg.textContent = '시간표를 불러오는 중…';
    const data = await getTimetable(params.school, targetMonday);

    const classRecords = filterClassRecords(data.records, params.grade, params.classroom);
    if (classRecords.length === 0) {
      tbody.replaceChildren();
      tableWrap.hidden = true;
      msg.textContent = data.stale
        ? '요청한 학년·반의 시간표가 없습니다. (오프라인/이전 데이터)'
        : '요청한 학년·반의 시간표가 없습니다.';
      msg.hidden = false;
      return;
    }

    renderWidgetTable(tbody, classRecords, targetMonday, today, params.classroom);

    if (data.stale) {
      msg.textContent = '네트워크 연결이 원활하지 않아 이전에 저장된 시간표를 표시합니다.';
      msg.hidden = false;
    } else {
      msg.hidden = true;
    }
    tableWrap.hidden = false;

    if (data.sourceUpdatedAt) {
      updated.textContent = '기준: ' + data.sourceUpdatedAt;
    } else {
      updated.textContent = '조회: ' + today;
    }
  } catch (err) {
    msg.textContent = err instanceof Error ? err.message : '시간표를 불러오지 못했습니다.';
    msg.classList.add('status-error');
  }
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  window.addEventListener('DOMContentLoaded', init);
}
