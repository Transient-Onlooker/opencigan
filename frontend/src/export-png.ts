import type { TimetableRecord } from './api';
import { defaultDisplaySettings, displaySubject, displayTeacher, subjectColor, subjectTextColor, type DisplaySettings } from './personalization';

export type ExportView = 'today' | 'week' | 'teacher';

export interface ExportOptions {
  view: ExportView;
  schoolName: string;
  grade: number;
  classroom: number;
  selectedDay: string;
  week: string;
  teacherName: string;
  records: TimetableRecord[];
  dark: boolean;
  displaySettings?: DisplaySettings;
}

type ExportLesson = { title: string; detail: string; color?: string };

function sanitizeFilenamePart(value: string): string {
  return value.normalize('NFC').replace(/[\\/:*?"<>|\x00-\x1F\x7F]/g, '').trim().replace(/\s+/g, '_');
}

export function buildExportFilename(options: ExportOptions, extension: 'png' | 'pdf' = 'png'): string {
  const safeSchool = sanitizeFilenamePart(options.schoolName) || '학교';
  const target = options.view === 'teacher'
    ? sanitizeFilenamePart(options.teacherName || '선생님')
    : `${options.grade || 1}학년${options.classroom || 1}반`;
  const dateOrWeek = sanitizeFilenamePart(options.view === 'today' ? options.selectedDay : options.week);
  const safeExt = extension === 'pdf' ? 'pdf' : 'png';
  const filename = `Opencigan_${safeSchool}_${target}_${options.view}_${dateOrWeek}.${safeExt}`;
  if (filename.length <= 120) return filename;
  return filename.slice(0, 116).replace(/[\uD800-\uDBFF]$/, '') + '.' + extension;
}

function addDate(date: string, offset: number) {
  const value = new Date(date + 'T00:00:00Z');
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
}

function labelDate(date: string) {
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'UTC', month: 'numeric', day: 'numeric', weekday: 'short' }).format(new Date(date + 'T00:00:00Z'));
}

export function createExportGrid(options: ExportOptions) {
  const { view, records, grade, classroom, teacherName, schoolName, selectedDay, week } = options;
  const settings = options.displaySettings ?? defaultDisplaySettings();
  const dates = view === 'today' ? [selectedDay] : Array.from({ length: 5 }, (_, index) => addDate(week, index));
  const selected = records.filter((lesson) => view === 'teacher'
    ? !!teacherName.trim() && lesson.teacher?.trim() === teacherName.trim() && dates.includes(lesson.date)
    : Number(lesson.grade) === Number(grade) && Number(lesson.class) === Number(classroom) && dates.includes(lesson.date));
  const periods = Array.from({ length: Math.max(0, ...selected.map((lesson) => Number(lesson.period)).filter((period) => Number.isInteger(period) && period > 0)) }, (_, index) => index + 1);
  const rows = periods.map((period) => dates.map((date): ExportLesson[] => selected
    .filter((lesson) => lesson.date === date && Number(lesson.period) === period)
    .map((lesson) => ({
      title: view === 'teacher' ? `${lesson.grade}학년 ${lesson.class}반` : displaySubject(lesson.subject, settings),
      detail: view === 'teacher' ? displaySubject(lesson.subject, settings) : settings.showTeachers && lesson.teacher ? displayTeacher(lesson.teacher, settings) : '',
      color: subjectColor(lesson.subject, settings),
    }))));
  return {
    title: schoolName,
    subtitle: view === 'teacher' ? `${displayTeacher(teacherName.trim(), settings)} 선생님 · ${labelDate(dates[0])} ~ ${labelDate(dates[dates.length - 1])}`
      : `${grade}학년 ${classroom}반 · ${view === 'today' ? labelDate(selectedDay) : `${labelDate(dates[0])} ~ ${labelDate(dates[dates.length - 1])}`}`,
    columns: dates.map((date) => settings.showDates || view === 'today'
      ? labelDate(date)
      : new Intl.DateTimeFormat('ko-KR', { timeZone: 'UTC', weekday: 'short' }).format(new Date(date + 'T00:00:00Z'))),
    periods,
    rows,
  };
}

export function wrappedText(ctx: CanvasRenderingContext2D, value: string, maxWidth: number): string[] {
  if (!value) return [''];
  const rawLines = value.split('\n');
  const lines: string[] = [];
  for (const rawLine of rawLines) {
    const tokens = rawLine.split(/(\s+)/);
    let current = '';
    for (const token of tokens) {
      if (!token) continue;
      const candidate = current + token;
      if (ctx.measureText(candidate).width <= maxWidth) {
        current = candidate;
      } else if (current && ctx.measureText(token).width <= maxWidth) {
        lines.push(current.trimEnd());
        current = token.trimStart();
      } else {
        for (const char of Array.from(token)) {
          if (current && ctx.measureText(current + char).width > maxWidth) {
            lines.push(current);
            current = char;
          } else current += char;
        }
      }
    }
    if (current) lines.push(current);
  }
  return lines.length ? lines : [''];
}

