<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import { suggestionsEnabled } from './suggestions-config';
  import MealsPanel from './MealsPanel.svelte';
  import CalendarNav from './CalendarNav.svelte';
  import SchoolSelector from './SchoolSelector.svelte';
  import ShareTools from './ShareTools.svelte';
  import SettingsPanel from './SettingsPanel.svelte';
  import TimetablePanel from './TimetablePanel.svelte';
  import { readAllergies, readMealPreferences, saveMealPreferences as persistMealPreferences, saveAllergies, readMealAllergyFilter, saveMealAllergyFilter, readSchoolPreference, readTheme, writeTheme, readAnimations, writeAnimations, readMealSchool, writeMealSchool } from './preferences';
  import type { MealAllergyFilter } from './meal-filter';
  import { getNavigationFromHistory, parseNavigationState, replaceNavigationState, pushNavigationState, subscribeNavigation, type NavigationState } from './navigation';
  import { saveSelection, readSelection, gradesInTimetable, classesInGrade, createSelectionState, createSharedSelectionSession, validateSharedCandidate, type PendingSharedClass } from './selection';
  import { currentKoreaDate, monday, addDays, clampWeek } from './date';
  import { resolveMealSchool, mealSchoolCandidates } from './neis-match';
  import { trackPageView } from './analytics';
  import { shareClassUrl, readSharedClass } from './sharing';
  import { saveTimetablePdf, saveTimetablePng, shareTimetablePng, type ExportOptions } from './export-png';
  import { createTimetableSession } from './timetable-cache';
  import { createMealSession } from './meal-session';
  import { createSchoolSearchSession } from './school-search-session';
  import { classLessons, teacherLessons, teacherNamesInTimetable, teacherSuggestions as findTeacherSuggestions, selectedTeacherName as findSelectedTeacherName, gradeLessons, comparisonClasses, missingWeekdayDates, observedClassCount as countObservedClasses, subjectNamesInTimetable } from './timetable-view';
  import { applySourceLessonStarts, dailyLessonOverview, koreaClockMinutes, parseLessonTimes, parseWeekdayLessonTimes, parseSourceLessonPreference, lessonTimesForDate, type LessonTimes, type WeekdayLessonTimes } from './lesson-times';
  import { createClassDisplayPreferences, createSchoolDisplayPreferences, defaultDisplaySettings, displayTeacher, subjectColor, subjectTextColor, type ColorMode, type DisplaySettings } from './personalization';
  import { createSettingsBackup, parseSettingsBackup, saveSchoolSettingsBackup, saveLessonTimePreferences, MAX_SETTINGS_BACKUP_BYTES } from './settings-backup';
  import { apiNotConfigured, getMeals, getTimetable, searchSchools, searchNeisSchools, timetableSubscriptionUrl, type Meal, type NeisSchool, type School, type TimetableRecord, type TimetableResponse } from './api';

  let school: School | null = null;
  let neis: NeisSchool | null = null;
  let schoolQuery = '';
  let schoolResults: School[] = [];
  let neisResults: NeisSchool[] = [];
  let schoolSearchState = '';
  let schoolSearchRetryable = false;
  let neisSearchState = '';
  let neisLoading = false;
  let schoolEditorOpen = true;
  let view: 'timetable' | 'meals' | 'settings' = 'timetable';
  let SuggestionsComponent: typeof import('./Suggestions.svelte').default | null = null;
  let suggestionsLoading = false;
  let suggestionsLoadFailed = false;
  let suggestionsRetryMessage = '';
  let suggestionsRetryPending = false;
  let previousView: 'timetable' | 'meals' | 'settings' = view;
  let timetableView: 'today' | 'week' | 'grade' | 'teacher' = 'week';
  let teacherQuery = '';
  let displaySettings: DisplaySettings = defaultDisplaySettings();
  let schoolDisplaySettings: DisplaySettings = defaultDisplaySettings();
  let useClassDisplay = false;
  const classDisplayPreferences = createClassDisplayPreferences(() => localStorage);
  const schoolDisplayPreferences = createSchoolDisplayPreferences(() => localStorage);
  let lessonTimes: LessonTimes = {};
  let weekdayLessonTimes: WeekdayLessonTimes = {};
  let weekdayTimeDrafts: WeekdayLessonTimes = {};
  let lessonTimeDrafts: Record<number, { start: string; end: string }> = {};
  let sourceLessonAutoEnabled = true;
  let sourceLessonApplied: Record<string, string> = {};
  let sourceLessonPrevious: LessonTimes = {};
  let autoSourceDraftPeriods: number[] = [];
  let editedSourcePeriods = new Set<number>();
  let appliedSourceKey = '';
  let lessonTimeState = '';
  let settingsBackupState = '';
  let allergySelection: number[] = [];
  let mealAllergyFilter: MealAllergyFilter = 'all';
  let openAllergySettingsRequest = 0;
  let tableRefreshState = '';
  let timetableCheckedAt = '';
  let exportState = '';
  let imageShareCancelled = false;
  let exportBusy = false;
  let shareUrl = '';
  let shareState = '';
  let subscriptionUrl = '';
  let subscriptionMode: import('./api').SubscriptionMode = 'summary';
  let subscriptionState = '';
  let subscriptionTimesConsent = false;
  let subscriptionPanelOpen = false;
  let grade = 1;
  let classroom = 1;
  let classroomDraft = '1';
  let classError = false;
  let today = currentKoreaDate(new Date());
  let clockMinute = koreaClockMinutes(new Date());
  let selectedDay = today;
  let current = monday(today);
  let week = current;
  const selectionState = createSelectionState({ school, grade, classroom, week }, (state) => {
    if (school !== state.school) school = state.school;
    if (grade !== state.grade) grade = state.grade;
    if (classroom !== state.classroom) classroom = state.classroom;
    if (week !== state.week) week = state.week;
  });
  let mealDate = today;
  let mealDateDraft = today;
  let mealView: 'day' | 'week' = 'day';
  let enabledMealTypes = ['조식', '중식', '석식'];
  let showAllergenNumbers = true;
  let dateError = '';
  let timetableDateError = '';
  let sharedClassState = '';
  let pendingSharedClass: PendingSharedClass | null = null;
  let sharedCandidateRequest: AbortSignal | null = null;
  let sharedSchoolChecking = false;
  const sharedSelection = createSharedSelectionSession((state) => { pendingSharedClass = state.pending; sharedSchoolChecking = state.checking; });
  let classActionsReady = false;
  let inputFocused = false;
  let theme: 'light' | 'dark' | 'system' = 'light';
  let animationsEnabled = true;
  let systemDark = false;
  let analyticsReady = false;
  let navigationReady = false;
  let applyingNavigation = false;
  let timetable: TimetableResponse | null = null;
  let timetableFromDevice = false;
  let meals: Meal[] = [];
  let hasMeals = false;
  let mealsStale = false;
  let tableState = '';
  let mealState = '';
  let tableLoading = false;
  let mealLoading = false;
  const mealTypes = ['조식', '중식', '석식'];
  const refreshInterval = 30 * 60 * 1000;
  const timetableSession = createTimetableSession((state) => {
    if (timetable !== state.data) timetable = state.data;
    if (timetableFromDevice !== state.fromDevice) timetableFromDevice = state.fromDevice;
    if (tableLoading !== state.loading) tableLoading = state.loading;
    if (tableState !== state.error) tableState = state.error;
    if (timetableRefreshAt !== state.refreshAt) timetableRefreshAt = state.refreshAt;
  });
  let timetableRefreshAt = 0;
  let mealsRefreshAt = 0;
  const schoolSearchSession = createSchoolSearchSession((results, message, retryable = false) => { schoolResults = results; schoolSearchState = message; schoolSearchRetryable = retryable; }, () => localStorage);
  const mealSession = createMealSession((state) => {
    if (neis !== state.neis) neis = state.neis;
    neisResults = state.candidates; neisSearchState = state.searchState; neisLoading = state.neisLoading;
    meals = state.meals; hasMeals = state.hasMeals; mealsStale = state.stale; mealState = state.error;
    mealLoading = state.loading; mealsRefreshAt = state.refreshAt;
  });

  $: filtered = classLessons(timetable?.records ?? [], grade, classroom);
  $: dayRecords = (timetable?.records ?? []).filter((r) => r.date === selectedDay);
  $: selectedClassLessons = classLessons(dayRecords, grade, classroom).sort((a, b) => Number(a.period) - Number(b.period));
  $: activeSourceLessonStarts = school && timetable?.schoolId === school.id && timetable.weekStart === week && !timetable.stale && !timetableFromDevice ? timetable.sourceLessonStarts : undefined;
  $: selectedDayTimes = lessonTimesForDate(lessonTimes, weekdayLessonTimes, selectedDay, sourceLessonAutoEnabled ? activeSourceLessonStarts : undefined);
  $: sourceLessonKey = sourceLessonAutoEnabled && activeSourceLessonStarts ? `${school?.id}:${week}:${JSON.stringify(activeSourceLessonStarts)}` : '';
  $: if (sourceLessonKey !== appliedSourceKey) {
    appliedSourceKey = sourceLessonKey;
    applyFreshSourceStarts(sourceLessonKey && activeSourceLessonStarts ? activeSourceLessonStarts : {});
  }
  $: dayOverview = dailyLessonOverview(selectedClassLessons, selectedDayTimes, clockMinute, selectedDay === today);
  $: shownClassLessons = displaySettings.endedLessonMode === 'hide' ? selectedClassLessons.filter((item) => !dayOverview.completed.includes(Number(item.period))) : selectedClassLessons;
  $: gradeRecords = gradeLessons(dayRecords, grade);
  $: comparableClasses = comparisonClasses(gradeRecords);
  $: teacherNames = teacherNamesInTimetable(timetable?.records ?? []);
  $: observedClassCount = countObservedClasses(timetable?.records ?? []);
  $: subjectNames = subjectNamesInTimetable(timetable?.records ?? []);
  $: teacherSuggestions = findTeacherSuggestions(teacherNames, teacherQuery, (name) => displayTeacher(name, displaySettings));
  $: if (view !== previousView) {
    previousView = view;
    suggestionsLoadFailed = false;
    if (view === 'settings' && suggestionsEnabled) void loadSuggestions();
  }

  async function loadSuggestions() {
    if (SuggestionsComponent || suggestionsLoadFailed) return;
    if (suggestionsLoading) { suggestionsRetryPending = true; return; }
    suggestionsLoading = true;
    suggestionsRetryPending = false;
    try {
      SuggestionsComponent = (await import('./Suggestions.svelte')).default;
    } catch {
      suggestionsLoadFailed = true;
    } finally {
      suggestionsLoading = false;
      if (suggestionsRetryPending && view === 'settings' && !SuggestionsComponent) {
        suggestionsLoadFailed = false;
        void loadSuggestions();
      }
    }
  }
  function retrySuggestionsAfterReload() {
    if (JSON.stringify(lessonTimeDrafts) !== JSON.stringify(lessonTimes) ||
        JSON.stringify(weekdayTimeDrafts) !== JSON.stringify(weekdayLessonTimes)) {
      suggestionsRetryMessage = '작성 중인 교시 시각을 저장하거나 초기화한 뒤 다시 시도해 주세요.';
      return;
    }
    try {
      sessionStorage.setItem('opencigan-retry-suggestions', '1');
      window.location.reload();
    } catch {
      suggestionsRetryMessage = '다시 시도하려면 설정을 저장한 뒤 페이지를 새로고침해 주세요.';
    }
  }
  $: selectedTeacherName = findSelectedTeacherName(teacherNames, teacherQuery, (name) => displayTeacher(name, displaySettings));
  $: selectedTeacherRecords = teacherLessons(timetable?.records ?? [], selectedTeacherName);
  $: classActionsReady = !!school && timetable?.schoolId === school.id && timetable.weekStart === week && filtered.length > 0 && !classError && !pendingSharedClass && !sharedSchoolChecking;
  $: canExport = !!school && timetable?.schoolId === school.id && timetable.weekStart === week && !classError && !pendingSharedClass && !sharedSchoolChecking && (timetableView === 'teacher' ? selectedTeacherRecords.length > 0 : classActionsReady && (timetableView === 'week' || timetableView === 'today' && selectedClassLessons.length > 0));
  $: teacherPeriods = Array.from({ length: Math.max(0, ...selectedTeacherRecords.map((r) => Number(r.period))) }, (_, i) => i + 1);
  $: teacherDates = Array.from({ length: 5 }, (_, i) => addDays(week, i));
  $: availableGrades = gradesInTimetable(timetable?.records ?? [], school && /(?:중학교|고등학교)/.test(school.name) ? 3 : 6);
  $: gradeOptions = availableGrades.length ? availableGrades : school && /(?:중학교|고등학교)/.test(school.name) ? [1, 2, 3] : [1, 2, 3, 4, 5, 6];
  $: availableClasses = classesInGrade(timetable?.records ?? [], grade);
  $: weekendClasses = filtered.some((r) => r.date === addDays(week, 5) || r.date === addDays(week, 6));
  $: dates = Array.from({ length: weekendClasses ? 7 : 5 }, (_, i) => addDays(week, i));
  $: missingWeekdays = missingWeekdayDates(filtered, dates);
  $: periods = Array.from({ length: Math.max(0, ...filtered.map((r) => Number(r.period))) }, (_, i) => i + 1);
  $: lessonTimePeriods = Array.from({ length: Math.max(8, ...[
    ...(timetable?.records ?? []).map((r) => Number(r.period)),
    ...Object.keys(lessonTimeDrafts).map(Number),
    ...(school && timetable?.schoolId === school.id && timetable.weekStart === week ? Object.keys(timetable.sourceLessonStarts ?? {}).map(Number) : []),
  ].filter((period) => Number.isInteger(period) && period > 0 && period <= 20)) }, (_, i) => i + 1);
  $: visibleMealTypes = mealTypes.filter((type) => enabledMealTypes.includes(type));
  $: mealDates = Array.from({ length: 7 }, (_, index) => addDays(monday(mealDate), index));
  $: if (school && neis && (view === 'meals' || view === 'timetable' && timetableView === 'today')) {
    view; timetableView; selectedDay; mealDate;
    loadMeals();
  }
  $: isDark = themeIsDark(theme, systemDark);
  $: if (analyticsReady && view !== 'settings') trackPageView(view === 'meals' ? '/meals' : '/timetable');
  $: if (navigationReady && !applyingNavigation && !classError && !pendingSharedClass) {
    let navigationUrl: string | undefined;
    if (school && readSharedClass(window.location.hash)) {
      const nextUrl = new URL(window.location.href);
      nextUrl.hash = new URL(shareClassUrl(nextUrl.href, school, Number(grade), Number(classroom))).hash;
      navigationUrl = nextUrl.href;
    }
    pushNavigationState({ version: 1, view, timetableView, school, grade: Number(grade), classroom: Number(classroom), week, selectedDay, mealDate }, current, undefined, navigationUrl);
  }

  function applyNavigation(state: NavigationState | null) {
    state = parseNavigationState(state, monday(currentKoreaDate(new Date())));
    if (!state) return;
    applyingNavigation = true;
    cancelSharedSelection();
    const previousSchool = school?.id;
    const previousWeek = week;
    selectionState.update({ grade: state.grade, classroom: state.classroom, week: state.week }); classroomDraft = String(classroom); classError = false;
    selectedDay = state.selectedDay; mealDate = state.mealDate; mealDateDraft = mealDate; dateError = '';
    view = state.view; timetableView = state.timetableView;
    if (state.school && previousSchool !== state.school.id) chooseSchool(state.school, true);
    else if (!state.school) {
      timetableSession.cancel(); mealSession.cancel();
      selectionState.update({ school: null }); timetableSession.update({ data: null, loading: false }); mealSession.update({ neis: null, meals: [], loading: false }); schoolEditorOpen = true;
      try { localStorage.removeItem('opensigan-school'); } catch { /* 현재 탐색을 유지합니다. */ }
    } else {
      if (previousWeek !== week) loadTimetable(false, true, true);
      else ensureAvailableClass();
      loadMeals();
      persistClassSelection();
    }
    shareUrl = ''; subscriptionUrl = ''; shareState = ''; subscriptionState = '';
    applyingNavigation = false;
  }

  function dateText(key: string, options: Intl.DateTimeFormatOptions = { month: 'numeric', day: 'numeric' }) {
    return new Intl.DateTimeFormat('ko-KR', { ...options, timeZone: 'UTC' }).format(new Date(key + 'T00:00:00Z'));
  }
  function shortDate(key: string) {
    const [, month, day] = key.split('-').map(Number);
    return `${month}.${day}`;
  }
  function timeText(value: string | null | undefined, withSeconds = false) {
    if (!value || Number.isNaN(Date.parse(value))) return '정보 없음';
    return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: withSeconds ? '2-digit' : undefined }).format(new Date(value));
  }
  function errorText(error: unknown) { return error instanceof Error ? error.message : '요청을 완료하지 못했어요.'; }

  function themeIsDark(preference: 'light' | 'dark' | 'system', prefersDark: boolean) {
    return preference === 'dark' || (preference === 'system' && prefersDark);
  }

  $: subjectStyle = ((settings: DisplaySettings) => (subject: string | null | undefined) => {
    const color = subjectColor(subject, settings);
    return color ? `background-color:${color};color:${subjectTextColor(color)}` : undefined;
  })(displaySettings);
  $: classDisplayKey = school ? `opensigan-class-display:${school.id}:${grade}:${classroom}` : '';
  $: if (classDisplayKey) loadClassDisplay(classDisplayKey, schoolDisplaySettings);

  function loadClassDisplay(key: string, fallback: DisplaySettings) {
    const value = classDisplayPreferences.read(key, fallback);
    useClassDisplay = value.enabled;
    displaySettings = value.settings;
  }
  function setClassDisplay(enabled: boolean) {
    if (!classDisplayKey) return;
    classDisplayPreferences.set(classDisplayKey, enabled ? displaySettings : null);
    loadClassDisplay(classDisplayKey, schoolDisplaySettings);
  }
  function saveDisplaySettings(next: DisplaySettings) {
    displaySettings = next;
    if (!school) return;
    if (useClassDisplay) {
      classDisplayPreferences.set(classDisplayKey, next);
    } else {
      schoolDisplaySettings = next;
      try { schoolDisplayPreferences.set(school.id, next); }
      catch { /* 현재 설정은 페이지에서 유지됩니다. */ }
    }
  }
  function saveAlias(kind: 'subject' | 'teacher', key: string, value: string) {
    if (!key) return;
    const property = kind === 'subject' ? 'subjectAliases' : 'teacherAliases';
    const aliases = { ...displaySettings[property] };
    if (value.trim()) aliases[key] = value.trim().slice(0, 60);
    else delete aliases[key];
    saveDisplaySettings({ ...displaySettings, [property]: aliases });
  }
  function saveSubjectColor(subject: string, value: string) {
    if (!subject || !/^#[0-9a-fA-F]{6}$/.test(value)) return;
    saveDisplaySettings({ ...displaySettings, subjectColors: { ...displaySettings.subjectColors, [subject]: value } });
  }
  function setColorMode(value: string) {
    if (value === 'none' || value === 'auto' || value === 'custom') saveDisplaySettings({ ...displaySettings, colorMode: value as ColorMode });
  }
  function clearSubjectColors() { saveDisplaySettings({ ...displaySettings, subjectColors: {} }); }

  function resetDisplaySettings() {
    if (useClassDisplay) {
      setClassDisplay(false);
      settingsBackupState = '현재 학급에 학교 기본 설정을 다시 적용했어요.';
    } else {
      saveDisplaySettings(defaultDisplaySettings());
      settingsBackupState = '현재 학교의 시간표 표시 설정을 초기화했어요.';
    }
  }
  function downloadSettingsBackup(classOnly = false) {
    if (!school) return;
    const scope = classOnly ? { grade: Number(grade), classroom: Number(classroom) } : undefined;
    const contents = createSettingsBackup(school.id, classOnly ? displaySettings : schoolDisplaySettings, lessonTimes, scope, weekdayLessonTimes);
    const url = URL.createObjectURL(new Blob([contents], { type: 'application/json;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `opencigan-settings-${school.id.replace(/[^a-zA-Z0-9_-]/g, '-')}${scope ? `-${scope.grade}-${scope.classroom}` : ''}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    settingsBackupState = classOnly ? '현재 학급의 표시 설정을 파일로 저장했어요.' : '현재 학교의 표시 설정과 교시 시각을 파일로 저장했어요.';
  }
  async function importSettingsFile(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file || !school) return;
    const schoolId = school.id;
    const scope = { grade: Number(grade), classroom: Number(classroom) };
    const targetClass = classDisplayKey;
    try {
      if (file.size > MAX_SETTINGS_BACKUP_BYTES) throw new Error('설정 파일은 64KB 이하여야 해요.');
      const backup = parseSettingsBackup(await file.text(), schoolId, scope);
      if (school?.id !== schoolId) throw new Error('학교가 변경되어 설정을 적용하지 않았어요.');
      if (backup.scoped) {
        if (targetClass !== classDisplayKey || classError) throw new Error('학급이 변경되어 설정을 적용하지 않았어요.');
        try { classDisplayPreferences.restore(targetClass, backup.displaySettings); }
        catch { throw new Error('브라우저 저장소에 설정을 저장하지 못했어요.'); }
        loadClassDisplay(targetClass, schoolDisplaySettings);
        settingsBackupState = '현재 학급의 표시 설정을 복원했어요.';
        return;
      }
      const restoredWeekdays = parseWeekdayLessonTimes(backup.weekdayLessonTimes ?? weekdayLessonTimes, backup.lessonTimes);
      if (!restoredWeekdays) throw new Error('기존 요일별 시각이 백업의 공통 시각과 겹쳐 복원하지 않았어요.');
      saveSchoolSettingsBackup(localStorage, schoolId, backup.displaySettings, backup.lessonTimes, restoredWeekdays);
      schoolDisplayPreferences.markSaved(schoolId);
      schoolDisplaySettings = backup.displaySettings;
      lessonTimes = backup.lessonTimes;
      sourceLessonApplied = {};
      sourceLessonPrevious = {};
      try { localStorage.setItem(`opensigan-source-lesson-preference:${schoolId}`, JSON.stringify({ enabled: sourceLessonAutoEnabled, applied: {}, previous: {} })); } catch { /* 복원된 설정은 현재 화면에 적용합니다. */ }
      weekdayLessonTimes = restoredWeekdays;
      weekdayTimeDrafts = { ...weekdayLessonTimes };
      lessonTimeDrafts = { ...backup.lessonTimes };
      lessonTimeState = '';
      settingsBackupState = '현재 학교의 설정을 복원했어요.';
    } catch (error) {
      settingsBackupState = errorText(error);
    }
  }

  function editLessonTime(period: number, part: 'start' | 'end', value: string) {
    lessonTimeDrafts = { ...lessonTimeDrafts, [period]: { start: lessonTimeDrafts[period]?.start ?? '', end: lessonTimeDrafts[period]?.end ?? '', [part]: value } };
    editedSourcePeriods.add(period);
    autoSourceDraftPeriods = autoSourceDraftPeriods.filter((item) => item !== period);
    lessonTimeState = '';
  }
  function applyLessonTimeRules(value: LessonTimes) {
    lessonTimeDrafts = value;
    lessonTimeState = '계산된 시각을 입력했어요. 확인 후 시각 저장을 눌러 주세요.';
  }
  function applyFreshSourceStarts(source: Record<string, string>) {
    lessonTimeDrafts = applySourceLessonStarts(lessonTimeDrafts, source, lessonTimePeriods, autoSourceDraftPeriods);
    autoSourceDraftPeriods = lessonTimePeriods.filter((period) => !editedSourcePeriods.has(period) && !lessonTimes[period]?.start && lessonTimeDrafts[period]?.start === source[String(period)] && !lessonTimeDrafts[period]?.end);
  }
  function setSourceLessonAuto(enabled: boolean): boolean {
    if (!school || enabled === sourceLessonAutoEnabled) return true;
    const nextTimes = { ...lessonTimes };
    const nextDrafts = { ...lessonTimeDrafts };
    const nextApplied = enabled ? sourceLessonApplied : {};
    const nextPrevious = enabled ? sourceLessonPrevious : {};
    const nextAutoDraftPeriods = enabled ? autoSourceDraftPeriods : [];
    if (!enabled) {
      for (const [rawPeriod, start] of Object.entries(sourceLessonApplied)) {
        const period = Number(rawPeriod);
        if (nextTimes[period]?.start !== start) continue;
        const previous = sourceLessonPrevious[period];
        if (previous) { nextTimes[period] = previous; nextDrafts[period] = previous; }
        else { delete nextTimes[period]; delete nextDrafts[period]; }
      }
      for (const period of autoSourceDraftPeriods) {
        const entry = { ...nextDrafts[period] };
        if (!entry.end) { entry.start = ''; nextDrafts[period] = entry; }
      }
    }
    try {
      saveLessonTimePreferences(localStorage, school.id, nextTimes, weekdayLessonTimes, { enabled, applied: nextApplied, previous: nextPrevious });
      sourceLessonAutoEnabled = enabled;
      lessonTimes = nextTimes;
      lessonTimeDrafts = nextDrafts;
      sourceLessonApplied = nextApplied;
      sourceLessonPrevious = nextPrevious;
      autoSourceDraftPeriods = nextAutoDraftPeriods;
      editedSourcePeriods = new Set();
      return true;
    } catch (error) { lessonTimeState = errorText(error); return false; }
  }
  function useSourceStart(period: number) {
    const start = activeSourceLessonStarts?.[String(period)];
    if (!start) return;
    const entry = lessonTimeDrafts[period] ?? { start: '', end: '' };
    lessonTimeDrafts = { ...lessonTimeDrafts, [period]: { ...entry, start } };
    if (!sourceLessonApplied[String(period)]) {
      const previous = lessonTimes[period];
      if (previous) sourceLessonPrevious[period] = previous;
    }
    editedSourcePeriods.delete(period);
    autoSourceDraftPeriods = [...new Set([...autoSourceDraftPeriods.filter((item) => item !== period), period])];
    lessonTimeState = '';
  }
  function editWeekdayTime(day: number, period: number, part: 'start' | 'end', value: string) {
    const entry = weekdayTimeDrafts[day]?.[period] ?? { start: '', end: '' };
    weekdayTimeDrafts = { ...weekdayTimeDrafts, [day]: { ...weekdayTimeDrafts[day], [period]: { ...entry, [part]: value } } };
    lessonTimeState = '';
  }
  function clearWeekdayTime(day: number, period: number) {
    const entries = { ...weekdayTimeDrafts[day] }; delete entries[period];
    weekdayTimeDrafts = { ...weekdayTimeDrafts, [day]: entries };
    lessonTimeState = '';
  }
  function saveLessonTimes() {
    if (!school) return;
    const entries = Object.entries(lessonTimeDrafts).filter(([period, entry]) => (entry.start || entry.end) && !(autoSourceDraftPeriods.includes(Number(period)) && !entry.end));
    const parsed = parseLessonTimes(Object.fromEntries(entries));
    if (entries.length !== Object.keys(parsed).length) {
      lessonTimeState = '각 교시의 시작·종료 시각을 모두 입력하고, 시간 순서와 겹침 여부를 확인해 주세요.';
      return;
    }
    const weekday = parseWeekdayLessonTimes(weekdayTimeDrafts, parsed);
    if (!weekday) { lessonTimeState = '요일별 시작·종료 시각과 공통 시각의 순서·겹침을 확인해 주세요.'; return; }
    const lessonTimesBeforeSave = lessonTimes;
    const nextSourceLessonApplied = { ...sourceLessonApplied };
    const nextSourceLessonPrevious = { ...sourceLessonPrevious };
    for (const period of editedSourcePeriods) {
      delete nextSourceLessonApplied[String(period)];
      delete nextSourceLessonPrevious[period];
    }
    const incompleteSourcePeriods = autoSourceDraftPeriods.filter((period) => !parsed[period]);
    for (const period of autoSourceDraftPeriods.filter((period) => parsed[period])) {
      const sourceStart = activeSourceLessonStarts?.[String(period)];
      if (sourceStart && parsed[period]?.start === sourceStart) {
        nextSourceLessonApplied[String(period)] = sourceStart;
        const previous = lessonTimesBeforeSave[period];
        if (!nextSourceLessonPrevious[period] && previous) nextSourceLessonPrevious[period] = previous;
      }
    }
    try {
      saveLessonTimePreferences(localStorage, school.id, parsed, weekday, { enabled: sourceLessonAutoEnabled, applied: nextSourceLessonApplied, previous: nextSourceLessonPrevious });
      lessonTimes = parsed;
      weekdayLessonTimes = weekday;
      sourceLessonApplied = nextSourceLessonApplied;
      sourceLessonPrevious = nextSourceLessonPrevious;
      autoSourceDraftPeriods = incompleteSourcePeriods;
      editedSourcePeriods = new Set();
      lessonTimeState = '이 학교의 교시 시각을 저장했어요.';
      subscriptionUrl = ''; subscriptionPanelOpen = false; subscriptionTimesConsent = false;
    } catch (error) { lessonTimeState = errorText(error); }
  }
  function clearLessonTimes() {
    lessonTimeDrafts = {}; lessonTimes = {}; weekdayTimeDrafts = {}; weekdayLessonTimes = {}; lessonTimeState = '교시 시각을 초기화했어요.';
    sourceLessonApplied = {}; sourceLessonPrevious = {}; autoSourceDraftPeriods = []; editedSourcePeriods = new Set();
    subscriptionUrl = ''; subscriptionPanelOpen = false; subscriptionTimesConsent = false;
    if (school) { try { saveLessonTimePreferences(localStorage, school.id, {}, {}); localStorage.setItem(`opensigan-source-lesson-preference:${school.id}`, JSON.stringify({ enabled: sourceLessonAutoEnabled, applied: {}, previous: {} })); } catch { lessonTimeState = '현재 화면에만 적용됐어요. 브라우저 저장소를 확인해 주세요.'; } }
  }

  function toggleAllergy(id: number, checked: boolean) {
    allergySelection = checked ? [...new Set([...allergySelection, id])].sort((a, b) => a - b) : allergySelection.filter((value) => value !== id);
    try { saveAllergies(localStorage, allergySelection); } catch { /* 설정은 현재 페이지에서 유지됩니다. */ }
  }
  function setMealAllergyFilter(value: string) {
    if (value !== 'all' && value !== 'marked' && value !== 'unmarked') return;
    mealAllergyFilter = value;
    try { saveMealAllergyFilter(localStorage, value); } catch { /* 설정은 현재 페이지에서 유지됩니다. */ }
  }
  function openAllergySettings() { view = 'settings'; openAllergySettingsRequest += 1; }

  function saveMealPreferences() {
    try { persistMealPreferences(localStorage, { view: mealView, types: enabledMealTypes, showAllergenNumbers }); }
    catch { /* 설정은 현재 페이지에서 유지됩니다. */ }
  }
  function setMealView(value: 'day' | 'week') { mealView = value; saveMealPreferences(); }
  function toggleMealType(type: string, checked: boolean) {
    const next = checked ? [...enabledMealTypes, type] : enabledMealTypes.filter((item) => item !== type);
    if (!next.length) return;
    enabledMealTypes = mealTypes.filter((item) => next.includes(item));
    saveMealPreferences();
  }
  function setAllergenNumbersVisible(value: boolean) { showAllergenNumbers = value; saveMealPreferences(); }

  function findSchool() {
    schoolSearchSession.find(() => schoolQuery, searchSchools, errorText);
  }
  function cancelSharedSelection() {
    sharedCandidateRequest = null;
    sharedSelection.cancel();
    sharedClassState = '';
    subscriptionPanelOpen = false;
  }
  function persistSelection(selection: { school?: School; grade?: number; classroom: number }) {
    try { saveSelection(localStorage, selection); } catch { /* 저장소 접근 자체가 차단될 수 있습니다. */ }
  }
  function persistClassSelection() {
    if (!school || classError || pendingSharedClass) return;
    persistSelection({ school, grade, classroom });
  }
  function chooseSchool(value: School, keepClass = false, keepSharedValidation = false, shouldPersistSelection = true) {
    tableRefreshState = '';
    exportState = '';
    if (!keepSharedValidation) cancelSharedSelection();
    sharedClassState = '';
    if (selectionState.prepareSchool(value, keepClass, keepSharedValidation)) classError = false;
    classroomDraft = String(classroom);
    shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = '';
    schoolSearchSession.cancel(); mealSession.cancel();
    selectionState.update({ school: value }); schoolQuery = value.name; schoolResults = []; schoolSearchState = ''; schoolSearchRetryable = false; schoolEditorOpen = false;
    teacherQuery = '';
    schoolDisplaySettings = schoolDisplayPreferences.read(value.id, defaultDisplaySettings());
    try { lessonTimes = readSchoolPreference(localStorage, 'opensigan-lesson-times:', value.id, parseLessonTimes, () => ({})); }
    catch { lessonTimes = {}; }
    try { weekdayLessonTimes = readSchoolPreference(localStorage, 'opensigan-weekday-lesson-times:', value.id, (raw) => parseWeekdayLessonTimes(raw, lessonTimes) ?? {}, () => ({})); }
    catch { weekdayLessonTimes = {}; }
    weekdayTimeDrafts = { ...weekdayLessonTimes };
    lessonTimeDrafts = { ...lessonTimes }; lessonTimeState = '';
    try {
      const preference = parseSourceLessonPreference(JSON.parse(localStorage.getItem(`opensigan-source-lesson-preference:${value.id}`) ?? 'null'));
      sourceLessonAutoEnabled = preference.enabled;
      sourceLessonApplied = preference.applied;
      sourceLessonPrevious = preference.previous;
    } catch { sourceLessonAutoEnabled = true; sourceLessonApplied = {}; sourceLessonPrevious = {}; }
    autoSourceDraftPeriods = []; editedSourcePeriods = new Set(); appliedSourceKey = '';
    subscriptionTimesConsent = false;
    settingsBackupState = '';
    mealSession.reset();
    if (shouldPersistSelection) {
      persistSelection({ school: value, grade, classroom });
    }
    loadTimetable(false, true, true);
    if (school?.id !== value.id) return;
    try {
      const candidate = readMealSchool(localStorage, value.id);
      if (candidate && resolveMealSchool(value, [candidate])) { chooseNeis(candidate); return; }
    } catch { /* 사용할 수 없는 저장 정보는 다시 조회합니다. */ }
    void connectMeals(value);
  }
  async function connectMeals(value: School | null = school) {
    if (!value) return;
    await mealSession.connect(value, () => school?.id, (name, signal) => searchNeisSchools(name, signal),
      (selected, candidates) => resolveMealSchool(selected, candidates),
      (selected, candidates) => mealSchoolCandidates(selected, candidates), chooseNeis, errorText);
  }
  function chooseNeis(value: NeisSchool) {
    mealSession.choose(value, (selected) => { if (school) writeMealSchool(localStorage, school.id, selected); }, loadMeals);
  }
  function replaceInvalidSharedAddress(fallback: { school: School | null; grade: number; classroom: number }) {
    if (typeof window.history?.replaceState !== 'function') return;
    const url = new URL(window.location.href);
    url.hash = fallback.school ? new URL(shareClassUrl(url.href, fallback.school, fallback.grade, fallback.classroom)).hash : '';
    window.history.replaceState(window.history.state, '', url.href);
  }
  function ensureAvailableClass() {
    if (pendingSharedClass && pendingSharedClass.schoolId === school?.id && !sharedCandidateRequest) {
      const pending = sharedSelection.consume()!;
      const outcome = selectionState.resolveShared(pending, timetable, timetableFromDevice, school && /(?:중학교|고등학교)/.test(school.name) ? 3 : 6);
      if (outcome.status === 'rolled-back') {
        replaceInvalidSharedAddress(outcome.fallback);
        const message = outcome.reason === 'missing'
          ? `공유 링크의 ${pending.grade}학년 ${pending.classroom}반이 선택한 주의 시간표 데이터에 없어 적용하지 않았어요.`
          : '시간표 데이터가 없어 공유 링크의 학년·반을 확인하지 못했어요.';
        if (outcome.fallback.school) {
          classError = false;
          chooseSchool(outcome.fallback.school, true);
          sharedClassState = message + ` 기존 ${outcome.fallback.school.name} ${outcome.fallback.grade}학년 ${outcome.fallback.classroom}반을 유지했어요.`;
        } else {
          selectionState.update({ grade: pending.grade, classroom: pending.classroom });
          classroomDraft = String(classroom);
          classError = true;
          schoolEditorOpen = true;
          sharedClassState = message + ' 시간표에서 확인할 수 있는 학급을 선택해 주세요.';
        }
        return;
      }
      classError = false;
      classroomDraft = String(classroom);
      sharedClassState = '';
      if (school) persistSelection({ school, grade, classroom });
      return;
    }
    const changed = selectionState.reconcile(timetable?.records ?? [], school && /(?:중학교|고등학교)/.test(school.name) ? 3 : 6);
    classroomDraft = String(classroom);
    if (!changed) return;
    classError = false;
    shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = '';
    persistSelection({ grade, classroom });
  }
  function loadTimetable(preserve = false, reuseCachedWeek = false, validateClass = false) {
    validateClass = validateClass || !!pendingSharedClass;
    if (!preserve) {
      timetableCheckedAt = '';
      shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = ''; subscriptionPanelOpen = false;
    }
    timetableSession.load({
      schoolId: school?.id, week, preserve, reuseCachedWeek, validateClass, refreshInterval,
      now: () => Date.now(), storage: () => localStorage,
      current: () => ({ schoolId: school?.id, week }), fetch: getTimetable,
      validate: ensureAvailableClass, classError: () => classError, errorText,
      onSuccess: (data) => {
        if (tableRefreshState === '갱신 중') {
          timetableCheckedAt = new Date().toISOString();
          tableRefreshState = data.stale ? '서버에 연결했어요. 저장된 시간표를 표시 중이에요.' : '새로고침 완료';
        }
      },
      onFailure: () => { if (tableRefreshState === '갱신 중') tableRefreshState = '새로고침 실패'; },
    });
  }
  function selectTimetableView(value: typeof timetableView) {
    timetableDateError = '';
    timetableView = value;
    exportState = '';
    if (value === 'today' || value === 'grade') selectedDay = week === current ? today : week;
  }
  function loadMeals(preserve = false) {
    if (!school || !neis) return;
    const from = monday(view === 'timetable' && timetableView === 'today' ? selectedDay : mealDate);
    mealSession.load(neis.id, from, addDays(from, 6), preserve, () => Date.now(), refreshInterval, getMeals, errorText);
  }
  function refreshCalendar(refreshData = true) {
    const previousToday = today;
    clockMinute = koreaClockMinutes(new Date());
    today = currentKoreaDate(new Date()); current = monday(today);
    const validWeek = clampWeek(week, current);
    if (selectedDay === previousToday) selectedDay = today;
    if (validWeek !== week) {
      cancelSharedSelection();
      selectionState.update({ week: validWeek });
      selectedDay = selectedDay < week ? week : selectedDay > addDays(week, 6) ? addDays(week, 6) : selectedDay;
      if (refreshData) {
        loadTimetable();
      }
    }
    if (mealDate === previousToday && today !== previousToday) { mealDate = today; mealDateDraft = today; if (refreshData) loadMeals(); }
    if (refreshData && document.visibilityState === 'visible') {
      const now = Date.now();
      if (school && !tableLoading && now >= timetableRefreshAt) loadTimetable(true);
      if (school && neis && !mealLoading && now >= mealsRefreshAt) loadMeals(true);
    }
  }
  function changeWeek(delta: number) {
    timetableDateError = '';
    refreshCalendar(false); const next = addDays(week, delta * 7);
    if (next < current || next > addDays(current, 7)) return;
    if (next !== week) cancelSharedSelection();
    tableRefreshState = ''; exportState = ''; teacherQuery = ''; selectionState.update({ week: next }); selectedDay = week === current ? today : week; loadTimetable(false, true);
  }
  function currentWeek() { timetableDateError = ''; refreshCalendar(false); const preserve = week === current; tableRefreshState = ''; if (!preserve) { cancelSharedSelection(); teacherQuery = ''; } selectionState.update({ week: current }); selectedDay = today; loadTimetable(preserve); }
  function changeMealDate(delta: number) {
    const next = addDays(mealDate, delta);
    if (!validMealDate(next)) { dateError = '1900년 이후의 올바른 날짜를 선택해 주세요.'; return; }
    mealDate = next; mealDateDraft = next; dateError = ''; loadMeals();
  }
  function selectTimetableDate(event: Event, editing = false) {
    const input = event.currentTarget as HTMLInputElement;
    const value = input.value;
    if (value && input.validity.valid && value >= week && value <= addDays(week, 6)) {
      timetableDateError = '';
      if (selectedDay === value) return;
      selectedDay = value;
    } else if (editing) timetableDateError = '선택한 주의 날짜를 입력해 주세요.';
    else { input.value = selectedDay; timetableDateError = ''; }
  }
  function todayMeals() { refreshCalendar(); mealDate = today; mealDateDraft = today; dateError = ''; loadMeals(); }
  function selectMealTimetableDate(value: string) {
    refreshCalendar(false);
    if (!validMealDate(value)) return;
    const targetWeek = monday(value);
    if (targetWeek < current || targetWeek > addDays(current, 7)) return;
    const needsTimetable = targetWeek !== week || timetable?.weekStart !== targetWeek;
    if (targetWeek !== week) cancelSharedSelection();
    view = 'timetable'; timetableView = 'today'; selectionState.update({ week: targetWeek }); selectedDay = value;
    mealDate = value; mealDateDraft = value; dateError = '';
    if (needsTimetable) {
      tableRefreshState = ''; teacherQuery = '';
      loadTimetable(false, true);
    }
    loadMeals();
  }
  function updateMealDateDraft(event: Event) {
    if (dateError) dateError = '';
  }
  function validMealDate(value: string) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    if (!match) return false;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    if (year < 1900) return false;
    const date = new Date(0);
    date.setUTCHours(0, 0, 0, 0);
    date.setUTCFullYear(year, month - 1, day);
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
  }
  function selectMealDate(event: Event, editing = false) {
    const input = event.currentTarget as HTMLInputElement;
    const value = input.value;
    if (!validMealDate(value)) {
      if (editing) return;
      dateError = '1900년 이후의 올바른 날짜를 선택해 주세요.';
      mealDateDraft = mealDate;
      input.value = mealDate;
      return;
    }
    if (mealDate === value) { dateError = ''; return; }
    mealDate = value; mealDateDraft = value; dateError = ''; loadMeals();
  }
  function setTheme(value: string) {
    if (value !== 'light' && value !== 'dark' && value !== 'system') return;
    theme = value;
    try { writeTheme(localStorage, theme); } catch { /* 현재 선택은 저장 없이 유지합니다. */ }
  }
  function changeTheme() { setTheme(themeIsDark(theme, systemDark) ? 'light' : 'dark'); }
  function setAnimationsEnabled(enabled: boolean) {
    animationsEnabled = enabled;
    try { writeAnimations(localStorage, enabled); } catch { /* 현재 선택은 저장 없이 유지합니다. */ }
  }
  function refreshTimetable() {
    tableRefreshState = '갱신 중';
    loadTimetable(!!timetable);
  }
  function pngOptions(): ExportOptions | null {
    if (!timetable || !school || !canExport) return null;
    return {
      view: timetableView as ExportOptions['view'], schoolName: school.name,
      grade: Number(grade), classroom: Number(classroom), week, selectedDay,
      teacherName: selectedTeacherName, records: timetable.records, dark: isDark, displaySettings,
    };
  }
  async function exportTimetable(format: 'PNG' | 'PDF') {
    const options = pngOptions();
    if (!options || exportBusy) return;
    exportBusy = true;
    imageShareCancelled = false;
    exportState = format + ' 파일을 만드는 중…';
    try {
      await (format === 'PDF' ? saveTimetablePdf(options) : saveTimetablePng(options));
      exportState = format + ' 다운로드를 시작했어요.';
    } catch (error) { exportState = errorText(error); }
    finally { exportBusy = false; }
  }
  async function sharePng() {
    const options = pngOptions();
    if (!options || exportBusy) return;
    exportBusy = true;
    imageShareCancelled = false;
    exportState = '시간표 이미지를 만드는 중…';
    try {
      const result = await shareTimetablePng(options);
      imageShareCancelled = result === 'cancelled';
      exportState = result === 'shared' ? '시간표 이미지를 공유했어요.' : result === 'cancelled' ? '공유를 취소했어요.' : result === 'failed' ? '공유하지 못해 PNG 다운로드를 시작했어요.' : '이 브라우저는 이미지 공유를 지원하지 않아 PNG 다운로드를 시작했어요.';
    } catch (error) { exportState = errorText(error); }
    finally { exportBusy = false; }
  }
  function updateClass(event: Event) {
    cancelSharedSelection();
    shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = '';
    sharedClassState = '';
    const input = event.currentTarget as HTMLInputElement;
    const value = input.valueAsNumber;
    classroomDraft = input.value;
    classError = !selectionState.validClass(value, availableClasses);
  }
  function saveClass(event: Event) {
    updateClass(event);
    const input = event.currentTarget as HTMLInputElement;
    if (!classError) selectionState.commitClass(input.valueAsNumber);
    classroomDraft = String(classroom);
    input.value = classroomDraft;
    if (!classError) persistSelection({ classroom });
    persistClassSelection();
  }
  function saveGrade() {
    cancelSharedSelection();
    shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = '';
    sharedClassState = '';
    ensureAvailableClass();
    classError = false;
    persistSelection({ grade, classroom });
    persistClassSelection();
  }
  function selectGrade(event: Event) { selectionState.update({ grade: Number((event.currentTarget as HTMLSelectElement).value) }); saveGrade(); }
  function selectClass(event: Event) { selectionState.update({ classroom: Number((event.currentTarget as HTMLSelectElement).value) }); saveClassFromSelect(); }
  function saveClassFromSelect() {
    cancelSharedSelection();
    classroomDraft = String(classroom);
    classError = false;
    sharedClassState = '';
    shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = '';
    persistSelection({ classroom });
    persistClassSelection();
  }
  async function shareClass() {
    if (!school || !classActionsReady) return;
    if (shareUrl) { shareUrl = ''; shareState = ''; return; }
    shareState = ''; subscriptionState = '';
    subscriptionUrl = '';
    subscriptionPanelOpen = false;
    const url = shareClassUrl(window.location.href, school, Number(grade), Number(classroom));
    shareUrl = url;
    try {
      await navigator.clipboard.writeText(url);
      if (url === shareUrl) shareState = '학급 링크를 복사했어요.';
    } catch {
      if (url === shareUrl) shareState = '아래 링크를 선택해 복사해 주세요.';
    }
  }

  function subscribeTimetable() {
    if (!classActionsReady || apiNotConfigured) return;
    if (subscriptionPanelOpen) { subscriptionPanelOpen = false; subscriptionUrl = ''; subscriptionState = ''; return; }
    subscriptionPanelOpen = true;
    shareState = ''; subscriptionState = '';
    shareUrl = '';
    updateSubscriptionUrl();
  }

  function updateSubscriptionUrl() {
    if (!school) return;
    if (subscriptionMode === 'timed' && !subscriptionTimesConsent) { subscriptionUrl = ''; return; }
    if (subscriptionMode === 'timed' && Object.keys(weekdayLessonTimes).length) {
      subscriptionUrl = '';
      subscriptionState = '요일별 시각을 반영하는 구독 링크는 서버 업데이트 후 사용할 수 있어요.';
      return;
    }
    subscriptionState = '';
    subscriptionUrl = timetableSubscriptionUrl(school.id, Number(grade), Number(classroom), subscriptionMode, lessonTimes);
  }

  function changeSubscriptionMode(event: Event) {
    if (!school) return;
    const value = (event.currentTarget as HTMLSelectElement).value;
    subscriptionMode = value === 'periods' || value === 'timed' ? value : 'summary';
    subscriptionState = '';
    updateSubscriptionUrl();
  }

  async function copySubscription() {
    const url = subscriptionUrl;
    try {
      await navigator.clipboard.writeText(url);
      if (url === subscriptionUrl) subscriptionState = '구독 링크를 복사했어요. 캘린더 앱에 URL로 추가하세요.';
    } catch {
      if (url === subscriptionUrl) subscriptionState = '아래 URL을 복사해 캘린더 앱에 추가하세요.';
    }
  }

  function restoreSharedClass(shared: NonNullable<ReturnType<typeof readSharedClass>>, fallback: { school: School | null; grade: number; classroom: number }) {
    return sharedSelection.verifySchool(shared, fallback, () => school?.id, searchSchools, async (verified, signal) => {
      classError = false;
      if (fallback.school) {
        const requestedWeek = week;
        const cacheKey = verified.id + '\u0000' + requestedWeek;
        const cached = timetableSession.cache.get(cacheKey, Date.now());
        let candidate: TimetableResponse | null = cached?.data ?? null;
        if (!candidate) {
          sharedCandidateRequest = signal;
          try { candidate = await getTimetable(verified.id, requestedWeek, signal); } catch { /* The previous selection remains active. */ }
          finally { if (sharedCandidateRequest === signal) sharedCandidateRequest = null; }
        }
        if (signal.aborted) return;
        if (school?.id !== fallback.school.id || week !== requestedWeek) { sharedSelection.cancel(); return; }
        const valid = validateSharedCandidate(candidate, verified, requestedWeek, shared.grade, shared.classroom);
        if (!valid || !candidate) {
          sharedSelection.consume();
          replaceInvalidSharedAddress(fallback);
          const available = candidate?.schoolId === verified.id && candidate.weekStart === requestedWeek && !candidate.stale && candidate.records.length > 0;
          const reason = available ? '선택한 주의 시간표에 없어요.' : '시간표 데이터를 확인할 수 없어요.';
          sharedClassState = `공유 링크의 ${shared.grade}학년 ${shared.classroom}반은 ${reason} 기존 ${fallback.school.name} ${fallback.grade}학년 ${fallback.classroom}반을 유지했어요.`;
          return;
        }
        const expires = cached?.expires ?? Date.now() + refreshInterval;
        timetableSession.cache.put(cacheKey, candidate, expires);
        chooseSchool(verified, true, true, false);
        if (school?.id === verified.id && !pendingSharedClass && !classError) {
          timetableSession.saveFresh(cacheKey, candidate, expires, () => localStorage);
        }
        return;
      }
      chooseSchool(verified, true, true, false);
    }, () => { sharedClassState = '공유 링크의 학교를 확인하지 못해 이전 학교를 유지했어요.'; });
  }

  onMount(() => {
    const shared = typeof window !== 'undefined' && window.location?.hash ? readSharedClass(window.location.hash) : null;
    let savedSchool: School | null = null;
    analyticsReady = true;
    refreshCalendar();
    const calendarTimer = setInterval(refreshCalendar, 60_000);
    const onVisibilityChange = () => { if (document.visibilityState === 'visible') refreshCalendar(); };
    const onStorage = (event: StorageEvent) => {
      let storage: Storage;
      try { storage = localStorage; } catch { return; }
      if (event.storageArea !== storage) return;
      if (!school) return;
      const schoolDisplayKey = `opensigan-display:${school.id}`;
      if (event.key === null || event.key === schoolDisplayKey) {
        try {
          schoolDisplaySettings = schoolDisplayPreferences.syncFromStorage(school.id, schoolDisplaySettings);
          if (!useClassDisplay) displaySettings = schoolDisplaySettings;
        } catch { /* Keep the current in-memory settings when storage is unavailable or unreadable. */ }
      }
      const classDisplayPrefix = `opensigan-class-display:${school.id}:`;
      if (event.key === null) {
        if (classDisplayKey) {
          const saved = classDisplayPreferences.syncFromStorage(classDisplayKey);
          useClassDisplay = saved.enabled;
          displaySettings = saved.settings ?? schoolDisplaySettings;
        }
      } else if (event.key.startsWith(classDisplayPrefix)) {
        const saved = classDisplayPreferences.syncFromStorage(event.key);
        if (event.key === classDisplayKey) {
          useClassDisplay = saved.enabled;
          displaySettings = saved.settings ?? schoolDisplaySettings;
        }
      }
    };
    const onFocus = () => refreshCalendar();
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target;
      inputFocused = target instanceof HTMLElement && !!target.closest('main') &&
        (target instanceof HTMLTextAreaElement && !target.readOnly ||
         target instanceof HTMLInputElement && !target.readOnly && ['search', 'text', 'number', 'date', 'time', 'url'].includes(target.type));
    };
    const onFocusOut = () => { inputFocused = false; };
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('storage', onStorage);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    window.addEventListener('focus', onFocus);
    const themeMedia = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    systemDark = themeMedia?.matches ?? false;
    const onThemeMedia = (event: MediaQueryListEvent) => { systemDark = event.matches; };
    themeMedia?.addEventListener?.('change', onThemeMedia);
    try {
      allergySelection = readAllergies(localStorage);
      mealAllergyFilter = readMealAllergyFilter(localStorage);
      const savedMealSettings = readMealPreferences(localStorage, mealTypes, { view: mealView, types: enabledMealTypes, showAllergenNumbers });
      mealView = savedMealSettings.view;
      enabledMealTypes = savedMealSettings.types;
      showAllergenNumbers = savedMealSettings.showAllergenNumbers;
      theme = readTheme(localStorage, theme);
      animationsEnabled = readAnimations(localStorage);
      savedSchool = readSelection(localStorage, (change) => selectionState.update(change));
    } catch { /* 저장소를 사용할 수 없으면 기본 설정으로 시작합니다. */ }
    if (savedSchool) chooseSchool(savedSchool, true);
    if (shared) void restoreSharedClass(shared, { school: savedSchool, grade: Number(grade), classroom: Number(classroom) });
    if (typeof window.history?.replaceState === 'function') {
      const savedNavigation = !shared ? getNavigationFromHistory(current) : null;
      if (savedNavigation) applyNavigation(savedNavigation);
      try {
        if (sessionStorage.getItem('opencigan-retry-suggestions') === '1') {
          sessionStorage.removeItem('opencigan-retry-suggestions');
          view = 'settings';
        }
      } catch { /* Navigation remains usable without session storage. */ }
      if (new URLSearchParams(window.location.search).get('view') === 'settings') view = 'settings';
      replaceNavigationState({ version: 1, view, timetableView, school, grade: Number(grade), classroom: Number(classroom), week, selectedDay, mealDate });
      navigationReady = true;
    }
    const stopNavigation = typeof window.history?.replaceState === 'function'
      ? subscribeNavigation(current, applyNavigation) : () => {};
    return () => {
      stopNavigation();
      sharedSelection.cancel();
      clearInterval(calendarTimer); document.removeEventListener('visibilitychange', onVisibilityChange); window.removeEventListener('storage', onStorage); document.removeEventListener('focusin', onFocusIn); document.removeEventListener('focusout', onFocusOut); window.removeEventListener('focus', onFocus); themeMedia?.removeEventListener?.('change', onThemeMedia);
      schoolSearchSession.cancel(); mealSession.cancel(); timetableSession.cancel();
    };
  });
</script>

<svelte:head><title>{school?.name ?? '내 학교 캘린더'} — Opencigan</title></svelte:head>
<div class:dark={isDark} class:motion-off={!animationsEnabled} class="app-shell">
  <a class="skip-link" href="#calendar">캘린더 본문으로 건너뛰기</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="Opencigan 홈"><span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 16 4-4-4-4M6 8l-4 4 4 4M14.5 4l-5 16"/></svg></span><span>Opencigan</span></a>
    <button class="theme-toggle" onclick={changeTheme} aria-label={isDark ? '라이트 모드로 전환' : '다크 모드로 전환'}>{isDark ? '라이트 모드' : '다크 모드'}</button>
  </header>
  <main>
    <section class="school-heading" aria-label="선택한 학교">
      <div><p class="eyebrow">내 학교 캘린더</p><h1>{school?.name ?? '어느 학교에 다니나요?'}</h1><p class="school-facts">{school ? school.region + ' · ' + grade + '학년 ' + classroom + '반' : '학교를 한 번 고르면 시간표와 급식을 함께 볼 수 있어요.'}</p></div>
      {#if school}<button class="secondary-button" onclick={() => schoolEditorOpen = !schoolEditorOpen} aria-expanded={schoolEditorOpen} aria-controls="school-settings"><Icon name="school" /> {schoolEditorOpen ? '변경 닫기' : '학교/학년 변경'}</button>{/if}
    </section>
    {#if apiNotConfigured}<p class="notice" role="alert">학교 정보를 불러올 API 주소가 설정되지 않았어요.</p>{/if}
    {#if sharedClassState && !classError}<p class="notice" role="status">{sharedClassState}</p>{/if}
    {#if schoolEditorOpen || !school}
      <SchoolSelector bind:schoolQuery {schoolResults} {schoolSearchState} {schoolSearchRetryable} {grade} {classroom} {classroomDraft} {gradeOptions} {classError} {sharedClassState} {findSchool} cancelSearch={schoolSearchSession.clear} {chooseSchool} {selectGrade} {updateClass} {saveClass} />
    {/if}
    <CalendarNav {view} {inputFocused} selectView={(value) => view = value} />
    <div id="calendar" class="calendar-content" tabindex="-1">
      <TimetablePanel {view} {timetableView} {school} {timetable} {week} {current} {today} {selectedDay} {grade} {classroom} {gradeOptions} {availableClasses} {tableLoading} {tableState} {tableRefreshState} {timetableCheckedAt} {timetableFromDevice} {exportState} {exportBusy} {imageShareCancelled} {canExport} {weekendClasses} {classError} {sharedClassState} {selectedClassLessons} {shownClassLessons} {dayOverview} {displaySettings} lessonTimes={selectedDayTimes} {comparableClasses} {gradeRecords} bind:teacherQuery {selectedTeacherName} {selectedTeacherRecords} {teacherSuggestions} {teacherDates} {teacherPeriods} {dates} {periods} {filtered} {missingWeekdays} {observedClassCount} {teacherNames} {exportTimetable} {sharePng} {refreshTimetable} {currentWeek} {selectTimetableView} {selectGrade} {selectClass} {changeWeek} {loadTimetable} {selectTimetableDate} {timetableDateError} {dateText} {shortDate} {timeText} {subjectStyle} todayMeal={{ neis, neisLoading, neisSearchState, mealState, hasMeals, mealLoading, meals, mealsStale, visibleMealTypes, allergySelection, mealAllergyFilter, showAllergenNumbers, loadMeals, openAllergySettings }} />
        <MealsPanel {view} {mealDate} {today} {mealView} {mealDates} {mealDateDraft} {dateError} {neis} {school} {neisSearchState} {neisLoading} {neisResults} {mealState} {hasMeals} {mealLoading} {meals} {visibleMealTypes} {allergySelection} {mealAllergyFilter} {openAllergySettings} {showAllergenNumbers} {current} {mealsStale} {todayMeals} {setMealView} {changeMealDate} {dateText} {updateMealDateDraft} {selectMealDate} {chooseNeis} {connectMeals} {loadMeals} {selectMealTimetableDate} />
        <SettingsPanel {view} {school} {useClassDisplay} {classError} {grade} {classroom} {theme} {animationsEnabled} {displaySettings} {subjectNames} {teacherNames} {lessonTimePeriods} {lessonTimeDrafts} {autoSourceDraftPeriods} {weekdayTimeDrafts} {lessonTimeState} sourceLessonStarts={activeSourceLessonStarts} {sourceLessonAutoEnabled} setSourceLessonAuto={setSourceLessonAuto} useSourceStart={useSourceStart} {settingsBackupState} {mealTypes} {enabledMealTypes} {showAllergenNumbers} {allergySelection} {mealAllergyFilter} {setMealAllergyFilter} {openAllergySettingsRequest} {setClassDisplay} {setTheme} {setAnimationsEnabled} {setColorMode} {saveAlias} {saveSubjectColor} {clearSubjectColors} {saveDisplaySettings} {editLessonTime} {editWeekdayTime} {clearWeekdayTime} {applyLessonTimeRules} {saveLessonTimes} {clearLessonTimes} {downloadSettingsBackup} {importSettingsFile} {resetDisplaySettings} {toggleMealType} {setAllergenNumbersVisible} {toggleAllergy} />
    </div>
    <ShareTools {view} {school} {classActionsReady} {apiNotConfigured} {shareUrl} {shareState} {subscriptionUrl} {subscriptionState} {subscriptionPanelOpen} {subscriptionMode} {subscriptionTimesConsent} {canExport} {exportBusy} {shareClass} {subscribeTimetable} {exportTimetable} {changeSubscriptionMode} setSubscriptionTimesConsent={(value) => { subscriptionTimesConsent = value; updateSubscriptionUrl(); }} {copySubscription} />
    <footer><div class="footer-open"><svg class="github-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.64-1.25-1.64-1.02-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.72.39-1.22.7-1.5-2.5-.28-5.13-1.25-5.13-5.56 0-1.23.44-2.24 1.16-3.03-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.16A10.8 10.8 0 0 1 12 6.17c.96 0 1.92.13 2.82.38 2.15-1.46 3.1-1.16 3.1-1.16.61 1.55.23 2.7.11 2.98.72.79 1.16 1.8 1.16 3.03 0 4.32-2.63 5.27-5.14 5.55.4.35.76 1.03.76 2.08v3.1c0 .3.2.65.78.54A11.25 11.25 0 0 0 12 .75Z"/></svg><div><strong>함께 만드는 오픈소스</strong><p>Opencigan은 오픈소스 프로젝트예요. GitHub에서 함께 기여해 주세요.</p><div class="footer-links"><a href="https://github.com/Transient-Onlooker/opencigan">Opencigan GitHub ↗</a><a href="https://github.com/hegelty/pycomcigan">pycomcigan ↗</a><a href="https://opencigan.mcv.kr/">Opencigan 사이트 ↗</a><a href="/api-docs.html">API 문서</a></div>{#if view === 'settings' && import.meta.env.VITE_SUGGESTIONS_ENABLED !== '0' && SuggestionsComponent}<SuggestionsComponent />{/if}</div></div></footer>
    {#if view === 'settings' && suggestionsEnabled && suggestionsLoadFailed && !suggestionsLoading && !SuggestionsComponent}
      <p role="status">제안 기능을 불러오지 못했어요. <button class="secondary-button" onclick={retrySuggestionsAfterReload}>새로고침 후 다시 시도</button>{#if suggestionsRetryMessage} {suggestionsRetryMessage}{/if}</p>
    {/if}
  </main>
</div>
