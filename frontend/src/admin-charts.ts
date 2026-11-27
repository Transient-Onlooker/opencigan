export interface AnalyticsChartSummary {
  daily?: Array<{
    day: string;
    visitors?: number | null;
    sessions?: number | null;
    page_views?: number | null;
    api_requests?: number | null;
  }>;
  apiHourly?: Array<{
    hour: string;
    requests?: number | null;
    errors?: number | null;
    upstream_errors?: number | null;
    overload_errors?: number | null;
    cache_hits?: number | null;
    cache_misses?: number | null;
    stale_responses?: number | null;
  }>;
  routes?: Array<{
    route: string;
    requests?: number | null;
    errors?: number | null;
    data_failures?: number | null;
    overload_errors?: number | null;
    unclassified_server_errors?: number | null;
    avg_ms?: number | null;
    cache_observed?: number | null;
    cache_hits?: number | null;
    cache_misses?: number | null;
    stale_responses?: number | null;
  }>;
}

type Datum = { label: string; values: Array<number | null> };
type Series = { key: string; label: string; color: string };

const SVG = 'http://www.w3.org/2000/svg';
const numberFormat = new Intl.NumberFormat('ko-KR');
const dateFormat = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', timeZone: 'Asia/Seoul' });
const hourFormat = new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', hourCycle: 'h23', timeZone: 'Asia/Seoul' });

function kstDate(day: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return day;
  const parsed = new Date(`${match[1]}-${match[2]}-${match[3]}T00:00:00+09:00`);
  return Number.isNaN(parsed.valueOf()) ? day : dateFormat.format(parsed);
}

function kstHour(hour: string): string {
  const parsed = new Date(hour);
  return Number.isNaN(parsed.valueOf()) ? hour : hourFormat.format(parsed);
}

