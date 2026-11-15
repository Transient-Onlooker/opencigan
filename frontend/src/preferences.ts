export type MealPreferences = { view: 'day' | 'week'; types: string[]; showAllergenNumbers: boolean };

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
