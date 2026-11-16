import './embed.css';
import './standalone-theme';
import { searchSchools, getTimetable, type School, type TimetableRecord } from './api';
import { currentKoreaDate, monday } from './date';

export function sanitizeDimension(val: string, fallback: string): string {
  const trimmed = val.trim();
  if (/^[1-9][0-9]{0,3}px$/.test(trimmed)) return trimmed;
  if (/^(?:[1-9][0-9]?|100)%$/.test(trimmed)) return trimmed;
  if (/^[1-9][0-9]{1,3}$/.test(trimmed)) return trimmed + 'px';
  return fallback;
}

export function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function buildEmbedUrl(
  baseUrl: string,
  school: School,
  grade: number,
  classroom: number,
  week: 'current' | 'next' = 'current',
  theme: 'auto' | 'light' | 'dark' = 'auto'
): string {
  const url = new URL(baseUrl);
  url.search = '';
  const params = new URLSearchParams();
  params.set('school', school.id);
  params.set('name', school.name);
  params.set('region', school.region);
  params.set('grade', String(grade));
  params.set('class', String(classroom));
  if (week !== 'current') params.set('week', week);
  if (theme !== 'auto') params.set('theme', theme);
  url.hash = params.toString();
  return url.href;
}

export function buildIframeSnippet(
  embedUrl: string,
  title: string,
  width: string = '100%',
  height: string = '380'
): string {
  const cleanWidth = sanitizeDimension(width, '100%');
  const cleanHeight = sanitizeDimension(height, '380px');
  const escapedTitle = escapeHtml(title);
  const escapedUrl = escapeHtml(embedUrl);
  return '<iframe src="' + escapedUrl + '" width="' + cleanWidth + '" height="' + cleanHeight + '" frameborder="0" loading="lazy" title="' + escapedTitle + '" style="border:1px solid #d4d4d4;border-radius:0"></iframe>';
}

export function extractAvailableClasses(records: TimetableRecord[], grade: number): number[] {
  const classesSet = new Set<number>();
  for (const r of records) {
    if (Number(r.grade) === grade) {
      const c = Number(r.class);
      if (Number.isInteger(c) && c > 0) classesSet.add(c);
    }
  }
  return Array.from(classesSet).sort((a, b) => a - b);
}

let selectedSchool: School | null = null;
let cachedRecords: TimetableRecord[] = [];
let searchController: AbortController | null = null;
let timetableController: AbortController | null = null;
let searchGeneration = 0;
let schoolGeneration = 0;

function updateCodeAndPreview() {
  const gradeSelect = document.querySelector<HTMLSelectElement>('#grade-select')!;
  const classSelect = document.querySelector<HTMLSelectElement>('#class-select')!;
  const weekSelect = document.querySelector<HTMLSelectElement>('#week-select')!;
  const themeSelect = document.querySelector<HTMLSelectElement>('#theme-select')!;
  const widthInput = document.querySelector<HTMLInputElement>('#width-input')!;
  const heightInput = document.querySelector<HTMLInputElement>('#height-input')!;
  const previewIframe = document.querySelector<HTMLIFrameElement>('#preview-iframe')!;
  const codeOutput = document.querySelector<HTMLTextAreaElement>('#code-output')!;
  const copyBtn = document.querySelector<HTMLButtonElement>('#copy-code-btn')!;

  const grade = Number(gradeSelect.value);
  const classroom = Number(classSelect.value);

  if (!selectedSchool || !grade || !classroom) {
    previewIframe.src = 'about:blank';
    codeOutput.value = '학교, 학년, 반을 선택하면 임베드 코드가 생성됩니다.';
    copyBtn.disabled = true;
    return;
  }

  const currentUrl = new URL(location.href);
  currentUrl.pathname = currentUrl.pathname.replace(/embed-builder\.html$/, 'embed.html');
  if (!currentUrl.pathname.endsWith('embed.html')) {
    currentUrl.pathname = currentUrl.pathname.replace(/\/[^/]*$/, '/embed.html');
  }

  const week = (weekSelect.value as 'current' | 'next') || 'current';
  const theme = (themeSelect.value as 'auto' | 'light' | 'dark') || 'auto';
  const embedUrl = buildEmbedUrl(currentUrl.href, selectedSchool, grade, classroom, week, theme);
  const title = selectedSchool.name + ' ' + grade + '학년 ' + classroom + '반 시간표';
  const snippet = buildIframeSnippet(embedUrl, title, widthInput.value, heightInput.value);

  previewIframe.src = embedUrl;
  codeOutput.value = snippet;
  copyBtn.disabled = false;
}

