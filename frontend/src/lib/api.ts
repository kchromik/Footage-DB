import type {
  AppSettings,
  Clip,
  ClipPage,
  Filters,
  MediaPreview,
  MoveBatch,
  MovePlan,
  Stats,
  SetupStatus,
  SystemCheck,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof Blob)
        ? { 'content-type': 'application/json' }
        : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let detail = `${response.status}`
    try {
      const data = await response.json()
      detail = data.detail ?? detail
    } catch {
      /* Antwort war kein JSON */
    }
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function buildQuery(filters: Filters, offset: number, limit: number, facets: boolean) {
  const params = new URLSearchParams()
  if (filters.q) params.set('q', filters.q)
  if (filters.mode !== 'auto') params.set('mode', filters.mode)
  filters.tags.forEach((tag) => params.append('tag', tag))
  if (filters.folder) params.set('folder', filters.folder)
  if (filters.look) params.set('look', filters.look)
  if (filters.date_from) params.set('date_from', filters.date_from)
  if (filters.date_to) params.set('date_to', filters.date_to)
  if (filters.duration_min) params.set('duration_min', filters.duration_min)
  if (filters.duration_max) params.set('duration_max', filters.duration_max)
  if (filters.favorite) params.set('favorite', 'true')
  if (filters.only_missing) params.set('only_missing', 'true')
  params.set('sort', filters.sort)
  params.set('offset', String(offset))
  params.set('limit', String(limit))
  if (facets) params.set('with_facets', 'true')
  return params.toString()
}

export const api = {
  me: () =>
    request<{ user: string | null; auth_required: boolean; media_root: string }>(
      '/api/auth/me',
    ),
  login: (username: string, password: string) =>
    request<{ user: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),

  clips: (filters: Filters, offset = 0, limit = 60, facets = false) =>
    request<ClipPage>(`/api/clips?${buildQuery(filters, offset, limit, facets)}`),
  clip: (id: number) => request<Clip>(`/api/clips/${id}`),
  updateClip: (id: number, payload: Record<string, unknown>) =>
    request<Clip>(`/api/clips/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  batchTags: (payload: {
    clip_ids: number[]
    add?: string[]
    remove?: string[]
    favorite?: boolean
    look_manual?: string
  }) =>
    request<{ changed: number }>('/api/clips/batch/tags', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  reprocess: (id: number, what: string) =>
    request<{ queued: string[] }>(`/api/clips/${id}/reprocess`, {
      method: 'POST',
      body: JSON.stringify({ what }),
    }),
  deleteClip: (id: number, removeFile: boolean) =>
    request<{ ok: boolean }>(`/api/clips/${id}?remove_file=${removeFile}`, {
      method: 'DELETE',
    }),

  stats: () => request<Stats>('/api/stats'),
  scan: () => request<{ started: boolean; detail?: string }>('/api/scan', { method: 'POST' }),
  jobs: () =>
    request<{ queue: Record<string, number>; items: Record<string, unknown>[] }>(
      '/api/jobs',
    ),
  retryJobs: () => request<{ requeued: number }>('/api/jobs/retry', { method: 'POST' }),
  cleanup: () =>
    request<{ removed_artifacts: number; removed_tags: number }>(
      '/api/maintenance/cleanup',
      { method: 'POST' },
    ),
  purgeMissing: () =>
    request<{ removed: number }>('/api/maintenance/purge-missing', { method: 'POST' }),

  planOrganize: () =>
    request<MovePlan>('/api/organize/plan', { method: 'POST', body: JSON.stringify({}) }),
  applyOrganize: () =>
    request<{ batch: string; moved: number; failed: number }>('/api/organize/apply', {
      method: 'POST',
      body: JSON.stringify({ confirm: true }),
    }),
  batches: () => request<{ items: MoveBatch[] }>('/api/organize/batches'),
  undoBatch: (batch: string) =>
    request<{ reverted: number; failed: number }>(`/api/organize/undo/${batch}`, {
      method: 'POST',
    }),

  tags: () =>
    request<{
      items: { id: number; name: string; category: string; count: number }[]
      by_category: Record<string, { name: string; count: number }[]>
    }>('/api/tags'),

  initUpload: (filename: string, size: number, subdir = '', tags: string[] = []) =>
    request<{
      id: string
      chunk_size: number
      chunk_count: number
      received: number[]
      resumed: boolean
    }>('/api/uploads/init', {
      method: 'POST',
      body: JSON.stringify({ filename, size, subdir, tags }),
    }),
  uploadChunk: async (id: string, index: number, blob: Blob, signal?: AbortSignal) => {
    const response = await fetch(`/api/uploads/${id}/chunk/${index}`, {
      method: 'PUT',
      body: blob,
      credentials: 'same-origin',
      signal,
    })
    if (!response.ok) throw new ApiError(`Block ${index} fehlgeschlagen`, response.status)
    return response.json()
  },
  completeUpload: (id: string) =>
    request<{ clip_id: number; path: string }>(`/api/uploads/${id}/complete`, {
      method: 'POST',
    }),
  abortUpload: (id: string) =>
    request<{ ok: boolean }>(`/api/uploads/${id}`, { method: 'DELETE' }),

  zipUrl: (ids: number[]) => `/api/media/zip?ids=${ids.join(',')}`,

  setupStatus: () => request<SetupStatus>('/api/setup/status'),
  systemCheck: () => request<SystemCheck>('/api/setup/check'),
  mediaPreview: () => request<MediaPreview>('/api/setup/preview'),
  patternPreview: (pattern: string) =>
    request<{ pattern: string; example: string }>('/api/setup/pattern-preview', {
      method: 'POST',
      body: JSON.stringify({ pattern }),
    }),
  completeSetup: (payload: Record<string, unknown>) =>
    request<{ complete: boolean; scan_started: boolean }>('/api/setup/complete', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  settings: () => request<AppSettings>('/api/settings'),
  updateSettings: (payload: Record<string, unknown>) =>
    request<AppSettings>('/api/settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
}
