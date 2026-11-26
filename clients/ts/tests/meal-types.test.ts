import type { Meal } from '../index.ts';

const withoutOptionalFields: Meal = {
  date: '2026-11-16',
  type: 'lunch',
  dishes: ['Rice'],
};

const withNullableFields: Meal = {
  date: '2026-11-16',
  type: 'lunch',
  dishes: ['Rice'],
  calories: null,
  nutrition: null,
  origin: null,
};

const withTextFields: Meal = {
  date: '2026-11-16',
  type: 'lunch',
  dishes: ['Rice'],
  calories: '650 kcal',
  nutrition: '1.2, 3.4, 5.6',
  origin: 'Rice (domestic)',
};

const invalidFieldType: Meal = {
  date: '2026-11-16',
  type: 'lunch',
  dishes: ['Rice'],
  // @ts-expect-error OpenAPI defines these values as string or null.
  calories: 650,
};

void [withoutOptionalFields, withNullableFields, withTextFields, invalidFieldType];
