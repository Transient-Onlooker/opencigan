export interface School {
  id: string;
  name: string;
  region: string;
  address?: string;
}

export interface TimetableRecord {
  grade: number;
  class: number | string;
  date: string;
  period: number;
  subject: string;
  teacher: string | null;
  isChanged: boolean;
}

export interface TimetableResponse {
  sourceLessonStarts?: Record<string, string>;
  schoolId: string;
  weekStart: string;
  records: TimetableRecord[];
  sourceUpdatedAt: string | null;
  fetchedAt: string;
  stale: boolean;
  cacheStatus?: 'hit' | 'miss' | 'stale';
}

export interface Meal {
  date: string;
  type: string;
  dishes: string[];
}

export interface MealsResponse {
  meals: Meal[];
  stale: boolean;
}

export interface HistoryLesson {
  subject: string;
  teacher: string | null;
}

export interface TimetableChange {
  observedAt: string;
  grade: number;
  class: number | string;
  date: string;
  period: number;
  type: string;
  before: HistoryLesson | null;
  after: HistoryLesson | null;
}

export interface TimetableHistoryResponse {
  changes: TimetableChange[];
  nextCursor: string | null;
}

export interface SchoolSearchResponse {
  schools: School[];
  stale: boolean;
}

export interface StatusResponse {
  status: string;
  scope: string;
}

export interface ClientOptions {
  baseUrl?: string;
  timeoutMs?: number;
  fetch?: typeof globalThis.fetch;
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface TimetableFilterOptions extends RequestOptions {
  grade?: number;
  class?: number;
  teacher?: string;
}

export type SubscriptionMode = 'periods' | 'summary' | 'timed';

export interface IcsOptions {
  weeks?: 1 | 2;
  mode?: SubscriptionMode;
  times?: string;
  teacher?: string;
}

export interface IcsRequestOptions extends IcsOptions, RequestOptions {
  ifNoneMatch?: string;
}

export interface IcsResult {
  data: string | null;
  notModified: boolean;
  etag: string | null;
}

export interface HistoryOptions extends RequestOptions {
  cursor?: string | null;
}

export class OpensiganError extends Error {
  readonly status?: number;
  readonly code?: string;
  readonly isTimeout: boolean;
  readonly isNetworkError: boolean;
  readonly retryAfter?: string;

  constructor(message: string, options: { status?: number; code?: string; isTimeout?: boolean; isNetworkError?: boolean; retryAfter?: string } = {}) {
    super(message);
    this.name = 'OpensiganError';
    this.status = options.status;
    this.code = options.code;
    this.isTimeout = Boolean(options.isTimeout);
    this.isNetworkError = Boolean(options.isNetworkError);
    this.retryAfter = options.retryAfter;
  }
}

function validateTimeout(timeoutMs: number): number {
  if (!Number.isInteger(timeoutMs) || timeoutMs <= 0 || timeoutMs > 2_147_483_647) {
    throw new OpensiganError('timeoutMs must be an integer from 1 to 2147483647.', { code: 'invalid_config' });
  }
  return timeoutMs;
}

export class OpensiganClient {
  readonly baseUrl: string;
  readonly timeoutMs: number;
  private readonly customFetch?: typeof globalThis.fetch;

  constructor(options: ClientOptions = {}) {
    let url: URL;
    try {
      url = new URL(options.baseUrl ?? 'http://127.0.0.1:8000');
    } catch {
      throw new OpensiganError('baseUrl must be an absolute HTTP(S) URL.', { code: 'invalid_config' });
    }
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname ||
        url.username || url.password || url.search || url.hash) {
      throw new OpensiganError('baseUrl must use HTTP(S) without credentials, query or fragment.', { code: 'invalid_config' });
    }
    this.baseUrl = url.href.replace(/\/+$/, '');
    this.timeoutMs = validateTimeout(options.timeoutMs ?? 15000);
    this.customFetch = options.fetch;
  }