export async function createTimetablePng(options: ExportOptions) {
  const grid = createExportGrid(options);
  if (!grid.periods.length) throw new Error('저장할 수업 정보가 없어요.');
  await document.fonts?.ready;

  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  if (!context) throw new Error('이 브라우저에서는 이미지 저장을 지원하지 않아요.');
  const ctx = context;
  const padding = 44;
  const periodWidth = 92;
  const cellWidth = grid.columns.length === 1 ? 450 : 240;
  const width = 2 * padding + periodWidth + cellWidth * grid.columns.length;
  const contentWidth = width - 2 * padding;
  const colors = options.dark
    ? { bg: '#111111', text: '#f5f5f5', sub: '#bcbcbc', line: '#4b4b4b', heading: '#202020' }
    : { bg: '#ffffff', text: '#111111', sub: '#555555', line: '#d4d4d4', heading: '#f5f5f5' };
  const font = '"Pretendard Variable", system-ui, sans-serif';
  ctx.font = `700 32px ${font}`;
  const titleLines = wrappedText(ctx, grid.title, contentWidth);
  ctx.font = `400 17px ${font}`;
  const subtitleLines = wrappedText(ctx, grid.subtitle, contentWidth);
  const headingHeight = padding + titleLines.length * 43 + subtitleLines.length * 25 + 34;
  const rowHeights = grid.rows.map((cells) => {
    let maxHeight = 68;
    for (const lessons of cells) {
      if (!lessons.length) {
        maxHeight = Math.max(maxHeight, 56);
        continue;
      }
      let cellHeight = 16;
      for (let i = 0; i < lessons.length; i++) {
        const lesson = lessons[i];
        ctx.font = `700 20px ${font}`;
        if (i > 0) cellHeight += 10;
        cellHeight += wrappedText(ctx, lesson.title, cellWidth - 24).length * 26;
        if (lesson.detail) {
          ctx.font = `400 16px ${font}`;
          cellHeight += wrappedText(ctx, lesson.detail, cellWidth - 24).length * 22;
        }
        cellHeight += 8;
      }
      maxHeight = Math.max(maxHeight, cellHeight + 16);
    }
    return maxHeight;
  });
  const height = headingHeight + 52 + rowHeights.reduce((sum, row) => sum + row, 0) + padding + 28;
  const maxDimension = 4096;
  const scale = Math.min(2, maxDimension / Math.max(width, height));
  canvas.width = Math.floor(width * scale);
  canvas.height = Math.floor(height * scale);
  if (scale !== 1) {
    ctx.scale(scale, scale);
  }
  ctx.fillStyle = colors.bg;
  ctx.fillRect(0, 0, width, height);
  ctx.textBaseline = 'top';
  ctx.fillStyle = colors.text;
  ctx.font = `700 32px ${font}`;
  let titleY = padding;
  for (const line of titleLines) { ctx.fillText(line, padding, titleY); titleY += 43; }
  ctx.font = `400 17px ${font}`;
  ctx.fillStyle = colors.sub;
  for (const line of subtitleLines) { ctx.fillText(line, padding, titleY + 4); titleY += 25; }

  let y = headingHeight;
  ctx.fillStyle = colors.heading;
  ctx.fillRect(padding, y, contentWidth, 52);
  ctx.textAlign = 'center';
  ctx.fillStyle = colors.text;
  ctx.font = `700 17px ${font}`;
  ctx.fillText('교시', padding + periodWidth / 2, y + 15);
  grid.columns.forEach((column, index) => ctx.fillText(column, padding + periodWidth + cellWidth * (index + .5), y + 15));
  y += 52;
  const verticals = [padding, padding + periodWidth, ...grid.columns.map((_, index) => padding + periodWidth + cellWidth * (index + 1))];
  ctx.strokeStyle = colors.line;
  ctx.lineWidth = 1;
  for (let index = 0; index < grid.rows.length; index++) {
    const row = grid.rows[index];
    const rowHeight = rowHeights[index];
    ctx.beginPath(); ctx.moveTo(padding, y + .5); ctx.lineTo(padding + contentWidth, y + .5); ctx.stroke();
    ctx.textAlign = 'center'; ctx.font = `700 17px ${font}`; ctx.fillStyle = colors.text;
    ctx.fillText(String(grid.periods[index]), padding + periodWidth / 2, y + Math.max(16, (rowHeight - 20) / 2));
    for (let column = 0; column < row.length; column++) {
      const cellLessons = row[column];
      const cellX = padding + periodWidth + column * cellWidth;
      const x = cellX + 12;
      if (!cellLessons.length) {
        ctx.textAlign = 'center';
        ctx.font = `400 16px ${font}`;
        ctx.fillStyle = options.dark ? '#555555' : '#bbbbbb';
        ctx.fillText('—', cellX + cellWidth / 2, y + (rowHeight - 18) / 2);
      } else {
        let textY = y + 12;
        ctx.textAlign = 'left';
        for (let i = 0; i < cellLessons.length; i++) {
          const lesson = cellLessons[i];
          if (i > 0) {
            ctx.strokeStyle = options.dark ? '#333333' : '#ebebeb';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(x - 2, textY - 4.5);
            ctx.lineTo(x + cellWidth - 22, textY - 4.5);
            ctx.stroke();
            textY += 6;
          }
          ctx.font = `700 20px ${font}`;
          const title = wrappedText(ctx, lesson.title, cellWidth - 24);
          ctx.font = `400 16px ${font}`;
          const detail = lesson.detail ? wrappedText(ctx, lesson.detail, cellWidth - 24) : [];
          if (lesson.color) {
            ctx.fillStyle = lesson.color;
            ctx.fillRect(x - 6, textY - 4, cellWidth - 12, title.length * 26 + detail.length * 22 + 8);
          }
          ctx.font = `700 20px ${font}`; ctx.fillStyle = lesson.color ? subjectTextColor(lesson.color) : colors.text;
          for (const line of title) {
            ctx.fillText(line, x, textY); textY += 26;
          }
          if (detail.length) {
            ctx.font = `400 16px ${font}`; ctx.fillStyle = lesson.color ? subjectTextColor(lesson.color) : colors.sub;
            for (const line of detail) {
              ctx.fillText(line, x, textY); textY += 22;
            }
          }
          textY += 8;
        }
      }
    }
    y += rowHeight;
  }
  ctx.beginPath(); ctx.moveTo(padding, y + .5); ctx.lineTo(padding + contentWidth, y + .5); ctx.stroke();
  for (const x of verticals) { ctx.beginPath(); ctx.moveTo(x + .5, headingHeight); ctx.lineTo(x + .5, y); ctx.stroke(); }
  ctx.textAlign = 'right'; ctx.font = `400 14px ${font}`; ctx.fillStyle = colors.sub;
  ctx.fillText('Opencigan · opencigan.mcv.kr', padding + contentWidth, y + 18);

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((value) => value ? resolve(value) : reject(new Error('이미지 생성에 실패했어요.')), 'image/png');
  });
  const filename = buildExportFilename(options, 'png');
  return { blob, filename };
}

function downloadFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export async function saveTimetablePng(options: ExportOptions) {
  const { blob, filename } = await createTimetablePng(options);
  downloadFile(blob, filename);
}

export async function saveTimetablePdf(options: ExportOptions) {
  // PDF export is intended for printing, independent of the screen theme.
  const printOptions = { ...options, dark: false };
  const [{ PDFDocument, PageSizes }, { blob }] = await Promise.all([
    import('pdf-lib'), createTimetablePng(printOptions),
  ]);
  const pdf = await PDFDocument.create();
  const image = await pdf.embedPng(await blob.arrayBuffer());
  const [width, height] = PageSizes.A4;
  const page = pdf.addPage(options.view === 'today' ? [width, height] : [height, width]);
  const size = image.scaleToFit(page.getWidth() - 48, page.getHeight() - 48);
  page.drawImage(image, { ...size, x: (page.getWidth() - size.width) / 2, y: page.getHeight() - size.height - 24 });
  const bytes = await pdf.save();
  const pdfFilename = buildExportFilename(options, 'pdf');
  downloadFile(new Blob([new Uint8Array(bytes)], { type: 'application/pdf' }), pdfFilename);
}

export async function shareTimetablePng(options: ExportOptions): Promise<'shared' | 'downloaded' | 'cancelled'> {
  const { blob, filename } = await createTimetablePng(options);
  if (typeof File !== 'undefined' && typeof navigator.share === 'function') {
    const file = new File([blob], filename, { type: 'image/png' });
    try {
      if (typeof navigator.canShare !== 'function' || navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: `${options.schoolName} 시간표` });
        return 'shared';
      }
    } catch (error) {
      if (error && typeof error === 'object' && 'name' in error && error.name === 'AbortError') return 'cancelled';
      // 공유를 지원하지 않거나 사용자 동작이 만료된 브라우저에서는 파일 저장으로 전환합니다.
    }
  }
  downloadFile(blob, filename);
  return 'downloaded';
}
