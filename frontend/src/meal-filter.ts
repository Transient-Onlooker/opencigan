import { allergenMatches } from './allergens';

export type MealAllergyFilter = 'all' | 'marked' | 'unmarked';

export function filterDishes(dishes: string[], query: string, selected: readonly number[], filter: MealAllergyFilter): string[] {
  const term = query.trim().normalize('NFC').toLocaleLowerCase('ko-KR');
  return dishes.filter((dish) => {
    if (term && !dish.normalize('NFC').toLocaleLowerCase('ko-KR').includes(term)) return false;
    const marked = allergenMatches(dish, selected).length > 0;
    return filter === 'all' || (filter === 'marked' ? marked : !marked);
  });
}