  private async request<T>(path: string, options?: RequestOptions & { calendar?: boolean; ifNoneMatch?: string }): Promise<T> {
    const timeout = AbortSignal.timeout(validateTimeout(options?.timeoutMs ?? this.timeoutMs));
    const signal = options?.signal ? AbortSignal.any([options.signal, timeout]) : timeout;
    const headers: Record<string, string> = { Accept: options?.calendar ? 'text/calendar' : 'application/json' };
    if (options?.ifNoneMatch) headers['If-None-Match'] = options.ifNoneMatch;
    let status: number | undefined;
    try {
      signal.throwIfAborted();
      const response = await (this.customFetch ?? globalThis.fetch)(`${this.baseUrl}${path}`, { signal, headers });
      status = response.status;
      const etag = response.headers.get('ETag');
      if (options?.calendar && status === 304) {
        return { data: null, notModified: true, etag } as T;
      }
      const text = await response.text();
      if (options?.calendar && response.ok) {
        return { data: text, notModified: false, etag } as T;
      }

      let body: unknown;
      try {
        body = JSON.parse(text);
      } catch (error) {
        if (!(error instanceof SyntaxError)) throw error;
        if (response.ok) {
          throw new OpensiganError('Response is not valid JSON.', { status, code: 'invalid_response' });
        }
      }
      if (!response.ok) {
        const code = body && typeof body === 'object' && 'code' in body && typeof body.code === 'string'
          ? body.code : undefined;
        const message = body && typeof body === 'object' && 'error' in body && typeof body.error === 'string'
          ? body.error : `Request failed (HTTP ${status}).`;
        throw new OpensiganError(message, { status, code, retryAfter: response.headers.get('Retry-After') ?? undefined });
      }
      if (!body || typeof body !== 'object' || Array.isArray(body)) {
        throw new OpensiganError('Response must be a JSON object.', { status, code: 'invalid_response' });
      }
      return body as T;
    } catch (error) {
      if (options?.signal?.aborted) throw options.signal.reason;
      if (timeout.aborted) {
        throw new OpensiganError('Request timed out.', { status, isTimeout: true });
      }
      if (error instanceof TypeError) {
        throw new OpensiganError('Unable to connect to the API or read its response.', { status, isNetworkError: true });
      }
      throw error;
    }
  }

  async getStatus(options?: RequestOptions): Promise<StatusResponse> {
    return this.request<StatusResponse>('/api/v1/status', options);
  }

  async searchSchools(query: string, options?: RequestOptions): Promise<SchoolSearchResponse> {
    const q = query.trim();
    return this.request<SchoolSearchResponse>(`/api/v1/schools?q=${encodeURIComponent(q)}`, options);
  }

  async searchNeisSchools(query: string, options?: RequestOptions): Promise<SchoolSearchResponse> {
    const q = query.trim();
    return this.request<SchoolSearchResponse>(`/api/v1/neis/schools?q=${encodeURIComponent(q)}`, options);
  }

  async getTimetable(school: string, week: string, options?: TimetableFilterOptions): Promise<TimetableResponse> {
    const params = new URLSearchParams();
    params.set('school', school.trim());
    params.set('week', week.trim());
    if (options?.grade !== undefined) params.set('grade', String(options.grade));
    if (options?.class !== undefined) params.set('class', String(options.class));
    if (options?.teacher !== undefined) params.set('teacher', options.teacher);
    return this.request<TimetableResponse>(`/api/v1/timetable?${params.toString()}`, options);
  }

  getTimetableIcsUrl(school: string, grade: number, classroom: number, options?: IcsOptions): string {
    const params = new URLSearchParams();
    params.set('school', school.trim());
    params.set('grade', String(grade));
    params.set('class', String(classroom));
    if (options?.weeks !== undefined) params.set('weeks', String(options.weeks));
    if (options?.mode !== undefined) params.set('mode', options.mode);
    if (options?.times !== undefined) params.set('times', options.times);
    if (options?.teacher !== undefined) params.set('teacher', options.teacher);
    return `${this.baseUrl}/api/v1/timetable.ics?${params.toString()}`;
  }

  async getTimetableIcs(school: string, grade: number, classroom: number, options?: IcsRequestOptions): Promise<IcsResult> {
    const url = this.getTimetableIcsUrl(school, grade, classroom, options);
    return this.request<IcsResult>(url.slice(this.baseUrl.length), { ...options, calendar: true });
  }

  async getMeals(school: string, fromDate: string, toDate: string, options?: RequestOptions): Promise<MealsResponse> {
    const params = new URLSearchParams();
    params.set('school', school.trim());
    params.set('from', fromDate.trim());
    params.set('to', toDate.trim());
    return this.request<MealsResponse>(`/api/v1/meals?${params.toString()}`, options);
  }

  async getTimetableHistory(school: string, week: string, options?: HistoryOptions): Promise<TimetableHistoryResponse> {
    const params = new URLSearchParams();
    params.set('school', school.trim());
    params.set('week', week.trim());
    if (options?.cursor !== undefined && options.cursor !== null) params.set('cursor', options.cursor);
    return this.request<TimetableHistoryResponse>(`/api/v1/timetable/history?${params.toString()}`, options);
  }
}