async function onSelectSchool(school: School) {
  searchGeneration++;
  searchController?.abort();
  timetableController?.abort();
  const generation = ++schoolGeneration;
  const controller = new AbortController();
  timetableController = controller;
  selectedSchool = school;
  cachedRecords = [];
  const searchInput = document.querySelector<HTMLInputElement>('#school-search-input')!;
  const searchResults = document.querySelector<HTMLUListElement>('#school-search-results')!;
  const selectedBox = document.querySelector<HTMLElement>('#selected-school-box')!;
  const selectedName = document.querySelector<HTMLElement>('#selected-school-name')!;
  const selectedMeta = document.querySelector<HTMLElement>('#selected-school-meta')!;
  const gradeSelect = document.querySelector<HTMLSelectElement>('#grade-select')!;
  const classSelect = document.querySelector<HTMLSelectElement>('#class-select')!;

  searchInput.hidden = true;
  searchResults.hidden = true;
  selectedBox.hidden = false;
  selectedName.textContent = school.name;
  selectedMeta.textContent = school.region + ' (' + school.id + ')';

  gradeSelect.disabled = true;
  classSelect.disabled = true;
  classSelect.replaceChildren(new Option('선택', ''));

  gradeSelect.value = '';
  updateCodeAndPreview();

  try {
    const today = currentKoreaDate(new Date());
    const thisMonday = monday(today);
    const res = await getTimetable(school.id, thisMonday, controller.signal);
    if (generation !== schoolGeneration || selectedSchool !== school) return;
    cachedRecords = res.records;
    const grades = Array.from(new Set(cachedRecords
      .map((record) => Number(record.grade))
      .filter((grade) => Number.isInteger(grade) && grade >= 1 && grade <= 6)))
      .sort((a, b) => a - b);
    gradeSelect.disabled = grades.length === 0;
    gradeSelect.replaceChildren(new Option('선택', ''), ...grades.map((grade) => new Option(grade + '학년', String(grade))));
    gradeSelect.value = grades.length > 0 ? String(grades[0]) : '';
    if (grades.length > 0) populateClasses(grades[0]);
  } catch (e) {
    if (generation !== schoolGeneration) return;
    alert('시간표 데이터를 가져오지 못했습니다: ' + (e instanceof Error ? e.message : String(e)));
  }
  if (generation !== schoolGeneration) return;
  updateCodeAndPreview();
}

function populateClasses(grade: number) {
  const classSelect = document.querySelector<HTMLSelectElement>('#class-select')!;
  classSelect.replaceChildren(new Option('선택', ''));
  const available = extractAvailableClasses(cachedRecords, grade);
  if (available.length > 0) {
    for (const c of available) {
      classSelect.add(new Option(c + '반', String(c)));
    }
    classSelect.value = String(available[0]);
    classSelect.disabled = false;
  } else {
    classSelect.disabled = true;
  }
}

