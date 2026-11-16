export function currentKoreaDate(now: Date): string {
  return new Date(now.getTime() + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

export function addDays(key: string, n: number): string {
  const date = new Date(`${key}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}

export function monday(key: string): string {
  const day = new Date(`${key}T00:00:00Z`).getUTCDay();
  return addDays(key, -((day + 6) % 7));
}

export function clampWeek(week: string, current: string): string {
  const first = monday(current);
  const last = addDays(first, 7);
  return week < first ? first : week > last ? last : week;
}

export function pasteDate(event: ClipboardEvent): void {
  const text = event.clipboardData?.getData('text/plain').trim() ?? '';
  const match = /^(\d{4})(?:-(\d{2})-(\d{2})|(\d{2})(\d{2}))$/.exec(text);
  if (!match) return;
  const input = event.currentTarget as HTMLInputElement;
  const previous = input.value;
  input.value = `${match[1]}-${match[2] ?? match[4]}-${match[3] ?? match[5]}`;
  if (!input.value) { input.value = previous; return; }
  event.preventDefault();
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}
