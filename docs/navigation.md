# Navigation State & Browser History Integration

Opencigan uses browser history state (`window.history.state`) to keep application views, selected dates, and classroom context synchronized with the browser navigation without modifying or overwriting URL fragments used by the sharing feature.

## Architecture & Principles

- **Fragment Preservation**: The URL hash/fragment is dedicated to `shareClassUrl` and class sharing links. Navigation state is never written to URL fragments or search parameters.
- **Namespaced History**: All navigation data is stored in `history.state.opensigan`. Any existing or external keys in `history.state` are preserved during `pushState` and `replaceState`.
- **Deduplication**: Pushing an identical navigation state is a no-op, preventing bloated history stacks.
- **Safe Popstate**: The `subscribeNavigation` listener delivers parsed states or `null` when the state is missing or invalid. It executes without initiating secondary or recursive history pushes.
- **Window Injection**: All navigation functions accept an optional window object (`NavigationHistoryWindow`), allowing deterministic testing with mock history objects.

## Data Structures

```ts
export type NavigationView = 'timetable' | 'meals' | 'settings';
export type TimetableViewMode = 'today' | 'week' | 'grade' | 'teacher';

export interface NavigationState {
  version: 1;
  view: NavigationView;
  timetableView: TimetableViewMode;
  school: School | null;
  grade: number;      // Integer 1..6
  classroom: number;  // Integer 1..99
  week: string;       // YYYY-MM-DD Monday (clamped to current or next week)
  selectedDay: string;// YYYY-MM-DD within week (week .. week + 6)
  mealDate: string;   // YYYY-MM-DD valid ISO calendar date 1900..9999
}
```

## API Reference

### `parseNavigationState(value: unknown, currentMonday: string): NavigationState | null`
Validates and parses a raw state object (e.g., from `history.state.opensigan`). Returns a clean `NavigationState` if all schema and domain rules match, or `null` if the payload is missing, invalid, or out of range.

### `getNavigationFromHistory(currentMonday: string, win?: NavigationHistoryWindow): NavigationState | null`
Reads the current `history.state.opensigan` from the target window and returns the parsed navigation state.

### `replaceNavigationState(state: NavigationState, win?: NavigationHistoryWindow): boolean`
Replaces the current history entry with the updated navigation state under the `opensigan` key, preserving any other keys in `history.state`.

### `pushNavigationState(state: NavigationState, currentMonday: string, win?: NavigationHistoryWindow): boolean`
Pushes a new history entry if the proposed `state` is not equal to the current state in history. Returns `true` if a new entry was pushed, and `false` if deduplicated.

### `areNavigationStatesEqual(a: NavigationState | null | undefined, b: NavigationState | null | undefined): boolean`
Compares two navigation states for field-level equality.

### `subscribeNavigation(currentMonday: string, callback: (state: NavigationState | null) => void, win?: NavigationHistoryWindow): () => void`
Subscribes to browser `popstate` events. Emits the parsed state or `null` whenever the user navigates through history. Returns an unsubscribe function.

## Integration Example for Root (App.svelte)

```ts
import {
  parseNavigationState,
  getNavigationFromHistory,
  replaceNavigationState,
  pushNavigationState,
  subscribeNavigation,
  type NavigationState
} from './navigation';

// 1. Initial State Sync
const initialNav = getNavigationFromHistory(currentMonday);
if (initialNav) {
  applyNavigation(initialNav);
} else {
  // Replace current history entry with initial state
  replaceNavigationState(buildCurrentNavState());
}

// 2. Listen to back/forward button navigation
const unsubscribe = subscribeNavigation(currentMonday, (nav) => {
  if (nav) {
    applyNavigation(nav, false); // do not re-push during popstate
  }
});

// 3. User interactions (view switch, date pick, etc.)
function onUserNavigate() {
  const nextState = buildCurrentNavState();
  pushNavigationState(nextState, currentMonday);
}
```