function setupEventListeners() {
  const searchInput = document.querySelector<HTMLInputElement>('#school-search-input')!;
  const searchResults = document.querySelector<HTMLUListElement>('#school-search-results')!;
  const selectedBox = document.querySelector<HTMLElement>('#selected-school-box')!;
  const clearBtn = document.querySelector<HTMLButtonElement>('#selected-school-clear')!;
  const gradeSelect = document.querySelector<HTMLSelectElement>('#grade-select')!;
  const classSelect = document.querySelector<HTMLSelectElement>('#class-select')!;
  const weekSelect = document.querySelector<HTMLSelectElement>('#week-select')!;
  const themeSelect = document.querySelector<HTMLSelectElement>('#theme-select')!;
  const widthInput = document.querySelector<HTMLInputElement>('#width-input')!;
  const heightInput = document.querySelector<HTMLInputElement>('#height-input')!;
  const copyBtn = document.querySelector<HTMLButtonElement>('#copy-code-btn')!;
  const copyFeedback = document.querySelector<HTMLElement>('#copy-feedback')!;

  let debounceTimer: number | undefined;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    schoolGeneration++;
    timetableController?.abort();
    selectedSchool = null;
    cachedRecords = [];
    const generation = ++searchGeneration;
    searchController?.abort();
    const q = searchInput.value.trim();
    if (q.length < 2) {
      searchResults.hidden = true;
      searchResults.replaceChildren();
      return;
    }
    debounceTimer = window.setTimeout(async () => {
      searchController = new AbortController();
      try {
        const res = await searchSchools(q, searchController.signal);
        if (generation !== searchGeneration) return;
        searchResults.replaceChildren();
        if (res.schools.length === 0) {
          const li = document.createElement('li');
          li.className = 'builder-search-item';
          li.textContent = '검색 결과가 없습니다.';
          searchResults.append(li);
        } else {
          for (const s of res.schools) {
            const li = document.createElement('li');
            li.className = 'builder-search-item';
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'builder-search-item-button';
            button.style.cssText = 'display:block;width:100%;padding:0;border:0;background:transparent;color:inherit;text-align:left;font:inherit;cursor:pointer';
            const strong = document.createElement('strong');
            strong.textContent = s.name;
            const span = document.createElement('span');
            span.textContent = s.region;
            button.append(strong, span);
            button.addEventListener('click', () => onSelectSchool(s));
            li.append(button);
            searchResults.append(li);
          }
        }
        searchResults.hidden = false;
      } catch (err) {
        if ((err as Error)?.name !== 'AbortError') {
          console.error(err);
        }
      }
    }, 300);
  });

  clearBtn.addEventListener('click', () => {
    schoolGeneration++;
    timetableController?.abort();
    selectedSchool = null;
    cachedRecords = [];
    selectedBox.hidden = true;
    searchInput.hidden = false;
    searchInput.value = '';
    searchInput.focus();
    gradeSelect.disabled = true;
    gradeSelect.value = '';
    classSelect.disabled = true;
    classSelect.replaceChildren(new Option('선택', ''));
    updateCodeAndPreview();
  });

  gradeSelect.addEventListener('change', () => {
    const g = Number(gradeSelect.value);
    if (g) populateClasses(g);
    updateCodeAndPreview();
  });

  classSelect.addEventListener('change', updateCodeAndPreview);
  weekSelect.addEventListener('change', updateCodeAndPreview);
  themeSelect.addEventListener('change', updateCodeAndPreview);
  widthInput.addEventListener('input', updateCodeAndPreview);
  heightInput.addEventListener('input', updateCodeAndPreview);

  copyBtn.addEventListener('click', async () => {
    const codeOutput = document.querySelector<HTMLTextAreaElement>('#code-output')!;
    try {
      await navigator.clipboard.writeText(codeOutput.value);
      copyFeedback.textContent = '클립보드에 복사되었습니다!';
    } catch {
      codeOutput.select();
      document.execCommand('copy');
      copyFeedback.textContent = '복사되었습니다!';
    }
    setTimeout(() => { copyFeedback.textContent = ''; }, 3000);
  });

  updateCodeAndPreview();
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  window.addEventListener('DOMContentLoaded', setupEventListeners);
}
