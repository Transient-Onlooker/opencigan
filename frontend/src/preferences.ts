import type { School } from './api';

export type Favorite = { school: School; grade: number; classroom: number };
export type MealPreferences = { view: 'day' | 'week'; types: string[]; showAllergenNumbers: boolean };

export function readFavorites(storage: Pick<Storage, 'getItem'>): Favorite[] | null {
  const saved: unknown = JSON.parse(storage.getItem('opensigan-favorites') || '[]');
  if (!Array.isArray(saved)) return null;
  const valid: Favorite[] = [];
  for (const entry of saved) {
    if (!entry || typeof entry !== 'object') continue;
    const item = entry as Partial<Favorite>;
    const value = item.school;
    if (!value || typeof value.id !== 'string' || !/^[0-9]+:[^:]{1,50}$/.test(value.id) || value.id.length > 100 ||
        typeof value.name !== 'string' || !value.name.trim() || value.name.length > 50 ||
        typeof value.region !== 'string' || value.region.length > 100 ||
        !Number.isInteger(item.grade) || Number(item.grade) < 1 || Number(item.grade) > 6 ||
        !Number.isInteger(item.classroom) || Number(item.classroom) < 1 || Number(item.classroom) > 99) continue;
    if (!valid.some((previous) => previous.school.id === value.id && previous.grade === item.grade && previous.classroom === item.classroom)) {
      valid.push({ school: { id: value.id, name: value.name, region: value.region }, grade: Number(item.grade), classroom: Number(item.classroom) });
    }
    if (valid.length === 10) break;
  }
  return valid;
}

export function writeFavorites(storage: Pick<Storage, 'setItem'>, favorites: Favorite[]) {
  storage.setItem('opensigan-favorites', JSON.stringify(favorites));
}

export function readAllergies(storage: Pick<Storage, 'getItem'>) {
  const allergies: unknown = JSON.parse(storage.getItem('opensigan-allergies') || '[]');
  return Array.isArray(allergies)
    ? [...new Set(allergies.filter((id): id is number => Number.isInteger(id) && id >= 1 && id <= 19))].sort((a, b) => a - b)
    : [];
}

export function readMealPreferences(storage: Pick<Storage, 'getItem'>, mealTypes: string[], defaults: MealPreferences) {
  const saved: unknown = JSON.parse(storage.getItem('opensigan-meal-preferences') || 'null');
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

export function readSchoolPreference<T>(storage: Pick<Storage, 'getItem'>, prefix: string, schoolId: string, parse: (value: unknown) => T, fallback: () => T): T {
  try { return parse(JSON.parse(storage.getItem(prefix + schoolId) || 'null')); }
  catch { return fallback(); }
}

export function writeSchoolPreference(storage: Pick<Storage, 'setItem'>, prefix: string, schoolId: string, value: unknown) {
  storage.setItem(prefix + schoolId, JSON.stringify(value));
}
