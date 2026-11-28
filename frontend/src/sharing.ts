import type { School } from './api';

export function shareClassUrl(href: string, school: School, grade: number, classroom: number) {
  const url = new URL(href);
  url.search = '';
  url.hash = new URLSearchParams({ school: school.id, name: school.name, region: school.region, grade: String(grade), class: String(classroom) }).toString();
  return url.href;
}

export type SharedClassReadResult =
  | { status: 'absent' }
  | { status: 'invalid'; reason: 'encoding' | 'fields' | 'value' | 'length' }
  | { status: 'valid'; value: { school: School; grade: number; classroom: number } };

export function inspectSharedClass(hash: string): SharedClassReadResult {
  if (!hash) return { status: 'absent' };
  if (hash.length > 4096) return { status: 'invalid', reason: 'length' };
  const raw = hash.replace(/^#/, '');
  const params = new URLSearchParams(raw);
  const keys = ['school', 'name', 'region', 'grade', 'class'];
  if (!keys.some((key) => params.has(key))) return { status: 'absent' };
  for (const part of raw.split('&')) {
    const separator = part.indexOf('=');
    const value = separator < 0 ? '' : part.slice(separator + 1);
    try { decodeURIComponent(value.replace(/\+/g, ' ')); }
    catch { return { status: 'invalid', reason: 'encoding' }; }
  }
  if (keys.some((key) => params.getAll(key).length !== 1)) return { status: 'invalid', reason: 'fields' };
  const id = params.get('school')!, name = params.get('name')!, region = params.get('region')!;
  const gradeText = params.get('grade')!, classText = params.get('class')!;
  if (!/^[0-9]+:[^:]{1,50}$/.test(id) || id.length > 100 || !name.trim() || name.length > 50 || region.length > 100 || !/^[1-6]$/.test(gradeText) || !/^[1-9][0-9]?$/.test(classText)) return { status: 'invalid', reason: 'value' };
  return { status: 'valid', value: { school: { id, name, region }, grade: Number(gradeText), classroom: Number(classText) } };
}

export function readSharedClass(hash: string) {
  const result = inspectSharedClass(hash);
  return result.status === 'valid' ? result.value : null;
}