function svgElement(doc: Document, name: string, attributes: Record<string, string> = {}): SVGElement {
  const element = doc.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function makeChart(doc: Document, title: string, description: string, data: Datum[], series: Series[]): HTMLElement {
  const section = doc.createElement('section');
  section.className = 'admin-chart';
  const heading = doc.createElement('h3');
  heading.className = 'admin-chart__heading';
  heading.textContent = title;
  const legend = doc.createElement('ul');
  legend.className = 'admin-chart__legend';

  for (const item of series) {
    const entry = doc.createElement('li');
    const swatch = doc.createElement('span');
    swatch.className = 'admin-chart__swatch';
    swatch.style.backgroundColor = item.color;
    swatch.setAttribute('aria-hidden', 'true');
    const label = doc.createElement('span');
    label.textContent = item.label;
    entry.append(swatch, label);
    legend.append(entry);
  }

  const width = 920;
  const top = 18;
  const left = Math.min(210, Math.max(88, ...data.map((row) => Math.min(200, row.label.length * 8 + 16))));
  const right = 24;
  const rowHeight = Math.max(32, series.length * 18);
  const height = top + Math.max(1, data.length) * rowHeight + 30;
  const chart = svgElement(doc, 'svg', {
    class: 'admin-chart__svg', viewBox: `0 0 ${width} ${height}`, role: 'img',
    'aria-label': `${title}. ${description}`,
  });
  const plotWidth = width - left - right;
  const groupHeight = rowHeight / Math.max(1, series.length);
  const maxValue = Math.max(1, ...data.flatMap((row) => row.values.filter((value): value is number => value !== null && Number.isFinite(value))));

  for (let index = 0; index <= 4; index += 1) {
    const x = left + plotWidth * index / 4;
    chart.append(svgElement(doc, 'line', { x1: String(x), y1: String(top), x2: String(x), y2: String(height - 20), class: 'admin-chart__grid' }));
    const tick = svgElement(doc, 'text', { x: String(x), y: String(height - 4), 'text-anchor': 'middle', class: 'admin-chart__tick' });
    tick.textContent = numberFormat.format(maxValue * index / 4);
    chart.append(tick);
  }

  data.forEach((row, rowIndex) => {
    const y = top + rowIndex * rowHeight;
    const label = svgElement(doc, 'text', { x: String(left - 10), y: String(y + rowHeight / 2 + 4), 'text-anchor': 'end', class: 'admin-chart__label' });
    label.textContent = row.label;
    chart.append(label);

    series.forEach((item, seriesIndex) => {
      const value = row.values[seriesIndex];
      const barY = y + seriesIndex * groupHeight + 3;
      if (value === null || !Number.isFinite(value)) {
        const missing = svgElement(doc, 'text', { x: String(left + 4), y: String(barY + groupHeight - 3), class: 'admin-chart__missing' });
        missing.textContent = `${item.label}: 자료 없음`;
        chart.append(missing);
        return;
      }

      const barWidth = Math.max(0, value / maxValue * plotWidth);
      if (value === 0) {
        chart.append(svgElement(doc, 'circle', { cx: String(left), cy: String(barY + (groupHeight - 6) / 2), r: '3', fill: item.color, 'aria-label': `${row.label} ${item.label}: 0` }));
      } else {
        chart.append(svgElement(doc, 'rect', { x: String(left), y: String(barY), width: String(barWidth), height: String(Math.max(2, groupHeight - 6)), rx: '2', fill: item.color, 'aria-label': `${row.label} ${item.label}: ${numberFormat.format(value)}` }));
      }
      const valueLabel = svgElement(doc, 'text', { x: String(Math.min(width - right, left + barWidth + 7)), y: String(barY + groupHeight - 3), class: 'admin-chart__value' });
      valueLabel.textContent = numberFormat.format(value);
      chart.append(valueLabel);
    });
  });

  section.append(heading, legend, chart);
  return section;
}

export function createAnalyticsCharts(summary: AnalyticsChartSummary, doc: Document = document): HTMLElement[] {
  const dailySeries: Series[] = [
    { key: 'visitors', label: '방문자', color: '#2563eb' },
    { key: 'sessions', label: '세션', color: '#7c3aed' },
    { key: 'page_views', label: '페이지 조회', color: '#0891b2' },
    { key: 'api_requests', label: 'API 요청', color: '#ea580c' },
  ];
  const hourlySeries: Series[] = [
    { key: 'requests', label: '요청', color: '#2563eb' },
    { key: 'errors', label: '오류', color: '#dc2626' },
    { key: 'upstream_errors', label: '조회 실패', color: '#ea580c' },
    { key: 'overload_errors', label: '과부하 차단', color: '#7c3aed' },
  ];
  const routeSeries: Series[] = [
    { key: 'requests', label: '요청', color: '#2563eb' },
    { key: 'errors', label: '오류', color: '#dc2626' },
  ];
  const cacheSeries: Series[] = [
    { key: 'cache_hits', label: '적중', color: '#16803d' },
    { key: 'cache_misses', label: '미스', color: '#2563eb' },
    { key: 'stale_responses', label: '이전 캐시', color: '#c2410c' },
  ];
  const toData = (rows: Array<Record<string, unknown>>, labelKey: string, series: Series[], format: (label: string) => string): Datum[] =>
    rows.map((row) => ({
      label: format(String(row[labelKey] ?? '')),
      values: series.map(({ key }) => typeof row[key] === 'number' && Number.isFinite(row[key]) ? row[key] as number : null),
    }));
  const charts: HTMLElement[] = [];

  if (summary.daily) charts.push(makeChart(doc, '일별 이용', '날짜별 방문자, 세션, 페이지 조회, API 요청 수입니다. 자료 누락은 자료 없음으로 표시합니다.', toData(summary.daily, 'day', dailySeries, kstDate), dailySeries));
  if (summary.apiHourly) charts.push(makeChart(doc, '시간별 API 요청', '한국 시간 기준 시간대별 요청과 오류 수입니다. 요청이 없던 시간대는 응답 자료에 포함되지 않습니다.', toData(summary.apiHourly, 'hour', hourlySeries, kstHour), hourlySeries));
  if (summary.apiHourly) charts.push(makeChart(doc, '시간별 캐시 응답', '캐시 상태가 기록된 적중, 미스, 이전 캐시 응답 건수입니다. 자료가 제공되지 않으면 자료 없음으로 표시합니다.', toData(summary.apiHourly, 'hour', cacheSeries, kstHour), cacheSeries));
  if (summary.apiHourly) {
    const errors = summary.apiHourly.map((row) => ({ label: kstHour(row.hour), values: [typeof row.requests === 'number' && row.requests > 0 && typeof row.errors === 'number' ? Math.round(row.errors / row.requests * 1000) / 10 : null] }));
    charts.push(makeChart(doc, '시간별 API 오류율 (%)', '각 시간의 오류 응답 수를 전체 API 요청 수로 나눈 값입니다.', errors, [{ key: 'rate', label: '오류율 %', color: '#dc2626' }]));
  }
  if (summary.routes) charts.push(makeChart(doc, 'API 경로별 이용', '경로별 요청과 오류 수입니다. 자료 누락은 0과 구별합니다.', toData(summary.routes, 'route', routeSeries, (label) => label), routeSeries));
  if (summary.routes) charts.push(makeChart(doc, 'API 경로별 평균 응답 시간 (ms)', '기록된 요청의 평균 처리 시간입니다.', toData(summary.routes, 'route', [{ key: 'avg_ms', label: '평균 ms', color: '#7c3aed' }], (label) => label), [{ key: 'avg_ms', label: '평균 ms', color: '#7c3aed' }]));
  if (summary.routes) {
    const rates: Series[] = [{ key: 'hit', label: '적중 %', color: '#16803d' }, { key: 'miss', label: '미스 %', color: '#2563eb' }, { key: 'stale', label: '이전 캐시 %', color: '#c2410c' }];
    const rows = summary.routes.map((route) => {
      const denominator = route.cache_observed;
      const ratio = (value: number | null | undefined) => typeof denominator === 'number' && denominator > 0 && typeof value === 'number' ? Math.round(value / denominator * 1000) / 10 : null;
      return { label: route.route, values: [ratio(route.cache_hits), ratio(route.cache_misses), ratio(route.stale_responses)] };
    });
    charts.push(makeChart(doc, 'API 경로별 캐시 비율 (%)', '분모는 캐시 상태가 기록된 응답 수입니다. 기록이 없으면 자료 없음으로 표시합니다.', rows, rates));
  }
  return charts;
}
