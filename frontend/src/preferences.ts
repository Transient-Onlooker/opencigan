import type { NeisSchool, School } from './api';
import type { MealAllergyFilter } from './meal-filter';

export type MealPreferences = { view: 'day' | 'week'; types: string[]; showAllergenNumbers: boolean };
export type ThemePreference = 'light' | 'dark' | 'system';

export function readMealSchool(storage: Pick<Storage, 'getItem'>, schoolId: string): NeisSchool | null {
  const saved = storage.getItem('opensigan-neis:' + schoolId);
  return saved ? JSON.parse(saved) as NeisSchool : null;
}

export function writeMealSchool(storage: Pick<Storage, 'setItem'>, schoolId: string, school: NeisSchool) {
  storage.setItem('opensigan-neis:' + schoolId, JSON.stringify(school));
}

export function readTheme(storage: Pick<Storage, 'getItem'>, fallback: ThemePreference): ThemePreference {
  const value = storage.getItem('opensigan-theme');
  return value === 'light' || value === 'dark' || value === 'system' ? value : fallback;
}

export function writeTheme(storage: Pick<Storage, 'setItem'>, theme: ThemePreference) {
  storage.setItem('opensigan-theme', theme);
}

export function readAnimations(storage: Pick<Storage, 'getItem'>) {
  return storage.getItem('opensigan-animations') !== 'off';
}

export function writeAnimations(storage: Pick<Storage, 'setItem'>, enabled: boolean) {
  storage.setItem('opensigan-animations', enabled ? 'on' : 'off');
}

export function readAllergies(storage: Pick<Storage, 'getItem'>) {
  const raw = storage.getItem('opensigan-allergies');
  let allergies: unknown;
  try { allergies = JSON.parse(raw || '[]'); } catch { return []; }
  return Array.isArray(allergies)
    ? [...new Set(allergies.filter((id): id is number => Number.isInteger(id) && id >= 1 && id <= 19))].sort((a, b) => a - b)
    : [];
}

export function readMealPreferences(storage: Pick<Storage, 'getItem'>, mealTypes: string[], defaults: MealPreferences) {
  const raw = storage.getItem('opensigan-meal-preferences');
  let saved: unknown;
  try { saved = JSON.parse(raw || 'null'); } catch { saved = null; }
  const value = { ...defaults, types: [...defaults.types] };
  if (saved && typeof saved === 'object') {
    const preferences = saved as { view?: unknown; types?: unknown; showAllergenNumbers?: unknown };
    if (preferences.view === 'day' || preferences.view === 'week') value.view = preferences.view;
    if (Array.isArray(preferences.types)) {
      const valid = mealTypes.filter((type) => (preferences.types as unknown[]).includes(type));
      if (valid.length) value.types = valid;
    }
    if (typeof preferences.showAllergenNumbers === 'boolean') value.showAllergenNumbers = preferences.showAllergenNumbers;
  }
  return value;
}

export function saveMealPreferences(storage: Pick<Storage, 'setItem'>, preferences: MealPreferences) {
  storage.setItem('opensigan-meal-preferences', JSON.stringify(preferences));
}

export function saveAllergies(storage: Pick<Storage, 'setItem'>, allergies: number[]) {
  storage.setItem('opensigan-allergies', JSON.stringify(allergies));
}

export function readMealAllergyFilter(storage: Pick<Storage, 'getItem'>): MealAllergyFilter {
  const value = storage.getItem('opensigan-meal-allergy-filter');
  return value === 'marked' || value === 'unmarked' ? value : 'all';
}

export function saveMealAllergyFilter(storage: Pick<Storage, 'setItem'>, value: MealAllergyFilter) {
  storage.setItem('opensigan-meal-allergy-filter', value);
}

export function readSchoolPreference<T>(storage: Pick<Storage, 'getItem'>, prefix: string, schoolId: string, parse: (value: unknown) => T, fallback: () => T): T {
  try { return parse(JSON.parse(storage.getItem(prefix + schoolId) || 'null')); }
  catch { return fallback(); }
}

export function writeSchoolPreference(storage: Pick<Storage, 'setItem'>, prefix: string, schoolId: string, value: unknown) {
  storage.setItem(prefix + schoolId, JSON.stringify(value));
}
