import type { School } from './api';

export function shareClassUrl(href: string, school: School, grade: number, classroom: number) {
  const url = new URL(href);
  url.search = '';
  url.hash = new URLSearchParams({ school: school.id, name: school.name, region: school.region, grade: String(grade), class: String(classroom) }).toString();
  return url.href;
}

export function readSharedClass(hash: string) {
  if (hash.length > 4096) return null;
  const params = new URLSearchParams(hash.replace(/^#/, ''));
  if (['school', 'name', 'region', 'grade', 'class'].some((key) => params.getAll(key).length !== 1)) return null;
  const id = params.get('school')!, name = params.get('name')!, region = params.get('region')!;
  const gradeText = params.get('grade')!, classText = params.get('class')!;
  if (!/^[0-9]+:[^:]{1,50}$/.test(id) || id.length > 100 || !name.trim() || name.length > 50 || region.length > 100 || !/^[1-6]$/.test(gradeText) || !/^[1-9][0-9]?$/.test(classText)) return null;
  return { school: { id, name, region }, grade: Number(gradeText), classroom: Number(classText) };
}
