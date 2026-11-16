<script lang="ts">
  import { onMount } from 'svelte';
  import Icon from './Icon.svelte';
  import MealsPanel from './MealsPanel.svelte';
  import PersonalTimetable from './PersonalTimetable.svelte';
  import CalendarNav from './CalendarNav.svelte';
  import SchoolSelector from './SchoolSelector.svelte';
  import FavoritesBar from './FavoritesBar.svelte';
  import ShareTools from './ShareTools.svelte';
  import SettingsPanel from './SettingsPanel.svelte';
  import TimetablePanel from './TimetablePanel.svelte';
  import { readAllergies, readMealPreferences, saveMealPreferences as persistMealPreferences, saveAllergies, readSchoolPreference, writeSchoolPreference, readFavorites, writeFavorites, readTheme, writeTheme, readAnimations, writeAnimations, readMealSchool, writeMealSchool, type Favorite } from './preferences';
  import { getNavigationFromHistory, parseNavigationState, replaceNavigationState, pushNavigationState, subscribeNavigation, type NavigationState } from './navigation';
  import { saveSelection, readSelection, resolveSharedClass, gradesInTimetable, classesInGrade, createSelectionState, createSharedSelectionSession, type PendingSharedClass } from './selection';
  import { currentKoreaDate, monday, addDays, clampWeek } from './date';
  import { resolveMealSchool, mealSchoolCandidates } from './neis-match';
  import { trackPageView } from './analytics';
  import { shareClassUrl, readSharedClass, findLessons } from './sharing';
  import { saveTimetablePdf, saveTimetablePng, shareTimetablePng, type ExportOptions } from './export-png';
  import { createTimetableSession } from './timetable-cache';
  import { createHistorySession } from './history-session';
  import { createMealSession } from './meal-session';
  import { classLessons, teacherLessons, teacherNamesInTimetable, gradeLessons, comparisonClasses, missingWeekdayDates, observedClassCount as countObservedClasses, subjectNamesInTimetable } from './timetable-view';
  import { dailyLessonOverview, koreaClockMinutes, parseLessonTimes, type LessonTimes } from './lesson-times';
  import { createClassDisplayPreferences, defaultDisplaySettings, parseDisplaySettings, displayTeacher, subjectColor, subjectTextColor, type ColorMode, type DisplaySettings } from './personalization';
  import { createSettingsBackup, parseSettingsBackup, saveSchoolSettingsBackup, MAX_SETTINGS_BACKUP_BYTES } from './settings-backup';
  import { apiNotConfigured, getMeals, getTimetable, getTimetableHistory, searchSchools, searchNeisSchools, timetableSubscriptionUrl, type Meal, type NeisSchool, type School, type TimetableRecord, type TimetableResponse, type TimetableChange } from './api';

  let school: School | null = null;
  let favorites: Favorite[] = [];
  let neis: NeisSchool | null = null;
  let schoolQuery = '';
  let schoolResults: School[] = [];
  let neisResults: NeisSchool[] = [];
  let schoolSearchState = '';
  let neisSearchState = '';
  let neisLoading = false;
  let schoolEditorOpen = true;
  let view: 'timetable' | 'meals' | 'settings' = 'timetable';
  let timetableView: 'today' | 'week' | 'grade' | 'teacher' = 'week';
  let teacherQuery = '';
  let displaySettings: DisplaySettings = defaultDisplaySettings();
  let schoolDisplaySettings: DisplaySettings = defaultDisplaySettings();
  let useClassDisplay = false;
  const classDisplayPreferences = createClassDisplayPreferences(() => localStorage);
  let lessonTimes: LessonTimes = {};
  let lessonTimeDrafts: Record<number, { start: string; end: string }> = {};
  let lessonTimeState = '';
  let settingsBackupState = '';
  let selectedSubject = '';
  let selectedTeacher = '';
  let allergySelection: number[] = [];
  let tableRefreshState = '';
  let timetableCheckedAt = '';
  let exportState = '';
  let exportBusy = false;
  let lessonQuery = '';
  let lessonWeekday = '';
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
  let sharedClassState = '';
  let pendingSharedClass: PendingSharedClass | null = null;
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
  let schoolTimer: ReturnType<typeof setTimeout>;
  let schoolRequest: AbortController | undefined;
  const mealSession = createMealSession((state) => {
    neis = state.neis; neisResults = state.candidates; neisSearchState = state.searchState; neisLoading = state.neisLoading;
    meals = state.meals; hasMeals = state.hasMeals; mealsStale = state.stale; mealState = state.error;
    mealLoading = state.loading; mealsRefreshAt = state.refreshAt;
  });
  let historyOpen = false;
  let historyLoading = false;
  let historyDisabled = false;
  let historyError = '';
  let historyChanges: TimetableChange[] = [];
  let historyScope: 'class' | 'school' = 'class';
  $: visibleHistory = historyScope === 'school' ? historyChanges : historyChanges.filter(
    (change) => Number(change.grade) === Number(grade) && Number(change.class) === Number(classroom));
  let historyCursor: string | null = null;
  const historySession = createHistorySession((state) => {
    historyLoading = state.loading; historyDisabled = state.disabled; historyError = state.error;
    historyChanges = state.changes; historyCursor = state.cursor;
  });

  $: filtered = classLessons(timetable?.records ?? [], grade, classroom);
  $: dayRecords = (timetable?.records ?? []).filter((r) => r.date === selectedDay);
  $: selectedClassLessons = classLessons(dayRecords, grade, classroom).sort((a, b) => Number(a.period) - Number(b.period));
  $: dayOverview = dailyLessonOverview(selectedClassLessons, lessonTimes, clockMinute, selectedDay === today);
  $: shownClassLessons = displaySettings.endedLessonMode === 'hide' ? selectedClassLessons.filter((item) => !dayOverview.completed.includes(Number(item.period))) : selectedClassLessons;
  $: gradeRecords = gradeLessons(dayRecords, grade);
  $: comparableClasses = comparisonClasses(gradeRecords);
  $: teacherNames = teacherNamesInTimetable(timetable?.records ?? []);
  $: observedClassCount = countObservedClasses(timetable?.records ?? []);
  $: subjectNames = subjectNamesInTimetable(timetable?.records ?? []);
  $: teacherSuggestions = teacherNames.filter((name) => [name, displayTeacher(name, displaySettings)].some((label) => label.toLocaleLowerCase('ko-KR').includes(teacherQuery.trim().toLocaleLowerCase('ko-KR'))));
  $: selectedTeacherName = teacherNames.find((name) => name === teacherQuery.trim() || displayTeacher(name, displaySettings) === teacherQuery.trim()) ?? '';
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
  $: lessonTimePeriods = Array.from({ length: Math.max(8, ...((timetable?.records ?? []).map((r) => Number(r.period)).filter((period) => Number.isInteger(period) && period > 0 && period <= 20))) }, (_, i) => i + 1);
  $: visibleMealTypes = mealTypes.filter((type) => enabledMealTypes.includes(type));
  $: mealDates = Array.from({ length: 7 }, (_, index) => addDays(monday(mealDate), index));
  $: matchingLessons = lessonQuery.trim() || lessonWeekday ? findLessons(filtered, lessonQuery, lessonWeekday) : [];
  $: currentFavorite = favorites.some((item) => item.school.id === school?.id && item.grade === Number(grade) && item.classroom === Number(classroom));
  $: isDark = themeIsDark(theme, systemDark);
  $: if (analyticsReady && view !== 'settings') trackPageView(view === 'meals' ? '/meals' : '/timetable');
  $: if (navigationReady && !applyingNavigation && !classError && !pendingSharedClass) {
    pushNavigationState({ version: 1, view, timetableView, school, grade: Number(grade), classroom: Number(classroom), week, selectedDay, mealDate }, current);
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
      timetableSession.cancel(); mealSession.cancel(); historySession.cancel();
      selectionState.update({ school: null }); timetableSession.update({ data: null, loading: false }); mealSession.update({ neis: null, meals: [], loading: false }); schoolEditorOpen = true;
      try { localStorage.removeItem('opensigan-school'); } catch { /* 현재 탐색을 유지합니다. */ }
    } else {
      if (previousWeek !== week) loadTimetable(false, true, true);
      else ensureAvailableClass();
      loadMeals();
      persistClassSelection();
    }
    shareUrl = ''; subscriptionUrl = ''; shareState = ''; subscriptionState = '';
    historySession.cancel(); historySession.update({ changes: [], cursor: null, loading: false }); historyOpen = false;
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
  function changeTypeText(type: string) { return type === 'added' ? '추가' : type === 'deleted' ? '삭제' : type === 'changed' ? '변경' : type; }
  function errorText(error: unknown) { return error instanceof Error ? error.message : '요청을 완료하지 못했어요.'; }

  function themeIsDark(preference: 'light' | 'dark' | 'system', prefersDark: boolean) {
    return preference === 'dark' || (preference === 'system' && prefersDark);
  }

  function subjectStyle(subject: string | null | undefined) {
    const color = subjectColor(subject, displaySettings);
    return color ? `background-color:${color};color:${subjectTextColor(color)}` : undefined;
  }
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
      try { writeSchoolPreference(localStorage, 'opensigan-display:', school.id, next); }
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
  function saveSubjectColor(value: string) {
    if (!selectedSubject || !/^#[0-9a-fA-F]{6}$/.test(value)) return;
    saveDisplaySettings({ ...displaySettings, subjectColors: { ...displaySettings.subjectColors, [selectedSubject]: value } });
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
    const contents = createSettingsBackup(school.id, classOnly ? displaySettings : schoolDisplaySettings, lessonTimes, scope);
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
      saveSchoolSettingsBackup(localStorage, schoolId, backup.displaySettings, backup.lessonTimes);
      schoolDisplaySettings = backup.displaySettings;
      lessonTimes = backup.lessonTimes;
      lessonTimeDrafts = { ...backup.lessonTimes };
      lessonTimeState = '';
      settingsBackupState = '현재 학교의 설정을 복원했어요.';
    } catch (error) {
      settingsBackupState = errorText(error);
    }
  }

  function editLessonTime(period: number, part: 'start' | 'end', value: string) {
    lessonTimeDrafts = { ...lessonTimeDrafts, [period]: { start: lessonTimeDrafts[period]?.start ?? '', end: lessonTimeDrafts[period]?.end ?? '', [part]: value } };
    lessonTimeState = '';
  }
  function saveLessonTimes() {
    if (!school) return;
    const entries = Object.entries(lessonTimeDrafts).filter(([, entry]) => entry.start || entry.end);
    const parsed = parseLessonTimes(Object.fromEntries(entries));
    if (entries.length !== Object.keys(parsed).length) {
      lessonTimeState = '각 교시의 시작·종료 시각을 모두 입력하고, 시간 순서와 겹침 여부를 확인해 주세요.';
      return;
    }
    lessonTimes = parsed;
    lessonTimeState = '이 학교의 교시 시각을 저장했어요.';
    subscriptionUrl = ''; subscriptionPanelOpen = false; subscriptionTimesConsent = false;
    try { writeSchoolPreference(localStorage, 'opensigan-lesson-times:', school.id, lessonTimes); }
    catch { lessonTimeState = '현재 화면에만 적용됐어요. 브라우저 저장소를 확인해 주세요.'; }
  }
  function clearLessonTimes() {
    lessonTimeDrafts = {}; lessonTimes = {}; lessonTimeState = '교시 시각을 초기화했어요.';
    subscriptionUrl = ''; subscriptionPanelOpen = false; subscriptionTimesConsent = false;
    if (school) { try { localStorage.removeItem('opensigan-lesson-times:' + school.id); } catch { /* 현재 화면에서 삭제했습니다. */ } }
  }

  function toggleAllergy(id: number, checked: boolean) {
    allergySelection = checked ? [...new Set([...allergySelection, id])].sort((a, b) => a - b) : allergySelection.filter((value) => value !== id);
    try { saveAllergies(localStorage, allergySelection); } catch { /* 설정은 현재 페이지에서 유지됩니다. */ }
  }

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

  function loadFavorites() {
    try { favorites = readFavorites(localStorage) ?? favorites; } catch { favorites = []; }
  }
  function saveFavorites() {
    try { writeFavorites(localStorage, favorites); } catch { /* 브라우저 저장이 차단되어도 현재 화면은 동작합니다. */ }
  }
  function addFavorite() {
    if (!school || classError || pendingSharedClass || favorites.length >= 10 ||
        favorites.some((item) => item.school.id === school?.id && item.grade === Number(grade) && item.classroom === Number(classroom))) return;
    favorites = [...favorites, { school: { ...school }, grade: Number(grade), classroom: Number(classroom) }];
    saveFavorites();
  }
  function removeFavorite(favorite: Favorite) {
    favorites = favorites.filter((item) => !(item.school.id === favorite.school.id && item.grade === favorite.grade && item.classroom === favorite.classroom));
    saveFavorites();
  }
  function switchToFavorite(favorite: Favorite) {
    cancelSharedSelection();
    selectionState.update({ grade: favorite.grade, classroom: favorite.classroom }); classError = false;
    shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = '';
    if (school?.id !== favorite.school.id) chooseSchool(favorite.school, true);
    else { schoolEditorOpen = false; ensureAvailableClass(); }
    classroomDraft = String(classroom);
    persistClassSelection();
    persistSelection({ grade, classroom });
  }

  function findSchool() {
    clearTimeout(schoolTimer); schoolRequest?.abort(); schoolResults = []; schoolSearchState = '';
    if (schoolQuery.trim().length < 2) { schoolSearchState = schoolQuery.length ? '학교 이름을 두 글자 이상 입력해 주세요.' : ''; return; }
    if (schoolQuery.trim().length > 50) { schoolSearchState = '학교 이름은 최대 50자까지 검색할 수 있어요.'; return; }
    schoolSearchState = '검색 중…';
    schoolTimer = setTimeout(async () => {
      const controller = new AbortController(); schoolRequest = controller;
      try {
        const result = await searchSchools(schoolQuery.trim(), controller.signal);
        if (!controller.signal.aborted) {
          schoolResults = result.schools;
          schoolSearchState = result.stale ? '저장된 검색 결과예요. 최신 정보가 아닐 수 있습니다.' : schoolResults.length ? '' : '검색 결과가 없어요. 컴시간에서 시간표를 제공하지 않는 학교는 검색되지 않을 수 있습니다.';
        }
      } catch (error) { if (!controller.signal.aborted) schoolSearchState = errorText(error); }
    }, 250);
  }
  function cancelSharedSelection() {
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
    if (selectionState.prepareSchool(value, keepClass)) classError = false;
    classroomDraft = String(classroom);
    shareUrl = ''; shareState = ''; subscriptionUrl = ''; subscriptionState = '';
    schoolRequest?.abort(); clearTimeout(schoolTimer); mealSession.cancel(); historySession.cancel();
    selectionState.update({ school: value }); schoolQuery = value.name; schoolResults = []; schoolSearchState = ''; schoolEditorOpen = false;
    selectedSubject = ''; selectedTeacher = ''; teacherQuery = '';
    try { schoolDisplaySettings = readSchoolPreference(localStorage, 'opensigan-display:', value.id, parseDisplaySettings, defaultDisplaySettings); }
    catch { schoolDisplaySettings = defaultDisplaySettings(); }
    try { lessonTimes = readSchoolPreference(localStorage, 'opensigan-lesson-times:', value.id, parseLessonTimes, () => ({})); }
    catch { lessonTimes = {}; }
    lessonTimeDrafts = { ...lessonTimes }; lessonTimeState = '';
    subscriptionTimesConsent = false;
    settingsBackupState = '';
    historySession.reset(); historyOpen = false;
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
    mealSession.cancelNeis();
    mealSession.update({ neis: value, candidates: [], neisLoading: false, searchState: '급식도 ' + value.name + '로 연결했어요.' });
    if (school) { try { writeMealSchool(localStorage, school.id, value); } catch { /* 현재 연결은 저장 없이 유지합니다. */ } }
    loadMeals();
  }
  function ensureAvailableClass() {
    if (pendingSharedClass && pendingSharedClass.schoolId === school?.id) {
      const pending = sharedSelection.consume()!;
      const outcome = resolveSharedClass(pending, timetable, timetableFromDevice, school && /(?:중학교|고등학교)/.test(school.name) ? 3 : 6);
      if (outcome.status === 'rolled-back') {
        const message = outcome.reason === 'missing'
          ? `공유 링크의 ${pending.grade}학년 ${pending.classroom}반이 선택한 주의 시간표 데이터에 없어 적용하지 않았어요.`
          : '시간표 데이터가 없어 공유 링크의 학년·반을 확인하지 못했어요.';
        if (outcome.fallback.school) {
          selectionState.update({ grade: outcome.fallback.grade, classroom: outcome.fallback.classroom });
          classError = false;
          chooseSchool(outcome.fallback.school, true);
          sharedClassState = message + ' 이전 학교와 학급을 유지했어요.';
        } else {
          classError = true;
          schoolEditorOpen = true;
          sharedClassState = message + ' 시간표에서 확인할 수 있는 학급을 선택해 주세요.';
        }
        return;
      }
      classError = false;
      selectionState.update({ grade: outcome.grade, classroom: outcome.classroom });
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
      now: () => Date.now(), storage: () => localStorage, online: () => navigator.onLine !== false,
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
  async function loadHistory(append = false) {
    await historySession.load(school?.id, week, append, () => ({ schoolId: school?.id, week }), getTimetableHistory, errorText);
  }
  function toggleHistory() {
    historyOpen = !historyOpen;
    if (historyOpen && !historyChanges.length && !historyDisabled) void loadHistory();
  }
  function selectTimetableView(value: typeof timetableView) {
    timetableView = value;
    exportState = '';
    if (value === 'today' || value === 'grade') selectedDay = week === current ? today : week;
    if (value === 'today') {
      mealDate = selectedDay; mealDateDraft = selectedDay; dateError = '';
      loadMeals();
    }
  }
  function loadMeals(preserve = false) {
    if (!school || !neis) return;
    const from = monday(mealDate);
    mealSession.load(neis.id, from, addDays(from, 6), preserve, () => Date.now(), refreshInterval, getMeals, errorText);
  }
  function refreshCalendar(refreshData = true) {
    const previousToday = today;
    clockMinute = koreaClockMinutes(new Date());
    today = currentKoreaDate(new Date()); current = monday(today);
    const validWeek = clampWeek(week, current);
    if (selectedDay === previousToday) selectedDay = today;
    if (validWeek !== week) {
      selectionState.update({ week: validWeek });
      selectedDay = selectedDay < week ? week : selectedDay > addDays(week, 6) ? addDays(week, 6) : selectedDay;
      historySession.reset();
      if (refreshData) {
        loadTimetable();
        if (historyOpen) void loadHistory();
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
    refreshCalendar(false); const next = addDays(week, delta * 7);
    if (next < current || next > addDays(current, 7)) return;
    tableRefreshState = ''; exportState = ''; teacherQuery = ''; selectionState.update({ week: next }); selectedDay = week === current ? today : week; historySession.reset(); historyOpen = false; loadTimetable(false, true);
  }
  function currentWeek() { refreshCalendar(false); const preserve = week === current; const reopenHistory = historyOpen; tableRefreshState = ''; if (!preserve) teacherQuery = ''; selectionState.update({ week: current }); selectedDay = today; historySession.reset(); loadTimetable(preserve); if (reopenHistory) void loadHistory(); }
  function changeMealDate(delta: number) {
    const next = addDays(mealDate, delta);
    if (!validMealDate(next)) { dateError = '1900년 이후의 올바른 날짜를 선택해 주세요.'; return; }
    mealDate = next; mealDateDraft = next; dateError = ''; loadMeals();
  }
  function selectTimetableDate(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const value = input.value;
    if (value && input.validity.valid && value >= week && value <= addDays(week, 6)) {
      selectedDay = value; mealDate = value; mealDateDraft = value; dateError = '';
      loadMeals();
    } else input.value = selectedDay;
  }
  function todayMeals() { refreshCalendar(); mealDate = today; mealDateDraft = today; dateError = ''; loadMeals(); }
  function selectMealTimetableDate(value: string) {
    refreshCalendar(false);
    if (!validMealDate(value)) return;
    const targetWeek = monday(value);
    if (targetWeek < current || targetWeek > addDays(current, 7)) return;
    const needsTimetable = targetWeek !== week || timetable?.weekStart !== targetWeek;
    view = 'timetable'; timetableView = 'today'; selectionState.update({ week: targetWeek }); selectedDay = value;
    mealDate = value; mealDateDraft = value; dateError = '';
    if (needsTimetable) {
      tableRefreshState = ''; teacherQuery = '';
      historySession.reset(); historyOpen = false;
      loadTimetable(false, true);
    }
    loadMeals();
  }
  function updateMealDateDraft(event: Event) {
    mealDateDraft = (event.currentTarget as HTMLInputElement).value;
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
  function selectMealDate(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const value = input.value;
    if (!validMealDate(value)) {
      dateError = '1900년 이후의 올바른 날짜를 선택해 주세요.';
      mealDateDraft = mealDate;
      input.value = mealDate;
      return;
    }
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
    exportState = '공유할 이미지를 만드는 중…';
    try {
      const result = await shareTimetablePng(options);
      exportState = result === 'shared' ? '시간표 이미지를 공유했어요.' : result === 'cancelled' ? '' : '이 브라우저에서는 이미지 공유가 어려워 PNG로 저장했어요.';
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
    classError = !Number.isInteger(value) || value < 1 || value > 99 || (availableClasses.length > 0 && !availableClasses.includes(value));
  }
  function saveClass(event: Event) {
    updateClass(event);
    const input = event.currentTarget as HTMLInputElement;
    if (!classError) selectionState.update({ classroom: input.valueAsNumber });
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
    return sharedSelection.verifySchool(shared, fallback, () => school?.id, searchSchools, (verified) => {
      selectionState.update({ grade: shared.grade, classroom: shared.classroom }); classError = false;
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
    const onFocus = () => refreshCalendar();
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target;
      inputFocused = target instanceof HTMLElement && !!target.closest('main') &&
        (target instanceof HTMLTextAreaElement && !target.readOnly ||
         target instanceof HTMLInputElement && !target.readOnly && ['search', 'text', 'number', 'date', 'time', 'url'].includes(target.type));
    };
    const onFocusOut = () => { inputFocused = false; };
    document.addEventListener('visibilitychange', onVisibilityChange);
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    window.addEventListener('focus', onFocus);
    const themeMedia = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    systemDark = themeMedia?.matches ?? false;
    const onThemeMedia = (event: MediaQueryListEvent) => { systemDark = event.matches; };
    themeMedia?.addEventListener?.('change', onThemeMedia);
    loadFavorites();
    try {
      allergySelection = readAllergies(localStorage);
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
      replaceNavigationState({ version: 1, view, timetableView, school, grade: Number(grade), classroom: Number(classroom), week, selectedDay, mealDate });
      navigationReady = true;
    }
    const stopNavigation = typeof window.history?.replaceState === 'function'
      ? subscribeNavigation(current, applyNavigation) : () => {};
    return () => {
      stopNavigation();
      sharedSelection.cancel();
      clearInterval(calendarTimer); document.removeEventListener('visibilitychange', onVisibilityChange); document.removeEventListener('focusin', onFocusIn); document.removeEventListener('focusout', onFocusOut); window.removeEventListener('focus', onFocus); themeMedia?.removeEventListener?.('change', onThemeMedia); historySession.cancel();
      clearTimeout(schoolTimer); schoolRequest?.abort(); mealSession.cancel(); timetableSession.cancel();
    };
  });
</script>

<svelte:head><title>{school?.name ?? '내 학교 캘린더'} — Opencigan</title></svelte:head>
<div class:dark={isDark} class:motion-off={!animationsEnabled} class="app-shell">
  <a class="skip-link" href="#calendar">캘린더 본문으로 건너뛰기</a>
  <header class="topbar">
    <div class="brand"><span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m18 16 4-4-4-4M6 8l-4 4 4 4M14.5 4l-5 16"/></svg></span><span>Opencigan</span></div>
    <button class="theme-toggle" onclick={changeTheme} aria-label={isDark ? '라이트 모드로 전환' : '다크 모드로 전환'}>{isDark ? '라이트 모드' : '다크 모드'}</button>
  </header>
  <main>
    <section class="school-heading" aria-label="선택한 학교">
      <div><p class="eyebrow">내 학교 캘린더</p><h1>{school?.name ?? '어느 학교에 다니나요?'}</h1><p class="school-facts">{school ? school.region + ' · ' + grade + '학년 ' + classroom + '반' : '학교를 한 번 고르면 시간표와 급식을 함께 볼 수 있어요.'}</p></div>
      {#if school}<button class="secondary-button" onclick={() => schoolEditorOpen = !schoolEditorOpen} aria-expanded={schoolEditorOpen} aria-controls="school-settings"><Icon name="school" /> {schoolEditorOpen ? '학교 선택 닫기' : '학교 변경'}</button>{/if}
    </section>
    {#if apiNotConfigured}<p class="notice" role="alert">학교 정보를 불러올 API 주소가 설정되지 않았어요.</p>{/if}
    {#if sharedClassState && !classError}<p class="notice" role="status">{sharedClassState}</p>{/if}
    {#if schoolEditorOpen || !school}
      <SchoolSelector bind:schoolQuery {schoolResults} {schoolSearchState} {grade} {classroom} {classroomDraft} {gradeOptions} {classError} {sharedClassState} {findSchool} cancelSearch={() => { clearTimeout(schoolTimer); schoolRequest?.abort(); schoolResults = []; schoolSearchState = ''; }} {chooseSchool} {selectGrade} {updateClass} {saveClass} />
    {/if}
    <FavoritesBar {school} {grade} {classroom} {favorites} {currentFavorite} disabled={classError || !!pendingSharedClass} {addFavorite} {removeFavorite} {switchToFavorite} />
    <CalendarNav {view} {inputFocused} selectView={(value) => view = value} />
    <div id="calendar" class="calendar-content" tabindex="-1">
        <TimetablePanel {view} {timetableView} {school} {timetable} {week} {current} {today} {selectedDay} {grade} {classroom} {gradeOptions} {availableClasses} {tableLoading} {tableState} {tableRefreshState} {timetableCheckedAt} {timetableFromDevice} {exportState} {exportBusy} {canExport} {weekendClasses} {classError} {sharedClassState} bind:lessonQuery bind:lessonWeekday {matchingLessons} {selectedClassLessons} {shownClassLessons} {dayOverview} {displaySettings} {lessonTimes} {comparableClasses} {gradeRecords} bind:teacherQuery {selectedTeacherName} {selectedTeacherRecords} {teacherSuggestions} {teacherDates} {teacherPeriods} {dates} {periods} {filtered} {missingWeekdays} {observedClassCount} {teacherNames} {historyOpen} {historyDisabled} {historyLoading} {historyError} {historyChanges} {visibleHistory} {historyCursor} bind:historyScope {exportTimetable} {sharePng} {refreshTimetable} {currentWeek} {selectTimetableView} {selectGrade} {selectClass} {changeWeek} {loadTimetable} {selectTimetableDate} {toggleHistory} {loadHistory} {dateText} {shortDate} {timeText} {changeTypeText} {subjectStyle} />
        <MealsPanel {view} {mealDate} {today} {mealView} {mealDates} {mealDateDraft} {dateError} {neis} {school} {neisSearchState} {neisLoading} {neisResults} {mealState} {hasMeals} {mealLoading} {meals} {visibleMealTypes} {allergySelection} {showAllergenNumbers} {current} {mealsStale} {todayMeals} {setMealView} {changeMealDate} {dateText} {updateMealDateDraft} {selectMealDate} {chooseNeis} {connectMeals} {loadMeals} {selectMealTimetableDate} />
        <SettingsPanel {view} {school} {useClassDisplay} {classError} {grade} {classroom} {theme} {animationsEnabled} {displaySettings} bind:selectedSubject bind:selectedTeacher {subjectNames} {teacherNames} {lessonTimePeriods} {lessonTimeDrafts} {lessonTimeState} {settingsBackupState} {mealTypes} {enabledMealTypes} {showAllergenNumbers} {allergySelection} {setClassDisplay} {setTheme} {setAnimationsEnabled} {setColorMode} {saveAlias} {saveSubjectColor} {clearSubjectColors} {saveDisplaySettings} {editLessonTime} {saveLessonTimes} {clearLessonTimes} {downloadSettingsBackup} {importSettingsFile} {resetDisplaySettings} {toggleMealType} {setAllergenNumbersVisible} {toggleAllergy} />
        {#if school && view === 'timetable'}
          <details class="personal-timetable-panel"><summary>개인 시간표·일정</summary>
            {#key `${school.id}:${grade}:${classroom}`}<PersonalTimetable schoolId={school.id} schoolName={school.name} grade={Number(grade)} classroom={Number(classroom)} {week} dark={isDark} {displaySettings} />{/key}
          </details>
        {/if}
    </div>
    <ShareTools {view} {school} {classActionsReady} {apiNotConfigured} {shareUrl} {shareState} {subscriptionUrl} {subscriptionState} {subscriptionPanelOpen} {subscriptionMode} {subscriptionTimesConsent} {canExport} {exportBusy} {shareClass} {subscribeTimetable} {exportTimetable} {changeSubscriptionMode} setSubscriptionTimesConsent={(value) => { subscriptionTimesConsent = value; updateSubscriptionUrl(); }} {copySubscription} />
    <footer><div class="footer-open"><svg class="github-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.13.68-3.79-1.33-3.79-1.33-.51-1.3-1.25-1.64-1.25-1.64-1.02-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.72.39-1.22.7-1.5-2.5-.28-5.13-1.25-5.13-5.56 0-1.23.44-2.24 1.16-3.03-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.16A10.8 10.8 0 0 1 12 6.17c.96 0 1.92.13 2.82.38 2.15-1.46 3.1-1.16 3.1-1.16.61 1.55.23 2.7.11 2.98.72.79 1.16 1.8 1.16 3.03 0 4.32-2.63 5.27-5.14 5.55.4.35.76 1.03.76 2.08v3.1c0 .3.2.65.78.54A11.25 11.25 0 0 0 12 .75Z"/></svg><div><strong>함께 만드는 오픈소스</strong><p>Opencigan은 오픈소스 프로젝트예요. GitHub에서 함께 기여해 주세요.</p><div class="footer-links"><a href="https://github.com/Transient-Onlooker/opensigan">Opencigan GitHub ↗</a><a href="https://github.com/hegelty/pycomcigan">pycomcigan ↗</a><a href="https://opencigan.mcv.kr/">Opencigan 사이트 ↗</a><a href="/api-docs.html">API 문서</a></div></div></div></footer>
  </main>
</div>
